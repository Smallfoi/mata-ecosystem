"""API защиты от другого человека: чёрный список и жалобы.

  GET    /v1/me/blocks            — кого я заблокировал
  POST   /v1/me/blocks {userId}   — заблокировать (рвёт дружбу и заявки)
  DELETE /v1/me/blocks/<id>       — разблокировать (дружбу НЕ возвращает)
  GET    /v1/reports/reasons      — список причин для формы жалобы
  POST   /v1/reports {...}        — пожаловаться на человека или клуб

Жалобу разбирает модератор в админке — ответ пользователю хранится в
`Report.resolution`, без него апелляция невозможна (§10 LAUNCH_READINESS).
"""
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone
from rest_framework.decorators import api_view, throttle_classes
from rest_framework.response import Response

from accounts.models import Account
from clubs.models import Club
from common.security import user_id_from_request
from common.throttling import UserJWTRateThrottle, WriteUserJWTRateThrottle

from .models import Block, Report

# Сколько жалоб в сутки принимаем от одного человека. Не про нагрузку:
# без потолка жалоба превращается в инструмент травли — завалить модерацию
# сотней жалоб на одного дешевле, чем их разобрать.
_REPORTS_PER_DAY = 20


def _me(request):
    return user_id_from_request(request)


@api_view(["GET", "POST"])
@throttle_classes([WriteUserJWTRateThrottle])
def my_blocks(request):
    uid = _me(request)
    if not uid:
        return Response({"detail": "Нет токена"}, status=401)

    if request.method == "GET":
        rows = list(Block.objects.filter(user_id=uid))
        accs = {a.id: a for a in Account.objects.filter(
            id__in=[b.blocked_id for b in rows])}
        out = []
        for b in rows:
            acc = accs.get(b.blocked_id)
            out.append({
                "userId": b.blocked_id,
                # Удалённый аккаунт из чёрного списка не выкидываем: строка
                # продолжает прятать, даже если показать некого.
                "name": (acc.name or "Бегун") if acc else "Профиль удалён",
                "avatarPath": acc.avatar_path if acc else "",
                "createdAt": b.created_at.isoformat(),
            })
        return Response(out)

    other = str(request.data.get("userId") or "").strip()
    if not other:
        return Response({"detail": "Нужен userId"}, status=400)
    if other == uid:
        return Response({"detail": "Себя заблокировать нельзя"}, status=400)
    if not Account.objects.filter(id=other).exists():
        return Response({"detail": "Пользователь не найден"}, status=404)

    Block.objects.get_or_create(user_id=uid, blocked_id=other)
    # Блокировка рвёт связь: иначе человек остаётся в списке друзей обоих и
    # продолжает получать то, что видно друзьям.
    from friends.models import Friendship

    Friendship.objects.filter(
        Q(requester_id=uid, addressee_id=other)
        | Q(requester_id=other, addressee_id=uid)
    ).delete()
    return Response({"ok": True}, status=201)


@api_view(["DELETE"])
@throttle_classes([WriteUserJWTRateThrottle])
def unblock(request, other_id: str):
    uid = _me(request)
    if not uid:
        return Response({"detail": "Нет токена"}, status=401)
    Block.objects.filter(user_id=uid, blocked_id=other_id).delete()
    return Response({"ok": True})


@api_view(["GET"])
@throttle_classes([UserJWTRateThrottle])
def report_reasons(request):
    """Причины для формы жалобы — одним списком, чтобы клиенты не расходились."""
    return Response([{"code": c, "title": t} for c, t in Report.REASONS])


@api_view(["POST"])
@throttle_classes([WriteUserJWTRateThrottle])
def create_report(request):
    uid = _me(request)
    if not uid:
        return Response({"detail": "Нет токена"}, status=401)

    target_type = str(request.data.get("targetType") or Report.TARGET_USER).strip()
    target_id = str(request.data.get("targetId") or "").strip()
    reason = str(request.data.get("reason") or "").strip()
    comment = str(request.data.get("comment") or "").strip()[:2000]

    if target_type not in dict(Report.TARGETS):
        return Response({"detail": "Неизвестный тип цели"}, status=400)
    if not target_id:
        return Response({"detail": "Нужен targetId"}, status=400)
    if reason not in dict(Report.REASONS):
        return Response({"detail": "Неизвестная причина"}, status=400)
    if target_type == Report.TARGET_USER and target_id == uid:
        return Response({"detail": "Нельзя пожаловаться на себя"}, status=400)

    exists = (
        Account.objects.filter(id=target_id).exists()
        if target_type == Report.TARGET_USER
        else Club.objects.filter(id=target_id).exists()
    )
    if not exists:
        return Response({"detail": "Цель не найдена"}, status=404)

    since = timezone.now() - timedelta(days=1)
    if Report.objects.filter(reporter_id=uid, created_at__gte=since).count() >= _REPORTS_PER_DAY:
        return Response(
            {"detail": "Слишком много жалоб за сутки — разберём уже отправленные"},
            status=429,
        )

    # Повторная жалоба на то же самое, пока первая не разобрана, — не новая
    # жалоба, а тот же сигнал: не плодим очередь модератору.
    dup = Report.objects.filter(
        reporter_id=uid, target_type=target_type, target_id=target_id, status=Report.NEW
    ).first()
    if dup:
        return Response({"ok": True, "id": str(dup.id), "duplicate": True}, status=200)

    r = Report.objects.create(
        reporter_id=uid,
        target_type=target_type,
        target_id=target_id,
        reason=reason,
        comment=comment,
    )
    return Response({"ok": True, "id": str(r.id)}, status=201)
