"""Проверка доступа к вкладке — одна дверь для всех страниц админки (S-12).

Правило: доступ разрешает ТОЛЬКО запись в базе. Ни идентификатор в адресе, ни
поле в форме, ни пункт меню не дают прав — меню лишь прячет то, что и так
закрыто на сервере. Поэтому «подставить чужой id в ссылке» тут ничего не даёт:
уровень считается по текущему пользователю из сессии, а не по тому, что в URL.
"""
from functools import wraps

from django.core.exceptions import PermissionDenied
from django.urls import NoReverseMatch, reverse

from .models import LEVEL_FULL, LEVEL_NONE, LEVEL_RANK, LEVEL_VIEW, TabPermission
from .tabs import BY_KEY, TABS

_CACHE_ATTR = "_mata_tab_levels"

# Свои адреса у страниц, не привязанных к модели.
PAGE_URLS = {
    "dashboard": "admin:index",
    "merch": "merch_console",
    "errors": "errors_console",
    "storage": "admin_storage",
    "onec_log": "onec_log",
    # У вкладки «Забеги» рабочая страница — разбор помеченных, а не список.
    "runs": "runs_review",
    "loyalty_settings": "loyalty_program",
}


def tab_url(tab) -> str:
    """Адрес вкладки: для страниц — своё имя, для моделей — список записей."""
    name = PAGE_URLS.get(tab.key)
    if not name and tab.models:
        app, model = tab.models[0].split(".")
        name = f"admin:{app}_{model}_changelist"
    try:
        return reverse(name) if name else ""
    except NoReverseMatch:
        return ""


def levels_for(user) -> dict:
    """Все уровни пользователя разом, один запрос на запрос-страницу."""
    if user is None or not getattr(user, "is_authenticated", False):
        return {}
    if not user.is_active:
        return {}
    if user.is_superuser:
        return {t.key: LEVEL_FULL for t in TABS}
    cached = getattr(user, _CACHE_ATTR, None)
    if cached is None:
        cached = {
            p.tab: p.level
            for p in TabPermission.objects.filter(user=user).only("tab", "level")
            if p.tab in BY_KEY
        }
        setattr(user, _CACHE_ATTR, cached)
    return cached


def tab_level(user, key: str) -> str:
    return levels_for(user).get(key, LEVEL_NONE)


def can(user, key: str, need: str = LEVEL_VIEW) -> bool:
    """Хватает ли прав. Сотрудник обязан быть действующим и иметь вход в админку."""
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if not (user.is_active and user.is_staff):
        return False
    return LEVEL_RANK[tab_level(user, key)] >= LEVEL_RANK[need]


def visible_tabs(user):
    """Вкладки, которые человеку вообще видно — в порядке меню."""
    lv = levels_for(user)
    return [t for t in TABS if LEVEL_RANK.get(lv.get(t.key, LEVEL_NONE), 0) >= 1]


def tab_required(key: str, need: str = LEVEL_VIEW):
    """Закрыть страницу вкладкой. Нет прав — 403, а не переход на вход:
    человек уже вошёл, ему нужен честный отказ, а не круг по логину."""
    def deco(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if not can(request.user, key, need):
                raise PermissionDenied("Нет доступа к этому разделу")
            return view(request, *args, **kwargs)
        return wrapper
    return deco


def superuser_required(view):
    """Только владелец. Отдельно от вкладок: этим правом нельзя поделиться.

    Проверяем не «является ли суперпользователем», а «та ли это закреплённая
    запись» (S-13): случайно всплывший флаг суперпользователя сюда не пустит.
    """
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        from .owner import is_owner

        user = request.user
        if not (getattr(user, "is_authenticated", False) and user.is_active
                and user.is_staff and user.is_superuser and is_owner(user)):
            raise PermissionDenied("Раздел доступен только владельцу")
        return view(request, *args, **kwargs)
    return wrapper


def nav_permission(key: str):
    """Для бокового меню: показывать пункт, только если вкладка открыта."""
    return lambda request: can(getattr(request, "user", None), key, LEVEL_VIEW)


def superuser_only(request) -> bool:
    from .owner import is_owner

    return is_owner(getattr(request, "user", None))
