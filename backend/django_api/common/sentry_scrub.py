"""Вычистка персональных данных из событий об ошибках (D-32, 152-ФЗ).

Зачем это отдельно от `send_default_pii=False`. Тот флаг выключает только то, что
SDK добавляет САМ: тело запроса, cookies, IP. Но персональные данные попадают в
событие и другим путём — их приносит сам код:

    ValueError: пользователь +79148278470 не найден
    KeyError: 'burv@infostart14.ru'
    локальные переменные кадра стека: token='eyJhbGciOi...'

Такое уедет в трекер ошибок как есть. Для нас это значит: телефоны и почты
покупателей утекают в систему, где их никто не ждёт, а хранение ПДн у нас
ограничено по замыслу (LAUNCH_READINESS §2) и по закону.

Поэтому событие проходит через эту вычистку целиком — сообщения, значения
переменных, теги, крошки — и всё, что похоже на телефон, почту, токен или карту,
заменяется на «[скрыто]». Ошибку это не портит: тип, место и стек остаются,
а разбирать причину по номеру телефона всё равно не приходится.

**Правило безопасности:** ни одна ошибка внутри вычистки не должна отменить
отправку события. Сломанный `before_send` означает, что мы перестаём видеть
ошибки вообще — то есть лечение хуже болезни. Поэтому здесь всё в try/except,
и при любом сбое событие уходит как есть.
"""
import re

REDACTED = "[скрыто]"

# Глубина и длина ограничены намеренно: событие может содержать огромные вложенные
# структуры, и обход «до конца» превратил бы вычистку в тормоз на горячем пути.
MAX_DEPTH = 12
MAX_STRING = 8192

# Ключи, значение которых не нужно даже смотреть — вырезаем целиком.
SECRET_KEYS = (
    "password", "passwd", "secret", "token", "authorization", "auth",
    "cookie", "csrf", "api_key", "apikey", "private", "dsn", "signature",
)

_PATTERNS = (
    # Телефон РФ: +7/8 и десять цифр, с любыми разделителями между ними.
    re.compile(r"(?<!\d)(?:\+7|8)[\s\-()]*\d{3}[\s\-()]*\d{3}[\s\-()]*\d{2}[\s\-()]*\d{2}(?!\d)"),
    # Почта.
    re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"),
    # JWT: три части через точку, начинается с заголовка base64 `{"alg"`.
    re.compile(r"eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+"),
    # Длинная шестнадцатеричная строка — обычно ключ, хэш пароля или id сессии.
    re.compile(r"(?<![A-Za-z0-9])[0-9a-fA-F]{32,}(?![A-Za-z0-9])"),
    # Номер карты: 13–19 цифр группами.
    re.compile(r"(?<!\d)(?:\d[ \-]?){13,19}(?!\d)"),
)


def scrub_text(value: str) -> str:
    """Заменить в строке всё, что похоже на персональные данные."""
    if len(value) > MAX_STRING:
        value = value[:MAX_STRING] + "…"
    for pattern in _PATTERNS:
        value = pattern.sub(REDACTED, value)
    return value


def _is_secret_key(key) -> bool:
    low = str(key).lower()
    return any(marker in low for marker in SECRET_KEYS)


def scrub(value, depth: int = 0):
    """Пройти структуру события и вычистить всё чувствительное."""
    if depth > MAX_DEPTH:
        return value
    if isinstance(value, str):
        return scrub_text(value)
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            out[key] = REDACTED if _is_secret_key(key) else scrub(item, depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        cleaned = [scrub(item, depth + 1) for item in value]
        return type(value)(cleaned) if isinstance(value, tuple) else cleaned
    return value


def before_send(event, hint):
    """Хук sentry_sdk: чистим событие перед отправкой."""
    try:
        return scrub(event)
    except Exception:
        # Лучше отправить неочищенное событие, чем не отправить никакого.
        return event


def before_breadcrumb(crumb, hint):
    """Хук sentry_sdk: крошки тоже несут данные — адреса запросов, сообщения."""
    try:
        return scrub(crumb)
    except Exception:
        return crumb
