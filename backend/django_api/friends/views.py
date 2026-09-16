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

from django.db.models import Q
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response

from accounts.models import Account
from clubs.models import ClubMember
from common.security import user_id_from_request

from .models import Friendship, friends_ids, relationship

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
