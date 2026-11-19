"""API защиты от другого человека: чёрный список и жалобы.

  GET    /v1/me/blocks            — кого я заблокировал
  POST   /v1/me/blocks {userId}   — заблокировать (рвёт дружбу и заявки)
  DELETE /v1/me/blocks/<id>       — разблокировать (дружбу НЕ возвращает)
  GET    /v1/reports/reasons      — список причин для формы жалобы
  POST   /v1/reports {...}        — пожаловаться на человека или клуб
  GET    /v1/me/reports           — мои жалобы и что с ними стало
  GET    /v1/me/measures          — меры, применённые ко мне
  POST   /v1/me/measures/:id/appeal {text} — возразить (один раз)

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

from .models import Block, ModerationMeasure, Report

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


# Возражение — текст человека, а не форма с галочками: мера бывает ошибкой по
# причине, которую мы не предусмотрели списком.
_APPEAL_MAX = 2000


@api_view(["GET"])
@throttle_classes([UserJWTRateThrottle])
def my_reports(request):
    """Мои жалобы и что с ними стало.

    Без этого экрана жалоба — это кнопка «отправить в никуда»: человек не знает,
    дошло ли, посмотрели ли, что решили (§10 готовности).
    """
    uid = _me(request)
    if not uid:
        return Response({"detail": "Нет токена"}, status=401)

    rows = list(Report.objects.filter(reporter_id=uid)[:100])
    user_ids = [r.target_id for r in rows if r.target_type == Report.TARGET_USER]
    club_ids = [r.target_id for r in rows if r.target_type == Report.TARGET_CLUB]
    names = {a.id: (a.name or "Бегун") for a in Account.objects.filter(id__in=user_ids)}
    names.update({c.id: c.name for c in Club.objects.filter(id__in=club_ids)})

    return Response([
        {
            "id": str(r.pk),
            "targetType": r.target_type,
            "targetName": names.get(r.target_id, "Профиль удалён"),
            "reason": r.reason,
            "reasonTitle": r.get_reason_display(),
            "comment": r.comment,
            "status": r.status,
            "statusTitle": r.get_status_display(),
            # Текст решения модератора заявителю НЕ отдаём: это слова о другом
            # человеке (их видит тот, к кому применили меру). Хватает статуса.
            "createdAt": r.created_at.isoformat(),
        }
        for r in rows
    ])


@api_view(["GET"])
@throttle_classes([UserJWTRateThrottle])
def my_measures(request):
    """Меры, применённые ко мне, — и мои возражения на них.

    Сюда попадают и меры к клубам, где человек владелец: отвечает за клуб он.
    """
    uid = _me(request)
    if not uid:
        return Response({"detail": "Нет токена"}, status=401)

    my_clubs = list(
        Club.objects.filter(owner_id=uid).values_list("id", flat=True)
    )
    rows = ModerationMeasure.objects.filter(
        Q(target_type=Report.TARGET_USER, target_id=uid)
        | Q(target_type=Report.TARGET_CLUB, target_id__in=my_clubs)
    )[:100]
    return Response([m.to_json() for m in rows])


@api_view(["POST"])
@throttle_classes([WriteUserJWTRateThrottle])
def appeal_measure(request, measure_id: str):
    uid = _me(request)
    if not uid:
        return Response({"detail": "Нет токена"}, status=401)

    text = str(request.data.get("text") or "").strip()[:_APPEAL_MAX]
    if not text:
        return Response({"detail": "Напишите, с чем вы не согласны"}, status=400)

    # Не число — та же «не найдена», без 500 и без подсказки о формате id.
    m = (ModerationMeasure.objects.filter(pk=int(measure_id)).first()
         if measure_id.isdigit() else None)
    if m is None:
        return Response({"detail": "Мера не найдена"}, status=404)

    mine = (
        m.target_id == uid
        if m.target_type == Report.TARGET_USER
        else Club.objects.filter(id=m.target_id, owner_id=uid).exists()
    )
    # Чужую меру не показываем и не даём оспорить — одинаковый ответ, чтобы
    # перебором id нельзя было узнать, что к кому применили.
    if not mine:
        return Response({"detail": "Мера не найдена"}, status=404)
    if not m.can_appeal:
        return Response({"detail": "Возражение уже подано"}, status=409)

    m.appeal_text = text
    m.appeal_at = timezone.now()
    m.appeal_status = ModerationMeasure.APPEAL_NEW
    m.save(update_fields=["appeal_text", "appeal_at", "appeal_status"])
    return Response({"ok": True, "appealStatus": m.appeal_status}, status=201)
