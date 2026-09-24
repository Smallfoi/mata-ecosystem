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
import urllib.error
import urllib.request
import uuid

_TIMEOUT = 120  # генерация картинки — десятки секунд

DEFAULT_BASE = "https://api.openai.com/v1"


class ImageProviderError(Exception):
    pass


def openai_enabled() -> bool:
    return bool((os.environ.get("OPENAI_API_KEY") or "").strip())


def base_url() -> str:
    return (os.environ.get("OPENAI_BASE_URL") or DEFAULT_BASE).rstrip("/")


def _multipart(fields, file_field, file_name, file_bytes, file_type="image/png"):
    """Сборка multipart/form-data вручную (urllib не умеет сам)."""
    boundary = "----mata" + uuid.uuid4().hex
    parts = []
    for key, val in fields.items():
        parts.append(b"--" + boundary.encode())
        parts.append(('Content-Disposition: form-data; name="%s"' % key).encode())
        parts.append(b"")
        parts.append(str(val).encode("utf-8"))
    parts.append(b"--" + boundary.encode())
    parts.append((
        'Content-Disposition: form-data; name="%s"; filename="%s"'
        % (file_field, file_name)
    ).encode())
    parts.append(("Content-Type: %s" % file_type).encode())
    parts.append(b"")
    parts.append(file_bytes)
    parts.append(b"--" + boundary.encode() + b"--")
    parts.append(b"")
    body = b"\r\n".join(parts)
    return "multipart/form-data; boundary=" + boundary, body


def _post_multipart(path, content_type, body):
    """Единая точка сетевого вызова к провайдеру (мокается в тестах)."""
    key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    req = urllib.request.Request(base_url() + path, data=body, method="POST")
    req.add_header("Authorization", "Bearer " + key)
    req.add_header("Content-Type", content_type)
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        detail = (e.read().decode("utf-8", "ignore") or "")[:500]
        raise ImageProviderError("OpenAI HTTP %s: %s" % (e.code, detail))
    except urllib.error.URLError as e:
        raise ImageProviderError("сеть недоступна: %s" % e)


def edit_image(source_bytes, prompt, size="1024x1536", high_fidelity=True) -> bytes:
    """Правка картинки по референсу через gpt-image-1. Возвращает PNG-байты (мастер).

    high_fidelity=high лучше сохраняет исходный товар (важно для каталога).
    """
    if not openai_enabled():
        raise ImageProviderError("OPENAI_API_KEY не задан — провайдер выключен")
    fields = {"model": "gpt-image-1", "prompt": prompt, "size": size, "n": "1"}
    if high_fidelity:
        fields["input_fidelity"] = "high"
    ctype, body = _multipart(fields, "image", "source.png", source_bytes)
    data = _post_multipart("/images/edits", ctype, body)
    items = data.get("data") or []
    b64 = items[0].get("b64_json") if items else None
    if not b64:
        raise ImageProviderError("пустой ответ провайдера")
    return base64.b64decode(b64)
