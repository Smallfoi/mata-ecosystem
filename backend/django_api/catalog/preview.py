"""Черновики каталога (`?preview=1`) — только сотрудникам.

Раньше `?preview=1` сам по себе открывал неопубликованные товары и баннеры любому, кто
допишет параметр в адрес. Теперь нужен пропуск сотрудника — подписанный токен превью
`preview_token` (параметр или заголовок X-Preview-Token). Его выдаёт Конструктор
(/admin/merch/, только сотрудник со вторым фактором) и передаёт во фрейм сайта/приложения
в параметре `pt`; фрейм пересылает его API. Сессия админки не годится: фреймы живут на
другом домене и cookie админки не шлют (а DRF у нас без session-auth).
Токен подписан SECRET_KEY, живёт PREVIEW_TOKEN_TTL и проверяется по живому аккаунту
сотрудника (уволили/сняли is_staff — токен перестаёт работать).
Без пропуска `?preview=1` молча игнорируется: отдаётся обычная витрина (не 403),
чтобы старые сборки и ссылки не ломались.
"""
from django.contrib.auth import get_user_model
from django.core import signing

SALT = "catalog.preview"
PREVIEW_TOKEN_TTL = 12 * 3600   # рабочий день в Конструкторе; дальше — перезагрузить его
_TRUE = {"1", "true", "True", "yes"}


def issue_token(user) -> str:
    """Подписанный токен превью для сотрудника (выдаёт страница Конструктора)."""
    return signing.TimestampSigner(salt=SALT).sign(str(user.pk))


def _staff_user(user) -> bool:
    return bool(user and user.is_authenticated and user.is_active and user.is_staff)


def _token_ok(token: str) -> bool:
    if not token:
        return False
    try:
        pk = signing.TimestampSigner(salt=SALT).unsign(token, max_age=PREVIEW_TOKEN_TTL)
    except signing.BadSignature:                 # подделка или истёк (SignatureExpired)
        return False
    user = get_user_model().objects.filter(pk=pk).first()
    return _staff_user(user)


def is_preview(request) -> bool:
    """preview=1 И пропуск сотрудника → отдаём черновики. Иначе — только опубликованное."""
    params = getattr(request, "query_params", request.GET)
    if params.get("preview") not in _TRUE:
        return False
    token = params.get("preview_token") or request.headers.get("X-Preview-Token", "")
    return _token_ok(token)
