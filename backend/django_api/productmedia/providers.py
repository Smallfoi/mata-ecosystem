"""Провайдер image-обработки фотопайплайна.

Сейчас — OpenAI gpt-image-1 (правка изображения по референсу). Ходим наружу через
stdlib urllib (как остальной проект, без лишних зависимостей). Секреты — из окружения:
  OPENAI_API_KEY   — ключ (в коде НЕТ; репозиторий публичный);
  OPENAI_BASE_URL  — адрес API; по умолчанию OpenAI, но можно указать прокси/агрегатор
                     (прод в РФ, OpenAI РФ блокирует — тогда сюда адрес релея).
Без ключа провайдер выключен (no-op) — труба строится, но не гоняет.
Сетевой вызов вынесен в _post_multipart — его мокаем в тестах.
"""
import base64
import json
import os
import threading
import urllib.error
import urllib.request
import uuid

_TIMEOUT = 300  # ожидание одного чтения; генерация идёт до ~2 мин (идём стримом, см. edit_image)

DEFAULT_BASE = "https://api.openai.com/v1"


class ImageProviderError(Exception):
    pass


def openai_enabled() -> bool:
    return bool((os.environ.get("OPENAI_API_KEY") or "").strip())


def base_url() -> str:
    return (os.environ.get("OPENAI_BASE_URL") or DEFAULT_BASE).rstrip("/")


def _sniff(data):
    """Тип картинки по первым байтам: (content-type, расширение). Раньше всё уходило как PNG."""
    head = bytes(data[:12])
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", "jpg"
    if head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        return "image/webp", "webp"
    return "image/png", "png"


def _multipart(fields, files):
    """Сборка multipart/form-data вручную (urllib не умеет сам).

    files — список (имя поля, имя файла, байты, content-type).
    """
    boundary = "----mata" + uuid.uuid4().hex
    parts = []
    for key, val in fields.items():
        parts.append(b"--" + boundary.encode())
        parts.append(('Content-Disposition: form-data; name="%s"' % key).encode())
        parts.append(b"")
        parts.append(str(val).encode("utf-8"))
    for field, name, data, ctype in files:
        parts.append(b"--" + boundary.encode())
        parts.append((
            'Content-Disposition: form-data; name="%s"; filename="%s"' % (field, name)
        ).encode())
        parts.append(("Content-Type: %s" % ctype).encode())
        parts.append(b"")
        parts.append(data)
    parts.append(b"--" + boundary.encode() + b"--")
    parts.append(b"")
    body = b"\r\n".join(parts)
    return "multipart/form-data; boundary=" + boundary, body


# Расход токенов последнего вызова — для учёта стоимости. Отдельно на каждый поток: в
# воркере Celery задания идут параллельно, и чужой расход не должен смешиваться.
_last = threading.local()


def last_usage():
    """Сколько токенов ушло на последнюю генерацию в этом потоке (dict из ответа OpenAI или None)."""
    return getattr(_last, "usage", None)


def _open(req):
    """Открыть запрос к провайдеру — напрямую или через OPENAI_PROXY.

    Прод в РФ, а OpenAI стоит за Cloudflare, который передаёт страну исходного
    посетителя даже при запросе из Cloudflare-воркера. Поэтому прокси на Cloudflare
    гео-блок не обходят; нужен обычный прокси вне РФ (VPS). OPENAI_PROXY =
    http://host:port — прямой HTTP-прокси (CONNECT): TLS идёт насквозь до OpenAI,
    прокси ключа не видит. Действует ТОЛЬКО на вызовы OpenAI, остальные внешние
    вызовы прода (1С, оплата, звонки) идут как раньше.
    """
    proxy = (os.environ.get("OPENAI_PROXY") or "").strip()
    if not proxy:
        return urllib.request.urlopen(req, timeout=_TIMEOUT)
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"https": proxy, "http": proxy}))
    return opener.open(req, timeout=_TIMEOUT)


def _post_multipart(path, content_type, body):
    """Единая точка сетевого вызова к провайдеру (мокается в тестах)."""
    key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    req = urllib.request.Request(base_url() + path, data=body, method="POST")
    req.add_header("Authorization", "Bearer " + key)
    req.add_header("Content-Type", content_type)
    # User-Agent ОБЯЗАТЕЛЕН: без него urllib шлёт "Python-urllib/…", и релей за Cloudflare
    # рубит запрос бот-защитой (ошибка 1010). curl в бот-листах не значится (им же и показаны
    # примеры в доках Cloudflare). Переопределяется OPENAI_USER_AGENT при необходимости.
    req.add_header("User-Agent",
                   (os.environ.get("OPENAI_USER_AGENT") or "curl/8.5.0").strip())
    try:
        with _open(req) as resp:
            hdrs = getattr(resp, "headers", None)
            ctype = (hdrs.get("Content-Type", "") if hdrs is not None else "") or ""
            if "text/event-stream" in ctype:
                return _parse_sse(resp)
            return json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        detail = (e.read().decode("utf-8", "ignore") or "")[:500]
        raise ImageProviderError("OpenAI HTTP %s: %s" % (e.code, detail))
    except urllib.error.URLError as e:
        raise ImageProviderError("сеть недоступна: %s" % e)


def _parse_sse(lines):
    """Разбор потокового ответа (SSE) правки картинки → {"data": [{"b64_json": ...}]}.

    Зачем стрим: без него до готовности картинки (до ~2 мин) по соединению не идёт ни
    байта, и прокси/Cloudflare рвут его как зависшее («Remote end closed connection»).
    В стриме OpenAI шлёт промежуточные кадры (image_edit.partial_image), в конце —
    image_edit.completed с итоговой картинкой; её и берём.
    """
    final = None
    buf = []

    def flush():
        nonlocal final
        if not buf:
            return
        payload = "\n".join(buf)
        buf.clear()
        if payload.strip() == "[DONE]":
            return
        try:
            ev = json.loads(payload)
        except ValueError:
            return
        if not isinstance(ev, dict):
            return
        if ev.get("type") == "error" or "error" in ev:
            raise ImageProviderError(
                "OpenAI stream error: %s" % json.dumps(ev.get("error", ev), ensure_ascii=False)[:500])
        if str(ev.get("type", "")).endswith(".completed") and ev.get("b64_json"):
            final = ev["b64_json"]
            if isinstance(ev.get("usage"), dict):
                _last.usage = ev["usage"]

    for raw in lines:
        line = raw.decode("utf-8", "ignore") if isinstance(raw, bytes) else raw
        line = line.rstrip("\r\n")
        if line == "":
            flush()
        elif line.startswith("data:"):
            buf.append(line[5:].lstrip())
    flush()
    return {"data": [{"b64_json": final}]} if final else {"data": []}


def edit_image(source_bytes, prompt, size="1024x1536", high_fidelity=True,
               extra_images=None) -> bytes:
    """Правка картинки по референсу (gpt-image). Возвращает байты мастера.

    high_fidelity=high лучше сохраняет исходный товар (важно для каталога).
    extra_images — крупные планы принта: уходят следующими картинками в том же запросе,
    чтобы модель срисовала мелкий текст, а не придумала его.
    """
    _last.usage = None
    if not openai_enabled():
        raise ImageProviderError("OPENAI_API_KEY не задан — провайдер выключен")
    model = (os.environ.get("OPENAI_IMAGE_MODEL") or "gpt-image-1").strip()
    # stream + partial_images: соединение живое всю генерацию (см. _parse_sse)
    fields = {"model": model, "prompt": prompt, "size": size, "n": "1",
              "stream": "true", "partial_images": "2"}
    # input_fidelity понимают только модели gpt-image-1* (1, 1-mini, 1.5); gpt-image-2.5
    # отвечает на него 400 invalid_input_fidelity_model, новые модели и так держат исходник.
    if high_fidelity and model.startswith("gpt-image-1"):
        fields["input_fidelity"] = "high"
    images = [source_bytes] + [b for b in (extra_images or []) if b][:15]  # OpenAI: до 16
    field = "image[]" if len(images) > 1 else "image"
    files = []
    for i, img in enumerate(images):
        ctype_img, ext = _sniff(img)
        files.append((field, "ref%d.%s" % (i, ext), img, ctype_img))
    ctype, body = _multipart(fields, files)
    data = _post_multipart("/images/edits", ctype, body)
    if getattr(_last, "usage", None) is None and isinstance(data.get("usage"), dict):
        _last.usage = data["usage"]
    items = data.get("data") or []
    b64 = items[0].get("b64_json") if items else None
    if not b64:
        raise ImageProviderError("пустой ответ провайдера")
    return base64.b64decode(b64)
