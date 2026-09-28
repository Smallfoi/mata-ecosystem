"""Анти-брутфорс для входа в админку (D-39).

Лимиты DRF (`common/throttling.py`) защищают только API: они живут в DRF-вью. Django-админка
— обычные вью Django, и её форма входа `/admin/login/` не была прикрыта ничем. При этом за
админкой стоят деньги (возвраты), персональные данные и публикация контента, а имя
пользователя у первого админа предсказуемое. Перебор пароля был возможен без ограничений.

Считаем НЕУДАЧНЫЕ попытки в двух разрезах сразу (D-68):
- **по IP** — против перебора паролей с одной машины;
- **по логину** — против перебора ОДНОЙ учётной записи с меняющихся адресов. Только
  по IP этого не поймать: ботнет или список прокси даёт по девять попыток с адреса и
  идёт дальше. Учётную запись владельца перебирают именно так, а логин у неё
  предсказуемый.

Удачный вход обнуляет оба счётчика. Превышение любого — 429 до конца окна. Счётчик в
кэше: в проде это общий Redis, поэтому лимит работает на всех воркерах gunicorn сразу
(как и остальные лимиты, D-07).

IP берём из `X-Real-IP` — его проставляет наш nginx (см. `nginx/mata.conf.example`).
`REMOTE_ADDR` за прокси равен адресу самого прокси: по нему блокировка одного пользователя
заблокировала бы всех.
"""
from django.contrib.auth.signals import user_logged_in, user_login_failed
from django.core.cache import cache
from django.dispatch import receiver
from django.http import HttpResponse

from common.clientip import client_ip

MAX_FAILS = 10          # попыток с одного адреса
MAX_FAILS_USER = 8      # попыток по одному логину, с любых адресов
WINDOW_SECONDS = 900    # 15 минут
_PREFIX = "adminlogin"

_login_path = None


def _client_ip(request) -> str:
    # Единый источник адреса (аудит D03): X-Real-IP учитывается, только если запрос
    # пришёл от нашего прокси. Имя оставлено — его импортирует accounts.otp_guard.
    return client_ip(request)


def _key(ip: str) -> str:
    return f"{_PREFIX}:{ip}"


def _norm_user(name) -> str:
    """Логин к общему виду: регистр и пробелы не должны давать новый счётчик."""
    return (str(name or "").strip().lower())[:150]


def _user_key(name: str) -> str:
    return f"{_PREFIX}:u:{_norm_user(name)}"


def _bump(key: str):
    try:
        # add() ставит TTL только при создании: окно считается от ПЕРВОЙ неудачи,
        # иначе каждая следующая попытка продлевала бы окно сама себе.
        cache.add(key, 0, WINDOW_SECONDS)
        cache.incr(key)
    except Exception:
        pass  # сбой кэша не должен ломать вход


def _count(key: str) -> int:
    try:
        return cache.get(key) or 0
    except Exception:
        return 0


def admin_login_path() -> str:
    """Путь формы входа в админку (кэшируем — reverse на каждый запрос не нужен)."""
    global _login_path
    if _login_path is None:
        try:
            from django.urls import reverse

            _login_path = reverse("admin:login")
        except Exception:
            _login_path = "/admin/login/"
    return _login_path


@receiver(user_login_failed)
def _count_failure(sender, credentials=None, request=None, **kwargs):
    if request is None:
        return
    _bump(_key(_client_ip(request)))
    name = (credentials or {}).get("username")
    if name:
        _bump(_user_key(name))


@receiver(user_logged_in)
def _reset_on_success(sender, request=None, user=None, **kwargs):
    if request is None:
        return
    try:
        cache.delete(_key(_client_ip(request)))
        if user is not None:
            cache.delete(_user_key(user.get_username()))
    except Exception:
        pass


class AdminLoginRateLimitMiddleware:
    """Блокирует отправку формы входа в админку после MAX_FAILS неудач с одного IP."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method == "POST" and request.path == admin_login_path():
            over_ip = _count(_key(_client_ip(request))) >= MAX_FAILS
            # Логин читаем из тела запроса до того, как форма его обработает.
            name = request.POST.get("username")
            over_user = bool(name) and _count(_user_key(name)) >= MAX_FAILS_USER
            if over_ip or over_user:
                return HttpResponse(
                    "Слишком много попыток входа. Попробуйте через 15 минут.",
                    status=429,
                    content_type="text/plain; charset=utf-8",
                )
        return self.get_response(request)

