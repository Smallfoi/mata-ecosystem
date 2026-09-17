"""API дружбы (D-82, этап 2a). Всё под токеном.

  GET    /v1/friends                 — {friends, incoming, outgoing}
  POST   /v1/friends/request {userId}— отправить заявку (обратную — авто-подтвердить)
  GET    /v1/friends/search?q=       — поиск по имени (для «по нику/ссылке»)
  GET    /v1/friends/suggestions     — подсказки (пока: одноклубники)
  POST   /v1/friends/match-contacts  — сопоставить контакты по хешу телефона
  POST   /v1/friends/<id>/accept     — подтвердить входящую заявку
  POST   /v1/friends/<id>/reject     — отклонить входящую / отменить исходящую
  DELETE /v1/friends/<id>            — удалить из друзей

Позицию/карту тут НЕ отдаём — это этап 2b (только для accepted, огрубление до гекса).
"""
import hashlib
import re
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response

from accounts.models import Account
from clubs.models import ClubMember
from common.security import user_id_from_request

from .models import (
    FriendMapPrefs,
    FriendPosition,
    Friendship,
    coarsen,
    friends_ids,
    relationship,
)

_MAX_CONTACT_HASHES = 3000


def _me(request):
    return user_id_from_request(request)


def _summary(acc: Account, status: str) -> dict:
    return {
        "userId": acc.id,
        "name": acc.name or "Бегун",
        "avatarPath": acc.avatar_path,
        "status": status,
    }


def _acc_map(ids):
    return {a.id: a for a in Account.objects.filter(id__in=list(ids))}


def _norm_phone(phone: str) -> str:
    d = re.sub(r"\D", "", phone or "")
    if len(d) == 11 and d.startswith("8"):
        d = "7" + d[1:]
    return d


@api_view(["GET"])
def friends_list(request):
    uid = _me(request)
    if not uid:
        return Response({"detail": "Нет токена"}, status=401)
    rows = list(Friendship.objects.filter(Q(requester_id=uid) | Q(addressee_id=uid)))
    ids = {(f.addressee_id if f.requester_id == uid else f.requester_id) for f in rows}
    accs = _acc_map(ids)
    friends, incoming, outgoing = [], [], []
    for f in rows:
        other = f.addressee_id if f.requester_id == uid else f.requester_id
        acc = accs.get(other)
        if not acc:
            continue
        if f.status == Friendship.ACCEPTED:
            friends.append(_summary(acc, "friends"))
        elif f.addressee_id == uid:
            incoming.append(_summary(acc, "incoming"))
        else:
            outgoing.append(_summary(acc, "outgoing"))
    return Response({"friends": friends, "incoming": incoming, "outgoing": outgoing})


@api_view(["POST"])
def friend_request(request):
    uid = _me(request)
    if not uid:
        return Response({"detail": "Нет токена"}, status=401)
    other = str((request.data or {}).get("userId") or "").strip()
    if not other or other == uid:
        return Response({"detail": "Неверный пользователь"}, status=400)
    if not Account.objects.filter(id=other).exists():
        return Response({"detail": "Пользователь не найден"}, status=404)
    # Встречная заявка (other→uid) — подтверждаем, становимся друзьями.
    rev = Friendship.objects.filter(requester_id=other, addressee_id=uid).first()
    if rev:
        if rev.status != Friendship.ACCEPTED:
            rev.status = Friendship.ACCEPTED
            rev.updated_at = timezone.now()
            rev.save(update_fields=["status", "updated_at"])
        return Response({"status": "friends"})
    existing = Friendship.objects.filter(requester_id=uid, addressee_id=other).first()
    if existing:
        return Response(
            {"status": "friends" if existing.status == Friendship.ACCEPTED else "outgoing"}
        )
    Friendship.objects.create(requester_id=uid, addressee_id=other)
    return Response({"status": "outgoing"})


@api_view(["POST"])
def friend_accept(request, other_id):
    uid = _me(request)
    if not uid:
        return Response({"detail": "Нет токена"}, status=401)
    f = Friendship.objects.filter(
        requester_id=other_id, addressee_id=uid, status=Friendship.PENDING
    ).first()
    if not f:
        return Response({"detail": "Заявки нет"}, status=404)
    f.status = Friendship.ACCEPTED
    f.updated_at = timezone.now()
    f.save(update_fields=["status", "updated_at"])
    return Response({"status": "friends"})


@api_view(["POST"])
def friend_reject(request, other_id):
    """Отклонить входящую заявку ИЛИ отменить свою исходящую (обе — pending)."""
    uid = _me(request)
    if not uid:
        return Response({"detail": "Нет токена"}, status=401)
    Friendship.objects.filter(status=Friendship.PENDING).filter(
        Q(requester_id=other_id, addressee_id=uid)
        | Q(requester_id=uid, addressee_id=other_id)
    ).delete()
    return Response({"status": "none"})


@api_view(["DELETE"])
def friend_remove(request, other_id):
    uid = _me(request)
    if not uid:
        return Response({"detail": "Нет токена"}, status=401)
    Friendship.objects.filter(
        Q(requester_id=uid, addressee_id=other_id)
        | Q(requester_id=other_id, addressee_id=uid)
    ).delete()
    return Response({"status": "none"})


@api_view(["GET"])
def friend_search(request):
    uid = _me(request)
    if not uid:
        return Response({"detail": "Нет токена"}, status=401)
    q = (request.query_params.get("q") or "").strip()
    if len(q) < 2:
        return Response({"results": []})
    accs = Account.objects.filter(name__icontains=q).exclude(id=uid)[:20]
    return Response({"results": [_summary(a, relationship(uid, a.id)) for a in accs]})


@api_view(["GET"])
def friend_suggestions(request):
    uid = _me(request)
    if not uid:
        return Response({"detail": "Нет токена"}, status=401)
    mine = ClubMember.objects.filter(user_id=uid).first()
    ids = set()
    if mine:
        ids = {
            m.user_id
            for m in ClubMember.objects.filter(club_id=mine.club_id).exclude(user_id=uid)
        }
    ids -= friends_ids(uid)
    ids.discard(uid)
    accs = _acc_map(ids)
    out = [_summary(a, relationship(uid, a.id)) for a in accs.values()]
    return Response({"suggestions": out[:20]})


@api_view(["POST"])
def friend_match_contacts(request):
    """Сопоставить контакты по ХЕШУ телефона (сырые номера не шлём — приватность).
    Клиент нормализует номер и шлёт sha256('+7XXXXXXXXXX'); сервер так же хеширует
    телефоны аккаунтов и возвращает совпадения."""
    uid = _me(request)
    if not uid:
        return Response({"detail": "Нет токена"}, status=401)
    raw = (request.data or {}).get("hashes") or []
    hashes = {h for h in raw if isinstance(h, str)}
    if not hashes:
        return Response({"results": []})
    if len(hashes) > _MAX_CONTACT_HASHES:
        hashes = set(list(hashes)[:_MAX_CONTACT_HASHES])
    out = []
    qs = Account.objects.exclude(id=uid).exclude(phone__isnull=True).exclude(phone="")
    for a in qs.iterator():
        digits = _norm_phone(a.phone)
        if not digits:
            continue
        h = hashlib.sha256(("+" + digits).encode()).hexdigest()
        if h in hashes:
            out.append(_summary(a, relationship(uid, a.id)))
    return Response({"results": out})


_POSITION_FRESH_MIN = 20  # позиция считается «живой» столько минут


@api_view(["GET", "PUT"])
def friend_prefs(request):
    """Приватность карты друзей (D-83, 2c). По умолчанию меня не видит никто."""
    uid = _me(request)
    if not uid:
        return Response({"detail": "Нет токена"}, status=401)
    prefs, _ = FriendMapPrefs.objects.get_or_create(user_id=uid)
    if request.method == "PUT":
        d = request.data if isinstance(request.data, dict) else {}
        if "visible" in d:
            prefs.visible = bool(d["visible"])
        if "homeHidden" in d:
            prefs.home_hidden = bool(d["homeHidden"])
        if d.get("precision") in ("hex", "exact"):
            prefs.precision = d["precision"]
        if "hideHours" in d:  # 0/None — снять «Тень»; 2/8/24 — включить
            h = d["hideHours"]
            if not h:
                prefs.hide_until = None
            else:
                try:
                    prefs.hide_until = timezone.now() + timedelta(hours=float(h))
                except (TypeError, ValueError):
                    pass
        if "home" in d:  # {lat,lng} — задать дом; null — очистить
            home = d["home"]
            if home is None:
                prefs.home_lat = prefs.home_lng = None
            elif isinstance(home, dict):
                try:
                    prefs.home_lat = float(home["lat"])
                    prefs.home_lng = float(home["lng"])
                except (KeyError, TypeError, ValueError):
                    pass
        prefs.updated_at = timezone.now()
        prefs.save()
        # Выключил видимость или ушёл в «Тень» — снять живую точку немедленно.
        if not prefs.visible or prefs.in_shadow():
            FriendPosition.objects.filter(user_id=uid).delete()
    return Response(prefs.to_json())


@api_view(["POST"])
def friend_position(request):
    """Телефон шлёт позицию, ПОКА открыта карта (батарея). Огрублённую храним для
    друзей (видим/не в Тени/не у дома); ТОЧНУЮ — только для «Маяка» (доверенным),
    пока маяк активен. Ни для кого — строку удаляем."""
    uid = _me(request)
    if not uid:
        return Response({"detail": "Нет токена"}, status=401)
    d = request.data if isinstance(request.data, dict) else {}
    try:
        lat = float(d["lat"])
        lng = float(d["lng"])
    except (KeyError, TypeError, ValueError):
        return Response({"detail": "Нет координат"}, status=400)
    prefs, _ = FriendMapPrefs.objects.get_or_create(user_id=uid)
    coarse_ok = prefs.visible and not prefs.in_shadow() and not prefs.near_home(lat, lng)
    beacon_on = prefs.in_beacon()
    if not coarse_ok and not beacon_on:
        FriendPosition.objects.filter(user_id=uid).delete()
        return Response({"stored": False})
    clat, clng = coarsen(lat, lng) if coarse_ok else (None, None)
    FriendPosition.objects.update_or_create(
        user_id=uid,
        defaults={
            "lat": clat, "lng": clng,
            "exact_lat": lat if beacon_on else None,
            "exact_lng": lng if beacon_on else None,
            "beacon": beacon_on,
            "status": str(d.get("status") or "")[:20],
            "updated_at": timezone.now(),
        },
    )
    return Response({"stored": True, "beacon": beacon_on})


@api_view(["GET"])
def friend_positions(request):
    """Позиции взаимных друзей (огрублённые). Взаимность «Тени»: если Я в тени —
    не вижу никого. Отдаём только видимых, не в тени, со свежей точкой."""
    uid = _me(request)
    if not uid:
        return Response({"detail": "Нет токена"}, status=401)
    me_prefs = FriendMapPrefs.objects.filter(user_id=uid).first()
    if me_prefs and me_prefs.in_shadow():
        return Response({"positions": [], "inShadow": True})
    fids = friends_ids(uid)
    if not fids:
        return Response({"positions": []})
    fresh = timezone.now() - timedelta(minutes=_POSITION_FRESH_MIN)
    prefs_map = {
        p.user_id: p for p in FriendMapPrefs.objects.filter(user_id__in=fids)
    }
    accs = _acc_map(fids)
    out = []
    for pos in FriendPosition.objects.filter(user_id__in=fids, updated_at__gte=fresh):
        pr = prefs_map.get(pos.user_id)
        acc = accs.get(pos.user_id)
        if not pr or not acc:
            continue
        beacon_to_me = (
            pos.beacon and pr.in_beacon() and pos.exact_lat is not None
            and uid in (pr.beacon_trusted or [])
        )
        if beacon_to_me:
            lat, lng, is_beacon = pos.exact_lat, pos.exact_lng, True
        elif pos.lat is not None and pr.visible and not pr.in_shadow():
            lat, lng, is_beacon = pos.lat, pos.lng, False
        else:
            continue
        out.append({
            "userId": pos.user_id,
            "name": acc.name or "Бегун",
            "avatarPath": acc.avatar_path,
            "lat": lat,
            "lng": lng,
            "status": pos.status,
            "beacon": is_beacon,
            "updatedAt": pos.updated_at.isoformat(),
        })
    return Response({"positions": out})


@api_view(["POST"])
def friend_beacon(request):
    """«Маяк» (D-84): точный трек 1–3 ДОВЕРЕННЫМ друзьям на время (safety-фича).
    {hours, trusted:[id,...]} — включить; {off:true} — выключить и стереть точную точку.
    Доверенные обязаны быть взаимными друзьями; их не больше 3."""
    uid = _me(request)
    if not uid:
        return Response({"detail": "Нет токена"}, status=401)
    d = request.data if isinstance(request.data, dict) else {}
    prefs, _ = FriendMapPrefs.objects.get_or_create(user_id=uid)
    if d.get("off"):
        prefs.beacon_until = None
        prefs.updated_at = timezone.now()
        prefs.save()
        FriendPosition.objects.filter(user_id=uid).update(
            exact_lat=None, exact_lng=None, beacon=False)
        return Response(prefs.to_json())
    fids = friends_ids(uid)
    trusted = [str(t) for t in (d.get("trusted") or []) if str(t) in fids][:3]
    try:
        hours = float(d.get("hours") or 2)
    except (TypeError, ValueError):
        hours = 2.0
    hours = max(0.25, min(hours, 12.0))
    prefs.beacon_trusted = trusted
    prefs.beacon_until = timezone.now() + timedelta(hours=hours)
    prefs.updated_at = timezone.now()
    prefs.save()
    return Response(prefs.to_json())
