"""Вход по одноразовому коду — провайдер подключается переменными окружения (D-24, D-50).

Без `SMS_PROVIDER` — dev-режим: код входа всегда «1234», ничего никуда не уходит.
С провайдером генерируем код, отправляем и сверяем сами. Код лежит в кэше Django
(в проде — общий Redis, D-07; LocMem на нескольких воркерах не годится).

**Длина кода — 4 цифры.** Не «на всякий случай»: поля ввода в приложениях и на
сайте рассчитаны ровно на 4 символа, а flashcall физически не может дать больше —
кодом там служат последние 4 цифры звонящего номера. Пока код был шестизначным,
пользователь просто не смог бы его ввести.

Провайдеры:

- **SIGMA messaging** (`SMS_PROVIDER=sigma`, D-50) — основной. Канал по умолчанию
  `flashcall`: клиенту звонят, он вводит последние 4 цифры номера. Дешевле SMS и
  не требует зарегистрированного имени отправителя. Канал `sms` — резерв, ему имя
  отправителя нужно.
- **SIGMA ProPush** (`SMS_PROVIDER=propush`, D-50) — сервис аутентификации поверх тех же
  каналов. Отличается принципиально: код генерирует и проверяет ОН, а не мы, и часть
  каналов «бескодовые» — пользователь подтверждает вход кнопкой на своём телефоне, вводить
  нечего. Поэтому здесь мы храним не код, а `requestId` сессии.
- **smsc.ru** (`SMS_PROVIDER=smsc`) — прежний вариант, оставлен запасным.

SDK и веб-виджет провайдера нам не нужны: всё делается обычными HTTP-запросами с сервера.
Это важно, потому что их SDK написан на TypeScript, а виджет рассчитан на сайт — в мобильные
приложения его не вставить.
"""
import json
import os
import secrets
import urllib.error
import urllib.parse
import urllib.request

from django.core.cache import cache

_DEV_CODE = "1234"
_OTP_TTL = 300        # срок жизни кода — 5 минут
_MAX_ATTEMPTS = 5     # сверок на один код
_TIMEOUT = 10         # сек на запрос к провайдеру

_SIGMA_API = "https://online.sigmasms.ru/api/sendings"
_PROPUSH_API = "https://user.sigmasms.ru/api/n/otp-handler"


def sms_enabled() -> bool:
    """Включён ли реальный провайдер (иначе dev-режим с кодом 1234)."""
    return bool(os.environ.get("SMS_PROVIDER"))


def code_length() -> int:
    """Сколько цифр в коде. Меньше 4 небезопасно, больше — не введут в поле."""
    try:
        return max(4, min(6, int(os.environ.get("OTP_CODE_LENGTH") or 4)))
    except ValueError:
        return 4


class _DevSmsProvider:
    def send(self, phone, code) -> bool:
        print(f"[OTP dev] {phone}: {code}")  # реально не отправляем
        return True


class _SmscProvider:
    """smsc.ru — активен при SMS_PROVIDER=smsc + SMS_LOGIN/SMS_PASSWORD."""

    def send(self, phone, code) -> bool:
        import urllib.parse

        login = os.environ.get("SMS_LOGIN", "")
        password = os.environ.get("SMS_PASSWORD", "")
        if not login or not password:
            return False
        params = urllib.parse.urlencode({
            "login": login, "psw": password, "phones": phone,
            "mes": f"Код входа в МАТА: {code}", "fmt": 3, "charset": "utf-8",
        })
        try:
            url = f"https://smsc.ru/sys/send.php?{params}"
            with urllib.request.urlopen(url, timeout=_TIMEOUT) as resp:
                return resp.status == 200
        except Exception:
            return False


class _SigmaProvider:
    """SIGMA messaging: flashcall (основной) и SMS (резерв).

    Про flashcall важно понимать одно: код придумываем МЫ и передаём его в
    `payload.text` — провайдер лишь звонит с номера, оканчивающегося на эти цифры.
    Значит проверка кода остаётся на нашей стороне, ровно как с SMS, и смена
    канала ничего не меняет в логике входа.

    `SIGMA_FALLBACK` — канал на случай, когда основной не отправился (например,
    оператор не пропускает звонок). Пусто — не пробовать: честная ошибка лучше,
    чем неожиданный расход на второй канал.
    """

    def send(self, phone, code) -> bool:
        channel = (os.environ.get("SIGMA_CHANNEL") or "flashcall").strip().lower()
        if self._send_via(channel, phone, code):
            return True
        fallback = (os.environ.get("SIGMA_FALLBACK") or "").strip().lower()
        if fallback and fallback != channel:
            return self._send_via(fallback, phone, code)
        return False

    def _send_via(self, channel, phone, code) -> bool:
        token = (os.environ.get("SIGMA_TOKEN") or "").strip()
        if not token:
            return False
        sender = (os.environ.get("SIGMA_SENDER") or "MATA").strip()
        # У flashcall текст — это и есть код (последние цифры звонящего номера),
        # у SMS — сообщение целиком.
        text = code if channel == "flashcall" else f"Код входа в МАТА: {code}"
        body = json.dumps({
            "recipient": phone,
            "type": channel,
            "payload": {"sender": sender, "text": text},
        }).encode("utf-8")
        req = urllib.request.Request(
            _SIGMA_API,
            data=body,
            headers={"Authorization": token, "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                return 200 <= resp.status < 300
        except Exception:
            return False


def _propush_call(method, path, body=None, params=""):
    """Запрос к ProPush. Возвращает (код ответа, тело-словарь) или (0, {}) при обрыве."""
    token = (os.environ.get("SIGMA_TOKEN") or "").strip()
    if not token:
        return 0, {}
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Authorization": token}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        f"{_PROPUSH_API}{path}{params}", data=data, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8") or "{}"
            return resp.status, json.loads(raw)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8") or "{}")
        except Exception:
            return e.code, {}
    except Exception:
        return 0, {}


class _ProPushProvider:
    """SIGMA ProPush: провайдер сам генерирует, доставляет и проверяет код.

    Наша роль — открыть сессию, отдать клиенту тип канала (нужно ли вводить код)
    и в конце подтвердить результат. Последним шагом всегда идёт «атомарная
    проверка и закрытие сессии»: она отрабатывает успешно ровно один раз, и это
    то, что защищает от повторного использования одной и той же аутентификации.
    """

    def start(self, phone):
        """Открыть сессию. Возвращает requestId или пустую строку."""
        widget = (os.environ.get("SIGMA_WIDGET") or "").strip()
        if not widget:
            return ""
        # Поле называется именно `widgetId` — сверено с документацией провайдера
        # (user.sigmasms.ru/documentation/api/OTP). С `widget` запрос отклонялся.
        code, data = _propush_call(
            "POST", "", {"widgetId": widget, "recipient": phone}
        )
        return str(data.get("requestId") or "") if 200 <= code < 300 else ""

    def channel(self, request_id):
        """Текущий канал доставки: нужно ли вводить код и сколько попыток осталось."""
        code, data = _propush_call("GET", f"/{request_id}/channel")
        if not (200 <= code < 300):
            return {}
        return {
            "type": data.get("type") or "",
            "status": data.get("status") or "",
            "codeType": data.get("codeType") or "code",
            "attemptsLeft": data.get("remainingCodeAttempts"),
        }

    def check(self, request_id, code):
        """Проверить введённый код (кодовые каналы)."""
        status, data = _propush_call(
            "POST", f"/{request_id}/checkCode", {"code": str(code)}
        )
        return 200 <= status < 300 and bool(data.get("success"))

    def resend(self, request_id):
        """Переключить доставку на следующий канал виджета.

        Ради этого ProPush и брали вместо ручной отправки: если SimPush не дошёл,
        сервис сам переходит к звонку, потом к SMS. Без этого вызова человек
        с недоставленным кодом просто упирается в тупик.

        Тела у запроса нет — провайдер требует именно так.
        """
        status, data = _propush_call("POST", f"/{request_id}/resend")
        return 200 <= status < 300 and bool(data.get("success"))

    def complete(self, request_id, phone):
        """Финальная проверка + закрытие сессии. Успешна только один раз."""
        status, data = _propush_call(
            "POST",
            f"/{request_id}/checkStatusAndComplete",
            params=f"?recipient={urllib.parse.quote(phone)}",
        )
        return 200 <= status < 300 and bool(data.get("success"))


def propush_widget_status():
    """Жив ли виджет: активен и не заблокирован.

    Нужно для проверки готовности к запуску. Заблокированный виджет выглядит
    как «вход просто не работает», и без этой проверки причину пришлось бы
    искать в логах.
    """
    widget = (os.environ.get("SIGMA_WIDGET") or "").strip()
    if not widget:
        return {"ok": False, "reason": "SIGMA_WIDGET не задан"}
    code, data = _propush_call("GET", f"/widget/{widget}")
    if not (200 <= code < 300):
        return {"ok": False, "reason": f"провайдер ответил {code or 'обрывом связи'}"}
    if data.get("isBlocked"):
        return {"ok": False, "reason": "виджет заблокирован", "name": data.get("name")}
    if not data.get("isActive"):
        return {"ok": False, "reason": "виджет неактивен", "name": data.get("name")}
    return {"ok": True, "name": data.get("name") or ""}


def resend_code(phone) -> bool:
    """Отправить код заново, сменив канал (только ProPush)."""
    if not _is_propush():
        return request_code(phone)
    rec = cache.get(f"otp:{phone}") or {}
    request_id = rec.get("requestId")
    if not request_id:
        return False
    return _ProPushProvider().resend(request_id)


def _provider():
    name = (os.environ.get("SMS_PROVIDER") or "").strip().lower()
    if name == "propush":
        return _ProPushProvider()
    if name == "sigma":
        return _SigmaProvider()
    if name == "smsc":
        return _SmscProvider()
    return _DevSmsProvider()


def _is_propush() -> bool:
    return (os.environ.get("SMS_PROVIDER") or "").strip().lower() == "propush"


def request_code(phone) -> bool:
    """Начать вход по коду. False — провайдер отправку не принял.

    Два разных мира. У обычных провайдеров код придумываем мы и кладём его в кэш
    ДО отправки: если провайдер ответил ошибкой, но звонок всё же прошёл, человек
    сможет войти. У ProPush код придумывает провайдер, поэтому храним `requestId`
    сессии — по нему потом и проверяем.
    """
    if _is_propush():
        request_id = _ProPushProvider().start(phone)
        if not request_id:
            return False
        cache.set(f"otp:{phone}", {"requestId": request_id}, _OTP_TTL)
        return True

    length = code_length()
    code = f"{secrets.randbelow(10 ** length):0{length}d}"
    cache.set(f"otp:{phone}", {"code": code, "attempts": 0}, _OTP_TTL)
    return _provider().send(phone, code)


def channel_info(phone) -> dict:
    """Чем сейчас подтверждается вход: кодом или кнопкой на телефоне.

    Клиент спрашивает это, чтобы решить, показывать ли поле для кода. У обычных
    провайдеров ответ всегда один и тот же — код; у ProPush канал может смениться
    прямо посреди сессии, поэтому его надо переспрашивать.
    """
    if not _is_propush():
        return {"codeType": "code", "type": "sms", "status": "sent"}
    rec = cache.get(f"otp:{phone}") or {}
    request_id = rec.get("requestId")
    if not request_id:
        return {}
    return _ProPushProvider().channel(request_id)


def check_code(phone, code) -> bool:
    """Подтверждён ли вход для этого телефона.

    Dev (без провайдера) — принимаем 1234. У обычных провайдеров сверяем код с
    отправленным. У ProPush: если код введён — отдаём на проверку провайдеру,
    а затем в любом случае закрываем сессию «атомарной проверкой». Пустой код —
    это бескодовый канал: человек подтвердил вход на телефоне, и нам остаётся
    только спросить результат.
    """
    code = (code or "").strip()
    if not sms_enabled():
        return code == _DEV_CODE

    if _is_propush():
        rec = cache.get(f"otp:{phone}") or {}
        request_id = rec.get("requestId")
        if not request_id:
            return False
        provider = _ProPushProvider()
        if code and not provider.check(request_id, code):
            return False
        # Закрываем сессию сами: провайдер не делает этого автоматически, а
        # незакрытая сессия — это вход, которым можно воспользоваться повторно.
        if not provider.complete(request_id, phone):
            return False
        cache.delete(f"otp:{phone}")
        return True

    rec = cache.get(f"otp:{phone}")
    if not rec or rec.get("attempts", 0) >= _MAX_ATTEMPTS:
        return False
    rec["attempts"] += 1
    cache.set(f"otp:{phone}", rec, _OTP_TTL)
    if code and code == rec.get("code"):
        cache.delete(f"otp:{phone}")  # одноразовый
        return True
    return False
