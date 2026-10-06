"""Баллы за захват — только за засчитанную пробежку (решение владельца 28.09.2026, п.4).

Как это работает
----------------
Территория на карте засчитывается сразу, как и раньше. Баллы за новую землю —
только если у бегуна есть ПРИНЯТАЯ пробежка (не помеченная, не отклонённая), к
которой относится захват. Одна пробежка — один оплаченный захват: клиент
Квартала захватывает один раз, на финише.

Как найти пробежку:
1. Новые сборки присылают `runId` в захвате — это id сводки той же пробежки.
2. Старые сборки `runId` не шлют. Тогда пробежка ищется по цифрам: клиент кладёт
   в захват дистанцию и время ТОЙ ЖЕ пробежки (`distanceMeters`,
   `elapsedSeconds` — из одного состояния с последующей сводкой), поэтому
   совпадение почти точное. Допуск — время ±max(60 с, 5 %), дистанция
   ±max(100 м, 5 %); контур не длиннее пробежки (+20 % и 100 м). Окно — пробежка
   завершилась не раньше чем за 7 суток до получения захвата (офлайн-очередь)
   и не позже чем через 12 ч (часы телефона, гонка запросов на финише).
   Время и дистанция в этой сверке проверяются и для `runId`.

Порядок прихода любой. На финише клиент отправляет захват и сводку почти
одновременно, из офлайн-очереди — когда появится связь, в любом порядке. Если
пробежки ещё нет, захват НЕ отбивается и не теряет баллы: запись ждёт здесь
(`pending`), а приём сводки (`runs.views`) доводит начисление ровно один раз —
дедуп по `capture_id` в истории баллов, проверка и запись под блокировкой
`ACTIVITY` бегуна (той же, что у суточного бюджета).

Пробежка помечена античитом — захват привязывается к ней и ждёт модератора:
одобрил — баллы приходят (`approve_run`), признал нарушением — не приходят,
а уже выплаченные за захват отзываются встречной проводкой.
"""
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from common.locks import ACTIVITY, lock_user

from .models import CaptureAward

SOURCE = "runnerTerritory"
SOURCE_REVOKED = "runnerTerritoryRevoked"

MATCH_LOOKBACK = timedelta(days=7)
MATCH_AHEAD = timedelta(hours=12)

PENDING_NO_RUN = "Баллы за захват придут, когда синхронизируется пробежка"
PENDING_REVIEW = "Пробежка на проверке — баллы за захват придут после неё"


def _metrics_match(award, run) -> bool:
    if award.elapsed_s <= 0 or run.duration_s <= 0:
        return False
    if abs(run.duration_s - award.elapsed_s) > max(60, 0.05 * run.duration_s):
        return False
    if award.distance_m > 0 and abs(run.distance_m - award.distance_m) > max(
        100, 0.05 * run.distance_m
    ):
        return False
    return award.route_m <= run.distance_m * 1.2 + 100


def _in_window(award, run) -> bool:
    at = award.created_at
    return at - MATCH_LOOKBACK <= run.finished_at <= at + MATCH_AHEAD


def _paid_runs(uid, exclude=None):
    qs = CaptureAward.objects.filter(user_id=uid, status=CaptureAward.AWARDED).exclude(
        run_id=""
    )
    if exclude:
        qs = qs.exclude(capture_id=exclude)
    return set(qs.values_list("run_id", flat=True))


def _find_run(award):
    from runs.models import Run

    taken = _paid_runs(award.user_id, exclude=award.capture_id)
    if award.run_id:
        run = Run.objects.filter(id=award.run_id, user_id=award.user_id).first()
        if run and run.id not in taken and _metrics_match(award, run):
            return run
        return None
    candidates = Run.objects.filter(
        user_id=award.user_id,
        finished_at__gte=award.created_at - MATCH_LOOKBACK,
        finished_at__lte=award.created_at + MATCH_AHEAD,
    ).exclude(id__in=taken)
    best = None
    for run in candidates:
        if not _metrics_match(award, run):
            continue
        if best is None or abs(run.finished_at - award.created_at) < abs(
            best.finished_at - award.created_at
        ):
            best = run
    return best


def _settle(award, run, *, cap=True):
    """Решить судьбу ожидающего захвата по найденной пробежке.

    Возвращает (выплачено, причина-ожидания-или-потолка). Вызывать под
    блокировкой ACTIVITY бегуна (кроме решения модератора — там сверх бюджета).
    """
    from loyalty.models import LoyaltyTransaction, add_txn
    from runs.budget import grant

    award.run_id = run.id
    if run.flagged:
        if run.reviewed_at:  # признана нарушением
            award.status = CaptureAward.REJECTED
            award.note = "Пробежка признана нарушением"
            award.settled_at = timezone.now()
            award.save()
            return 0, award.note
        award.note = PENDING_REVIEW
        award.save(update_fields=["run_id", "note"])
        return 0, PENDING_REVIEW
    if LoyaltyTransaction.objects.filter(
        user_id=award.user_id, run_id=award.capture_id, source=SOURCE
    ).exists():
        granted, reason = award.awarded, ""
    else:
        granted, _cut, reason = grant(award.user_id, award.points) if cap else (
            award.points, 0, "")
        if granted > 0:
            add_txn(award.user_id, granted, SOURCE, "Захват территории", None,
                    award.capture_id)
    award.awarded = granted
    award.status = CaptureAward.AWARDED
    award.note = reason
    award.settled_at = timezone.now()
    award.save()
    # Программа лояльности v1 (этап 2): бонус за захват — за валидную пробежку,
    # с месячными капами (loyalty.activity). Игровые баллы выше — только счёт игры.
    from loyalty import activity

    award.bonus_act = activity.on_capture(award, run)
    return granted, reason


def claim(uid, capture_id, points, run_hint, distance_m, route_m, elapsed_s):
    """Захват засчитан и стоит `points` баллов: выплатить сейчас или ждать пробежку.

    Звать внутри transaction.atomic(). Возвращает словарь для ответа:
    {"points": выплачено, "pending": ждёт баллов, "reason": пояснение,
     "capped": срезано потолком}.
    """
    lock_user(ACTIVITY, uid)
    award, _ = CaptureAward.objects.select_for_update().get_or_create(
        capture_id=capture_id,
        defaults=dict(
            user_id=uid, points=points, run_id=run_hint or "",
            distance_m=distance_m or 0.0, route_m=route_m or 0.0,
            elapsed_s=int(elapsed_s or 0),
        ),
    )
    if award.user_id != uid or award.status != CaptureAward.PENDING:
        return {"points": award.awarded if award.user_id == uid else 0,
                "pending": 0, "reason": award.note, "capped": 0}
    run = _find_run(award)
    if run is None:
        award.note = PENDING_NO_RUN
        award.save(update_fields=["note"])
        return {"points": 0, "pending": points, "reason": PENDING_NO_RUN, "capped": 0}
    granted, reason = _settle(award, run)
    if award.status == CaptureAward.PENDING:
        return {"points": 0, "pending": points, "reason": reason, "capped": 0}
    if award.status == CaptureAward.REJECTED:
        return {"points": 0, "pending": 0, "reason": reason, "capped": 0}
    out = {"points": granted, "pending": 0, "reason": reason,
           "capped": max(0, award.points - granted)}
    act = getattr(award, "bonus_act", None)
    if act is not None:
        # Программа v1: «+N» на экране — начисленный бонус, а не игровые баллы.
        from loyalty import activity

        out.update(points=act.amount, capped=0, bonus=activity.payload(act))
    return out


def settle_for_run(run):
    """Пришла сводка пробежки — довести ждущие её захваты (под блокировкой ACTIVITY).

    Сначала захват, прямо назвавший этот runId, иначе — ближайший по времени
    захват со совпавшими цифрами. Оплачивается один захват на пробежку.
    """
    if run.id in _paid_runs(run.user_id):
        return 0
    waiting = list(
        CaptureAward.objects.select_for_update().filter(
            user_id=run.user_id, status=CaptureAward.PENDING
        )
    )
    named = [a for a in waiting if a.run_id == run.id and _metrics_match(a, run)]
    if named:
        award = named[0]
    else:
        loose = [a for a in waiting if not a.run_id and _in_window(a, run)
                 and _metrics_match(a, run)]
        if not loose:
            return 0
        award = min(loose, key=lambda a: abs(run.finished_at - a.created_at))
    granted, _reason = _settle(award, run)
    return granted


def on_run_approved(run):
    """Модератор одобрил пробежку — выплатить привязанный к ней захват (без бюджета,
    как и баллы за саму пробежку при одобрении)."""
    with transaction.atomic():
        for award in CaptureAward.objects.select_for_update().filter(
            user_id=run.user_id, run_id=run.id, status=CaptureAward.PENDING
        ):
            _settle(award, run, cap=False)


def on_run_rejected(run):
    """Пробежка признана нарушением: ждущий захват баллов не получит, выплаченный —
    отзывается встречной проводкой (запись о выплате не удаляется)."""
    from django.db.models import Sum

    from loyalty.models import LoyaltyTransaction, add_txn

    with transaction.atomic():
        for award in CaptureAward.objects.select_for_update().filter(
            user_id=run.user_id, run_id=run.id
        ):
            if award.status == CaptureAward.AWARDED:
                paid = LoyaltyTransaction.objects.filter(
                    user_id=run.user_id, run_id=award.capture_id,
                    source__in=(SOURCE, SOURCE_REVOKED),
                ).aggregate(s=Sum("amount"))["s"] or 0
                if paid > 0:
                    add_txn(run.user_id, -paid, SOURCE_REVOKED,
                            "Отмена баллов за захват (пробежка не засчитана)",
                            None, award.capture_id)
            award.status = CaptureAward.REJECTED
            award.note = "Пробежка признана нарушением"
            award.settled_at = timezone.now()
            award.save()
