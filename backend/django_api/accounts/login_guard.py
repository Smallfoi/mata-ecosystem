"""Лимит неудачных входов по паролю на ОДИН аккаунт (аудит D03).

Лимит `auth` (20 в минуту) считает запросы с одного адреса. Против перебора пароля
одного человека с многих адресов (ботнет, список прокси, мобильные адреса, которые
у оператора меняются) он бессилен: по 19 попыток с адреса — и дальше. Здесь второй
разрез, как у входа в админку (D-68): неудачи считаются по телефону/почте, с каких
бы адресов они ни шли.

- **8 неудач за 15 минут** на один телефон (или почту в легаси-входе) → дальше 429
  до конца окна, даже с верным паролем: иначе перебор просто продолжится;
- удачный вход обнуляет счётчик, заблокированный аккаунт (403) не считается неудачей;
- считаем только НЕУДАЧИ: человек, который входит часто и правильно, не упрётся;
- владелец номера не заперт: вход по коду (`phone/request` + `phone/verify`) и сброс
  пароля идут своим путём. У них свои лимиты: 5 сверок на код и 3 кода на номер в
  сутки (`accounts/sms.py`, `otp_guard`, D-76) — поэтому здесь их не дублируем.

Счётчик в кэше: на проде это общий Redis, лимит один на все воркеры (D-07). Сбой кэша
вход не ломает.
"""
import functools

from django.core.cache import cache
from rest_framework.response import Response

from common.security import normalize_phone

MAX_FAILS = 8
WINDOW_SECONDS = 15 * 60
_PREFIX = "pwdlogin"

TOO_MANY_TEXT = (
    "Слишком много неудачных попыток входа. Попробуйте через 15 минут "
    "или войдите по коду из звонка/SMS."
)


def _account_key(data):
    """Ключ счётчика по тому, ЧТО вводят: телефон (основной путь) или почта (легаси)."""
    try:
        phone = normalize_phone(data.get("phone") or "")
        if phone:
            return f"{_PREFIX}:p:{phone}"
        email = str(data.get("email") or "").strip().lower()[:254]
        if email:
            return f"{_PREFIX}:e:{email}"
    except Exception:
        pass
    return None


def _fails(key):
    try:
        return cache.get(key) or 0
    except Exception:
        return 0


def _bump(key):
    try:
        # add() ставит срок только при создании: окно считается от ПЕРВОЙ неудачи,
        # иначе каждая следующая попытка продлевала бы блокировку сама себе.
        cache.add(key, 0, WINDOW_SECONDS)
        cache.incr(key)
    except Exception:
        pass


def _reset(key):
    try:
        cache.delete(key)
    except Exception:
        pass


def limit_failures(view):
    """Декоратор вьюхи входа по паролю: 401 — неудача, 200 — успех (обнуляет)."""

    @functools.wraps(view)
    def wrapper(request, *args, **kwargs):
        key = _account_key(request.data)
        if key and _fails(key) >= MAX_FAILS:
            return Response(
                {"detail": TOO_MANY_TEXT, "retryAfter": WINDOW_SECONDS},
                status=429,
                headers={"Retry-After": str(WINDOW_SECONDS)},
            )
        response = view(request, *args, **kwargs)
        if key:
            if response.status_code == 401:
                _bump(key)
            elif response.status_code == 200:
                _reset(key)
        return response

    return wrapper
