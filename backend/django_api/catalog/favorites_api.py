"""Избранное на едином аккаунте: `/v1/favorites` (аудит сайта 26.11.2026, пункт 6).

Одно избранное на сайт и приложение Store — по токену аккаунта. Ключ — модель
витрины (`/v1/models` → key). Гость копит избранное у себя (localStorage / prefs);
после входа клиент отправляет его в `POST /v1/favorites/merge` — ничего не теряется.

    GET    /v1/favorites               → {"keys": [...]}  (новые первыми)
    PUT    /v1/favorites/<key>         → {"keys": [...]}  добавить (повтор — не ошибка)
    DELETE /v1/favorites/<key>         → {"keys": [...]}  убрать
    POST   /v1/favorites/merge {keys}  → {"keys": [...]}  слить список гостя
"""
from django.db import IntegrityError, transaction
from rest_framework.decorators import api_view
from rest_framework.response import Response

from common.security import user_id_from_request

from .models import Favorite

MAX_FAVORITES = 500     # больше — уже не «избранное»; защищает от мусорных запросов
MAX_KEY = 80


def _keys(uid: str) -> list:
    return list(Favorite.objects.filter(user_id=uid).values_list("model_key", flat=True))


def _clean(key) -> str:
    key = str(key or "").strip()
    return key if 0 < len(key) <= MAX_KEY else ""


def _add(uid: str, keys) -> None:
    have = set(_keys(uid))
    room = MAX_FAVORITES - len(have)
    fresh = []
    for k in keys:
        k = _clean(k)
        if k and k not in have and room > 0:
            have.add(k)
            fresh.append(Favorite(user_id=uid, model_key=k))
            room -= 1
    if fresh:
        try:
            with transaction.atomic():
                Favorite.objects.bulk_create(fresh, ignore_conflicts=True)
        except IntegrityError:
            pass


@api_view(["GET"])
def favorites(request):
    uid = user_id_from_request(request)
    if not uid:
        return Response({"detail": "Нет токена"}, status=401)
    return Response({"keys": _keys(uid)})


@api_view(["PUT", "DELETE"])
def favorite_item(request, key):
    uid = user_id_from_request(request)
    if not uid:
        return Response({"detail": "Нет токена"}, status=401)
    key = _clean(key)
    if not key:
        return Response({"detail": "Пустой ключ"}, status=400)
    if request.method == "PUT":
        _add(uid, [key])
    else:
        Favorite.objects.filter(user_id=uid, model_key=key).delete()
    return Response({"keys": _keys(uid)})


@api_view(["POST"])
def favorites_merge(request):
    uid = user_id_from_request(request)
    if not uid:
        return Response({"detail": "Нет токена"}, status=401)
    keys = request.data.get("keys") if isinstance(request.data, dict) else None
    if not isinstance(keys, list):
        return Response({"detail": "Нужен список keys"}, status=400)
    _add(uid, keys[:MAX_FAVORITES])
    return Response({"keys": _keys(uid)})
