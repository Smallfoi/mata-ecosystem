"""Программа лояльности v1, этап 2 — бонусы за активность, приглашение и регистрацию
(ТЗ владельца 30.09.2026, §3; решения координатора).

Работает ТОЛЬКО при включённой программе (настройка LOYALTY_V1_ENABLED). Выключена —
ни одна функция здесь ничего не делает, бег и захват платятся по-старому.

Что здесь решается — только БОНУСЫ. Игра (забег засчитан, территория на карте,
километры в рейтингах) от этих решений не зависит: «при капе событие засчитывается
в игре, бонусы не начисляются».

Пробежка (BONUS_RUN, лот available сразу). Условия ТЗ §3:
1. дистанция ≥ RUN_MIN_KM — по серверному пересчёту трека, если трек есть;
   иначе по итогам клиента с пометкой `validated_by: summary`;
2. средний темп в RUN_PACE_MIN..RUN_PACE_MAX; ни один отрезок > 200 м не быстрее
   2:30/км (по треку);
3. одна тренировка двумя путями (свой забег + импорт) — один раз: пересечение по
   времени > 50 % более короткой → дубль;
4. не больше одной зачтённой пробежки в календарный день (Якутск);
5. трек совпадает > 80 % по геометрии и времени с треком другого аккаунта с того же
   устройства (`notifications.DeviceAccount`) → оба на проверку, без бонусов;
6. загружена не позже 48 ч после финиша.
Что из этого «не засчитано» (коротко, медленно, поздно, дубль, не первая за день) —
просто без бонуса. Что похоже на обман (темп быстрее 3:00/км, отрезок быстрее
2:30/км, совпадение треков с соседним аккаунтом, трек противоречит итогам) —
`suspicious`: без бонуса и в очередь ручной проверки (админка «Проверка забегов» →
вкладка «Бонусы на проверке»).

Почему итоги без трека засчитываются. Все выпущенные сборки Квартала шлют сначала
итоги (POST /v1/runs), а трек (POST /v1/runs/track) — следом и только если включены
тропы или резервная копия. Отказывать в бонусе без трека — значит отказывать всем
с выключенными тропами и всем старым сборкам. Поэтому: решение по итогам сразу
(темп и дистанция из итогов), а когда трек приходит — пересчёт по треку
(`on_track`). Если трек противоречит итогам (короче порога), отрезок слишком
быстрый или трек совпадает с соседним аккаунтом — бонус отзывается и пробежка
уходит на проверку.

Месячные капы — календарный месяц по Якутску (UTC+9): CAP_RUNS_MONTH /
CAP_CAPTURES_MONTH / CAP_STAGES_MONTH и общий CAP_ACTIVITY_MONTH[уровень]. Упёрлись
в общий кап посреди бонуса — начисляется остаток (кап — потолок суммы). Суточный
потолок 1000 и созревание 3 дня (D-107) при включённой программе не действуют;
заморозка бонусов за активность при needs_review — действует (`v1.ACTIVITY_LOTS`).

Захват (BONUS_CAPTURE) — только за валидную пробежку: привязка CaptureAward → Run
(territories/awards.py), а пробежка должна пройти условия (не «коротко/медленно/
поздно», не на проверке). Пробежка на проверке — захват ждёт решения.

Этап (BONUS_STAGE) — 1-е место в месячном итоге своего дивизиона. Дивизионы в лиге
недельные (league/divisions.py), месячного итога нет — его подводит
`close_stage_month`: зачёт = уровень дивизиона (tier) участника в этом месяце
(последнее членство), счёт = км засчитанных забегов за месяц по Якутску. Первое
место каждого уровня (км > 0) получает бонус. Закрытие — ежедневной задачей
`loyalty.daily` (первый запуск нового месяца), один раз (`LoyaltyStageClose`).

Приглашение (BONUS_REFERRAL пригласившему) и регистрация (BONUS_SIGNUP) — внизу.
"""
import bisect
import hashlib
import hmac
import logging
import re
import secrets
from datetime import datetime, timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Count, Sum
from django.utils import timezone

from . import config, v1
from .models_v1 import (
    LoyaltyActivity as Act,
    LoyaltyLot,
    LoyaltyPhoneGrant,
    LoyaltyReferral,
    LoyaltyReferralCode,
    LoyaltyStageClose,
    LoyaltyStatus,
)
from .wallet import lock_wallet

log = logging.getLogger(__name__)

UPLOAD_WINDOW = timedelta(hours=48)     # ТЗ §3 п.6
SEGMENT_M = 200                         # ТЗ §3 п.2: отрезок > 200 м …
SEGMENT_PACE_MIN = 150                  # … не быстрее 2:30 мин/км
DUP_OVERLAP = 0.5                       # п.3: пересечение по времени > 50 %
TWIN_SIMILARITY = 0.8                   # п.5: совпадение треков > 80 %
TWIN_RADIUS_M = 50                      # точки «совпали»: ближе 50 м …
TWIN_TIME_MS = 60_000                   # … и не дальше минуты по времени
TWIN_SAMPLE = 300
REFERRAL_BIND_DAYS = 7                  # код можно ввести в первые 7 дней

CAP_MESSAGE = "Лимит месяца исчерпан, обновится 1 числа"
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

# Пробежка «валидна» (за неё платится захват): прошла условия, даже если бонус за
# неё самих не дали (лимит месяца, не первая за день, дубль другого пути).
VALID_RUN = frozenset({Act.GRANTED, Act.CAPPED, Act.DAY_LIMIT, Act.DUPLICATE})
# «Зачтённая» пробежка дня (п.4).
COUNTED_RUN = frozenset({Act.GRANTED, Act.CAPPED})

_KIND = {
    Act.RUN: ("BONUS_RUN", "CAP_RUNS_MONTH", "accrue_run", "пробежку"),
    Act.CAPTURE: ("BONUS_CAPTURE", "CAP_CAPTURES_MONTH", "accrue_capture", "захват квартала"),
    Act.STAGE: ("BONUS_STAGE", "CAP_STAGES_MONTH", "accrue_stage", "победу в этапе"),
}


# ── месяц по Якутску ─────────────────────────────────────────────────────────

def month_of(dt) -> str:
    local = timezone.localtime(dt)
    return f"{local.year:04d}-{local.month:02d}"


def month_bounds(month: str):
    """Начало и конец календарного месяца по местному времени (Якутск)."""
    year, mon = (int(x) for x in month.split("-"))
    tz = timezone.get_current_timezone()
    start = datetime(year, mon, 1, tzinfo=tz)
    end = datetime(year + (mon == 12), mon % 12 + 1, 1, tzinfo=tz)
    return start, end


def usage(uid, month, exclude=None) -> dict:
    """Начислено в месяце: число бонусов по видам и общая сумма."""
    qs = Act.objects.filter(user_id=uid, month=month, status=Act.GRANTED)
    if exclude:
        qs = qs.exclude(pk=exclude)
    out = {Act.RUN: 0, Act.CAPTURE: 0, Act.STAGE: 0, "total": 0}
    for row in qs.values("kind").annotate(n=Count("id"), s=Sum("amount")):
        out[row["kind"]] = row["n"]
        out["total"] += row["s"] or 0
    return out


def _level(uid) -> int:
    st = LoyaltyStatus.objects.filter(user_id=uid).only("level").first()
    return st.level if st else 0


def limits(uid, month, level=None) -> dict:
    """Остаток лимитов месяца — для экрана после пробежки."""
    level = _level(uid) if level is None else level
    used = usage(uid, month)
    total = config.by_level("CAP_ACTIVITY_MONTH", level)
    start, end = month_bounds(month)
    return {
        "month": month,
        "runsLeft": max(0, config.get("CAP_RUNS_MONTH") - used[Act.RUN]),
        "capturesLeft": max(0, config.get("CAP_CAPTURES_MONTH") - used[Act.CAPTURE]),
        "stagesLeft": max(0, config.get("CAP_STAGES_MONTH") - used[Act.STAGE]),
        "activityLeft": max(0, total - used["total"]),
        "activityCap": total,
        "resetsAt": end.isoformat(),
    }


def payload(act) -> dict:
    """Поля ответа о бонусе (новые; старые клиенты их не читают)."""
    bonus_key = _KIND[act.kind][0]
    cap_reached = act.status == Act.CAPPED or (
        act.status == Act.GRANTED and act.amount < int(config.get(bonus_key)))
    msg = {
        Act.GRANTED: f"+{act.amount} бонусов",
        Act.CAPPED: CAP_MESSAGE,
        Act.DAY_LIMIT: "Бонус за пробежку — один раз в день",
        Act.DUPLICATE: "Эта тренировка уже учтена",
        Act.SUSPICIOUS: "Пробежка на проверке — бонус придёт после неё",
        Act.FLAGGED: "Пробежка на проверке — бонус придёт после неё",
        Act.WAITING: "Бонус за захват придёт после проверки пробежки",
        Act.REJECTED: "Бонус не начислен: проверка не подтвердила данные",
    }.get(act.status, act.reason)
    if act.status == Act.GRANTED and cap_reached:
        msg = f"+{act.amount} бонусов. {CAP_MESSAGE}"
    return {
        "amount": act.amount,
        "status": act.status,
        "reason": act.reason,
        "validatedBy": act.validated_by or None,
        "monthCapReached": cap_reached,
        "message": msg,
        **limits(act.user_id, act.month),
    }


def client_block(awarded, uid, month, capped, text) -> dict:
    """Объект `loyalty` для клиентов (контракт этапа 3, mata_kvartal run_bonus.dart):
    {awarded, monthLeft — сколько бонусов за активность ещё можно получить в этом
    месяце, capped — лимит исчерпан, text — текст для человека}."""
    return {"awarded": int(awarded), "monthLeft": limits(uid, month)["activityLeft"],
            "capped": bool(capped), "text": text}


def loyalty_block(act) -> dict:
    p = payload(act)
    return client_block(act.amount, act.user_id, act.month, p["monthCapReached"],
                        p["message"])


# ── трек ─────────────────────────────────────────────────────────────────────

def _haversine(a, b) -> float:
    from trails.matching import haversine_m

    return haversine_m(a[0], a[1], b[0], b[1])


def _track(run_id, uid):
    from trails.models import PendingTrack

    t = PendingTrack.objects.filter(run_id=run_id, user_id=uid).only("points").first()
    pts = [p for p in (t.points if t else []) if isinstance(p, (list, tuple)) and len(p) >= 3]
    return pts if len(pts) >= 2 else None


def track_metrics(points) -> dict:
    """Дистанция, время и самый быстрый отрезок ≥ 200 м по точкам [lat, lon, ts_ms]."""
    cum = [0.0]
    for a, b in zip(points, points[1:]):
        cum.append(cum[-1] + _haversine(a, b))
    times = [p[2] for p in points]
    span = (times[-1] - times[0]) / 1000.0
    fastest = None
    j = 0
    n = len(points)
    for i in range(n):
        j = max(j, i)
        while j < n and cum[j] - cum[i] < SEGMENT_M:
            j += 1
        if j >= n:
            break
        seg_km = (cum[j] - cum[i]) / 1000.0
        dt = (times[j] - times[i]) / 1000.0
        pace = max(0.0, dt) / seg_km
        if fastest is None or pace < fastest:
            fastest = pace
    return {"distance_m": cum[-1], "duration_s": span if span > 0 else None,
            "fastest_segment_pace": fastest}


def _similarity(a, b) -> float:
    """Доля точек трека `a`, рядом с которыми (≤ 50 м и ≤ 1 мин) есть точка `b`."""
    if len(a) < 2 or len(b) < 2:
        return 0.0
    step = max(1, len(a) // TWIN_SAMPLE)
    sample = a[::step]
    bs = sorted(b, key=lambda p: p[2])
    bt = [p[2] for p in bs]
    hit = 0
    for p in sample:
        lo = bisect.bisect_left(bt, p[2] - TWIN_TIME_MS)
        hi = bisect.bisect_right(bt, p[2] + TWIN_TIME_MS)
        if any(_haversine(p, q) <= TWIN_RADIUS_M for q in bs[lo:hi]):
            hit += 1
    return hit / len(sample)


def _device_twins(uid) -> set:
    from notifications.models import DeviceAccount

    tokens = list(DeviceAccount.objects.filter(user_id=uid).values_list("token", flat=True))
    if not tokens:
        return set()
    return set(DeviceAccount.objects.filter(token__in=tokens).exclude(user_id=uid)
               .values_list("user_id", flat=True))


def _twin_tracks(uid, track):
    """Треки других аккаунтов с того же устройства, совпавшие с этим > 80 %."""
    from trails.models import PendingTrack

    twins = _device_twins(uid)
    if not twins:
        return []
    t0, t1 = track[0][2], track[-1][2]
    hits = []
    for other in PendingTrack.objects.filter(user_id__in=twins).only("run_id", "user_id",
                                                                   "points"):
        pts = [p for p in (other.points or []) if isinstance(p, (list, tuple)) and len(p) >= 3]
        if len(pts) < 2 or pts[-1][2] < t0 - TWIN_TIME_MS or pts[0][2] > t1 + TWIN_TIME_MS:
            continue
        if _similarity(track, pts) > TWIN_SIMILARITY:
            hits.append((other.user_id, other.run_id))
    return hits


# ── решение по бонусу ────────────────────────────────────────────────────────

def _set(act, status, reason="", amount=0, lot=None):
    act.status, act.reason, act.amount = status, reason[:200], amount
    act.lot_id = lot.pk if lot is not None else (act.lot_id if amount else None)
    act.save()
    return act


def _grant(act, now):
    """Бонус в пределах месячных капов. Вызывать под замком кошелька."""
    uid = act.user_id
    bonus_key, cap_key, event_type, what = _KIND[act.kind]
    st = v1._ensure_status(uid, now)
    used = usage(uid, act.month, exclude=act.pk)
    cap = int(config.get(cap_key))
    bonus = int(config.get(bonus_key))
    if used[act.kind] >= cap:
        return _set(act, Act.CAPPED, CAP_MESSAGE)
    left = config.by_level("CAP_ACTIVITY_MONTH", st.level) - used["total"]
    amount = min(bonus, left)
    if amount <= 0:
        return _set(act, Act.CAPPED, CAP_MESSAGE)
    lot = v1.accrue(uid, amount, act.kind, act.ref, event_type=event_type, status=True,
                    now=now, meta={"activity": act.pk, "month": act.month},
                    note=f"Бонус за {what}")
    if amount < bonus:
        act.meta = {**act.meta, "partial": True, "bonus": bonus}
    _set(act, Act.GRANTED, "", amount, lot)
    v1._notify(uid, f"+{amount} бонусов", f"Бонус за {what}.")
    return act


def _revoke(act, now, note):
    """Отозвать начисленный бонус (ушёл на проверку / отклонён)."""
    if act.status == Act.GRANTED and act.amount and act.lot_id:
        v1.revoke_accrual(act.user_id, act.lot_id, act.amount, now=now, note=note,
                          source_ref=act.ref)
    act.amount, act.lot_id = 0, None


def _duplicate_of(act):
    """Та же тренировка, уже учтённая другим путём (пересечение > 50 % короткой)."""
    if not (act.started_at and act.finished_at):
        return None
    mine = (act.finished_at - act.started_at).total_seconds()
    qs = Act.objects.filter(
        user_id=act.user_id, kind=Act.RUN, started_at__lt=act.finished_at,
        finished_at__gt=act.started_at,
    ).exclude(pk=act.pk).exclude(status__in=(Act.DUPLICATE, Act.REJECTED))
    for other in qs:
        theirs = (other.finished_at - other.started_at).total_seconds()
        overlap = (min(act.finished_at, other.finished_at)
                   - max(act.started_at, other.started_at)).total_seconds()
        shorter = min(mine, theirs)
        if shorter <= 0 or overlap / shorter > DUP_OVERLAP:
            return other
    return None


def _day_taken(act) -> bool:
    return Act.objects.filter(user_id=act.user_id, kind=Act.RUN, day=act.day,
                              status__in=COUNTED_RUN).exclude(pk=act.pk).exists()


def _make_suspicious(act, reason, now):
    """На проверку: бонус отзывается, бонусы захватов этой пробежки — ждут решения."""
    if act.status in (Act.SUSPICIOUS, Act.REJECTED):
        return act
    _revoke(act, now, "Пробежка ушла на проверку")
    _set(act, Act.SUSPICIOUS, reason)
    if act.kind == Act.RUN:
        for cap in Act.objects.filter(user_id=act.user_id, kind=Act.CAPTURE, run_ref=act.ref,
                                      status=Act.GRANTED):
            _revoke(cap, now, "Пробежка захвата ушла на проверку")
            _set(cap, Act.WAITING, "Пробежка на проверке")
    return act


def _suspicion(act, track, metrics) -> str:
    """Признаки обмана (п.2 темп и отрезки, п.5 соседний аккаунт). Пусто — чисто."""
    km = act.distance_m / 1000.0
    if km > 0 and act.duration_s / km < config.get("RUN_PACE_MIN"):
        return "Темп быстрее 3:00 мин/км"
    if metrics and metrics["fastest_segment_pace"] is not None and \
            metrics["fastest_segment_pace"] < SEGMENT_PACE_MIN:
        return "Отрезок больше 200 м быстрее 2:30 мин/км"
    return ""


def _flag_twins(act, track, now) -> bool:
    hits = _twin_tracks(act.user_id, track)
    if not hits:
        return False
    reason = "Трек совпадает с треком другого аккаунта с того же устройства"
    act.meta = {**act.meta, "twins": [{"user": u, "run": r} for u, r in hits]}
    _make_suspicious(act, reason, now)
    for ouid, orun in hits:
        with transaction.atomic():
            lock_wallet(ouid)
            other = Act.objects.select_for_update().filter(user_id=ouid, kind=Act.RUN,
                                                           ref=orun).first()
            if other is not None:
                other.meta = {**other.meta, "twins": [{"user": act.user_id, "run": act.ref}]}
                if other.status in (Act.GRANTED, Act.CAPPED, Act.DAY_LIMIT):
                    _make_suspicious(other, reason, now)
                else:
                    other.save(update_fields=["meta"])
    return True


def _evaluate_run(act, *, track=None, flagged="", upload_at=None, now=None):
    """Проверить пробежку по ТЗ §3 и решить бонус. Под замком кошелька бегуна."""
    now = now or timezone.now()
    if flagged:
        return _set(act, Act.FLAGGED, flagged[:200])
    upload_at = upload_at or now
    if act.finished_at and upload_at - act.finished_at > UPLOAD_WINDOW:
        return _set(act, Act.INELIGIBLE, "Загружена позже 48 часов после финиша")
    dup = _duplicate_of(act)
    if dup is not None:
        act.meta = {**act.meta, "duplicateOf": dup.ref}
        return _set(act, Act.DUPLICATE, "Та же тренировка из другого источника")
    metrics = None
    if track:
        metrics = track_metrics(track)
        act.validated_by = "track"
        act.meta = {**act.meta, "summaryM": act.distance_m, "summaryS": act.duration_s}
        act.distance_m = metrics["distance_m"]
        if metrics["duration_s"]:
            act.duration_s = int(metrics["duration_s"])
    else:
        act.validated_by = "summary"
    km = act.distance_m / 1000.0
    if km < float(config.get("RUN_MIN_KM")):
        return _set(act, Act.INELIGIBLE, f"Короче {config.get('RUN_MIN_KM'):g} км")
    if act.duration_s <= 0 or act.duration_s / km > config.get("RUN_PACE_MAX"):
        return _set(act, Act.INELIGIBLE, "Темп медленнее 12:00 мин/км")
    why = _suspicion(act, track, metrics)
    if why:
        return _make_suspicious(act, why, now)
    if track and _flag_twins(act, track, now):
        return act
    if _day_taken(act):
        return _set(act, Act.DAY_LIMIT, "В этот день уже есть пробежка с бонусом")
    return _grant(act, now)


def _new_run_act(uid, ref, *, source, started, finished, distance_m, duration_s, upload_at):
    return Act.objects.create(
        user_id=uid, kind=Act.RUN, ref=ref, source=source, status=Act.WAITING,
        month=month_of(finished), day=timezone.localtime(finished).date(),
        started_at=started, finished_at=finished, distance_m=float(distance_m or 0),
        duration_s=int(duration_s or 0), meta={"uploadAt": upload_at.isoformat()},
    )


def on_run(run, now=None):
    """Свой забег (POST /v1/runs): решение по бонусу. None — программа выключена."""
    if not config.enabled():
        return None
    now = now or timezone.now()
    uid = run.user_id
    with transaction.atomic():
        lock_wallet(uid)
        act = Act.objects.filter(user_id=uid, kind=Act.RUN, ref=run.id).first()
        if act is not None:
            return act
        act = _new_run_act(
            uid, run.id, source="app",
            started=run.finished_at - timedelta(seconds=max(0, run.duration_s)),
            finished=run.finished_at, distance_m=run.distance_m, duration_s=run.duration_s,
            upload_at=run.created_at)
        if run.flagged and run.reviewed_at:
            return _set(act, Act.REJECTED, "Забег признан нарушением")
        _evaluate_run(act, track=_track(run.id, uid),
                      flagged=run.flag_reason or "Забег помечен" if run.flagged else "",
                      upload_at=run.created_at, now=now)
    return act


def on_workout(workout, same_run=None, now=None):
    """Импорт тренировки (Health Connect, файл, часы): решение по бонусу."""
    from workouts.views import RUNNING_SPORTS

    if not config.enabled() or workout.sport not in RUNNING_SPORTS:
        return None
    now = now or timezone.now()
    uid = workout.user_id
    with transaction.atomic():
        lock_wallet(uid)
        ref = f"w:{workout.id}"
        act = Act.objects.filter(user_id=uid, kind=Act.RUN, ref=ref).first()
        if act is not None:
            return act  # тренировку уже учитывали (в т.ч. до отключения источника)
        act = _new_run_act(
            uid, ref, source=workout.source[:20], started=workout.started_at,
            finished=workout.started_at + timedelta(seconds=max(0, workout.duration_s)),
            distance_m=workout.distance_m, duration_s=workout.duration_s,
            upload_at=workout.imported_at)
        if same_run is not None:
            act.meta = {**act.meta, "duplicateOf": same_run.id}
            return _set(act, Act.DUPLICATE, "Та же тренировка, что и забег в приложении")
        if workout.flagged:
            act.validated_by = "summary"
            return _set(act, Act.INELIGIBLE, workout.flag_reason or "Тренировка помечена")
        _evaluate_run(act, upload_at=workout.imported_at, now=now)
    return act


def on_track(run_id, uid, now=None):
    """Трек пришёл после итогов: пересчитать по треку. Расхождение, быстрый отрезок,
    совпадение с соседним аккаунтом — бонус отзывается, пробежка на проверку."""
    if not config.enabled():
        return None
    now = now or timezone.now()
    with transaction.atomic():
        lock_wallet(uid)
        act = Act.objects.select_for_update().filter(user_id=uid, kind=Act.RUN,
                                                     ref=run_id).first()
        if act is None or act.validated_by == "track" or act.status not in (
                Act.GRANTED, Act.CAPPED, Act.DAY_LIMIT):
            return act
        track = _track(run_id, uid)
        if not track:
            return act
        metrics = track_metrics(track)
        act.validated_by = "track"
        act.meta = {**act.meta, "summaryM": act.distance_m, "summaryS": act.duration_s,
                    "trackM": round(metrics["distance_m"])}
        act.distance_m = metrics["distance_m"]
        if metrics["duration_s"]:
            act.duration_s = int(metrics["duration_s"])
        if act.distance_m / 1000.0 < float(config.get("RUN_MIN_KM")):
            return _make_suspicious(act, "По треку пробежка короче, чем в итогах", now)
        why = _suspicion(act, track, metrics)
        if why:
            return _make_suspicious(act, why, now)
        if _flag_twins(act, track, now):
            return act
        act.save()
    return act


# ── захват ───────────────────────────────────────────────────────────────────

def _decide_capture(act, run_act, now):
    if run_act is None:
        return _set(act, Act.INELIGIBLE, "Нет пробежки")
    if run_act.status in VALID_RUN:
        return _grant(act, now)
    if run_act.status in (Act.SUSPICIOUS, Act.FLAGGED, Act.WAITING):
        return _set(act, Act.WAITING, "Пробежка на проверке")
    if run_act.status == Act.REJECTED:
        return _set(act, Act.REJECTED, "Пробежка признана нарушением")
    return _set(act, Act.INELIGIBLE, "Пробежка не прошла условия бонуса: " + run_act.reason)


def on_capture(award, run, now=None):
    """Захват засчитан по пробежке (CaptureAward → AWARDED): бонус, если пробежка
    валидна. None — программа выключена."""
    if not config.enabled():
        return None
    now = now or timezone.now()
    uid = award.user_id
    run_act = Act.objects.filter(user_id=uid, kind=Act.RUN, ref=run.id).first()
    if run_act is None:
        run_act = on_run(run, now=now)
    with transaction.atomic():
        lock_wallet(uid)
        act, created = Act.objects.get_or_create(
            user_id=uid, kind=Act.CAPTURE, ref=award.capture_id,
            defaults=dict(run_ref=run.id, source="app", status=Act.WAITING,
                          month=month_of(award.created_at),
                          day=timezone.localtime(award.created_at).date()))
        if not created and act.status != Act.WAITING:
            return act
        run_act.refresh_from_db()
        return _decide_capture(act, run_act, now)


def _settle_captures(uid, run_ref, now):
    run_act = Act.objects.filter(user_id=uid, kind=Act.RUN, ref=run_ref).first()
    for act in Act.objects.filter(user_id=uid, kind=Act.CAPTURE, run_ref=run_ref,
                                  status=Act.WAITING):
        _decide_capture(act, run_act, now)


def _reject_captures(uid, run_ref, now):
    for act in Act.objects.filter(user_id=uid, kind=Act.CAPTURE, run_ref=run_ref).exclude(
            status=Act.REJECTED):
        _revoke(act, now, "Пробежка захвата признана нарушением")
        _set(act, Act.REJECTED, "Пробежка признана нарушением")


# ── решения модератора ───────────────────────────────────────────────────────

def approve(act, by="", now=None):
    """Очередь «Бонусы на проверке»: подтвердить — бонус, если в пределах капов
    (и это первая зачтённая пробежка дня)."""
    now = now or timezone.now()
    with transaction.atomic():
        lock_wallet(act.user_id)
        act = Act.objects.select_for_update().get(pk=act.pk)
        if act.status != Act.SUSPICIOUS:
            return act
        act.reviewed_at, act.reviewed_by = now, (by or "")[:150]
        if act.kind == Act.RUN and _day_taken(act):
            _set(act, Act.DAY_LIMIT, "В этот день уже есть пробежка с бонусом")
        else:
            _grant(act, now)
        if act.kind == Act.RUN:
            _settle_captures(act.user_id, act.ref, now)
    return act


def reject(act, by="", now=None):
    now = now or timezone.now()
    with transaction.atomic():
        lock_wallet(act.user_id)
        act = Act.objects.select_for_update().get(pk=act.pk)
        if act.status not in (Act.SUSPICIOUS, Act.FLAGGED, Act.WAITING):
            return act
        act.reviewed_at, act.reviewed_by = now, (by or "")[:150]
        _revoke(act, now, "Отклонено модератором")
        _set(act, Act.REJECTED, "Отклонено модератором")
        if act.kind == Act.RUN:
            _reject_captures(act.user_id, act.ref, now)
    return act


def on_run_approved(run, now=None):
    """Модератор одобрил забег, помеченный античитом игры: проверить по ТЗ и решить."""
    if not config.enabled():
        return None
    now = now or timezone.now()
    with transaction.atomic():
        lock_wallet(run.user_id)
        act = Act.objects.select_for_update().filter(user_id=run.user_id, kind=Act.RUN,
                                                     ref=run.id).first()
        if act is None:
            return on_run(run, now=now)
        if act.status != Act.FLAGGED:
            return act
        _evaluate_run(act, track=_track(run.id, run.user_id), upload_at=run.created_at,
                      now=now)
        _settle_captures(run.user_id, run.id, now)
    return act


def on_run_rejected(run, now=None):
    if not config.enabled():
        return None
    now = now or timezone.now()
    with transaction.atomic():
        lock_wallet(run.user_id)
        act = Act.objects.select_for_update().filter(user_id=run.user_id, kind=Act.RUN,
                                                     ref=run.id).first()
        if act is not None and act.status != Act.REJECTED:
            _revoke(act, now, "Забег признан нарушением")
            _set(act, Act.REJECTED, "Забег признан нарушением")
        _reject_captures(run.user_id, run.id, now)
    return act


def suspicious_queue():
    return Act.objects.filter(status=Act.SUSPICIOUS).order_by("-created_at")


# ── месячный этап ────────────────────────────────────────────────────────────

def _prev_month(now) -> str:
    local = timezone.localtime(now)
    first = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return month_of(first - timedelta(days=1))


def stage_standings(month):
    """Месячный итог дивизионов: {уровень: [(uid, км), …]} по убыванию км."""
    from league.models import Division, DivisionMember
    from runs.models import Run

    start, end = month_bounds(month)
    members = list(DivisionMember.objects.filter(
        week_start__gte=start.date(), week_start__lt=end.date()).order_by("week_start"))
    tiers = dict(Division.objects.filter(
        id__in={m.division_id for m in members}).values_list("id", "tier"))
    tier_of = {}
    for m in members:  # последнее членство месяца определяет зачёт
        if m.division_id in tiers:
            tier_of[m.user_id] = tiers[m.division_id]
    if not tier_of:
        return {}
    km = dict(Run.objects.filter(
        flagged=False, finished_at__gte=start, finished_at__lt=end,
        user_id__in=list(tier_of)).values("user_id").annotate(m=Sum("distance_m"))
        .values_list("user_id", "m"))
    out = {}
    for uid, tier in tier_of.items():
        meters = km.get(uid) or 0
        if meters > 0:
            out.setdefault(tier, []).append((uid, round(meters / 1000.0, 2)))
    for tier in out:
        out[tier].sort(key=lambda x: (-x[1], x[0]))
    return out


def close_stage_month(month=None, now=None) -> dict:
    """Закрыть месячный этап: 1-е место каждого уровня — BONUS_STAGE (с капами).
    Один раз на месяц; по умолчанию — прошлый месяц."""
    if not config.enabled():
        return {"enabled": False}
    now = now or timezone.now()
    month = month or _prev_month(now)
    if LoyaltyStageClose.objects.filter(month=month).exists():
        return {"month": month, "skipped": "closed"}
    _start, end = month_bounds(month)
    if end > now:
        return {"month": month, "skipped": "not_finished"}
    standings = stage_standings(month)
    winners = []
    with transaction.atomic():
        _close, created = LoyaltyStageClose.objects.get_or_create(month=month)
        if not created:
            return {"month": month, "skipped": "closed"}
        for tier, rows in sorted(standings.items()):
            uid, km = rows[0]
            lock_wallet(uid)
            act, made = Act.objects.get_or_create(
                user_id=uid, kind=Act.STAGE, ref=f"stage:{month}:t{tier}",
                defaults=dict(source="league", status=Act.WAITING, month=month,
                              meta={"tier": tier, "km": km}))
            if made:
                _grant(act, now)
            # Без id человека: удаление аккаунта (D-104) стирает строку решения,
            # а отметка закрытия месяца остаётся обезличенной.
            winners.append({"tier": tier, "km": km, "status": act.status,
                            "amount": act.amount})
        _close.winners = winners
        _close.save(update_fields=["winners"])
    return {"month": month, "winners": len(winners)}


# ── регистрация ──────────────────────────────────────────────────────────────

def phone_key(phone) -> str:
    """HMAC нормализованного телефона (та же нормализация, что у поиска по контактам)."""
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    if not digits:
        return ""
    return hmac.new(settings.SECRET_KEY.encode(), ("+" + digits).encode(),
                    hashlib.sha256).hexdigest()


def grant_signup(uid, phone, now=None) -> int:
    """Бонус за регистрацию — один раз на телефон (переживает удаление аккаунта).
    Зовётся ТОЛЬКО при создании аккаунта с подтверждённым телефоном: перенос
    существующих (тестеров) бонуса не даёт. В статусные не входит."""
    if not config.enabled():
        return 0
    key = phone_key(phone)
    amount = int(config.get("BONUS_SIGNUP"))
    if not key or amount <= 0:
        return 0
    try:
        with transaction.atomic():
            _grant_row, created = LoyaltyPhoneGrant.objects.get_or_create(
                key=key, kind=LoyaltyPhoneGrant.SIGNUP)
            if not created:
                return 0
            v1.accrue(uid, amount, v1.SIGNUP, "signup", event_type="accrue_signup",
                      status=False, now=now, note="Бонус за регистрацию")
    except IntegrityError:
        return 0
    v1._notify(uid, f"+{amount} бонусов", "Бонус за регистрацию в МАТА.")
    return amount


# ── приглашение ──────────────────────────────────────────────────────────────

def referral_code(uid) -> str:
    """Постоянный код приглашения (выдаётся при первом обращении, не меняется)."""
    row = LoyaltyReferralCode.objects.filter(user_id=uid).first()
    if row is not None:
        return row.code
    for _ in range(20):
        code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(6))
        try:
            with transaction.atomic():
                return LoyaltyReferralCode.objects.create(user_id=uid, code=code).code
        except IntegrityError:
            row = LoyaltyReferralCode.objects.filter(user_id=uid).first()
            if row is not None:
                return row.code
    return ""


def _same_person(a, b) -> str:
    """Причина считать два аккаунта одним человеком (тот же телефон / устройство)."""
    from accounts.models import Account

    phones = dict(Account.objects.filter(id__in=[a, b]).values_list("id", "phone_hash"))
    if phones.get(a) and phones.get(a) == phones.get(b):
        return "Нельзя пригласить самого себя: тот же телефон"
    if b in _device_twins(a):
        return "Нельзя пригласить самого себя: то же устройство"
    return ""


def bind_referral(uid, code, now=None):
    """Привязать приглашение (ввод кода). Возвращает (ok, текст)."""
    from accounts.models import Account

    if not config.enabled():
        return False, "Приглашения пока не работают"
    now = now or timezone.now()
    code = re.sub(r"[^A-Za-z0-9]", "", str(code or "")).upper()[:12]
    if not code:
        return False, "Введите код приглашения"
    row = LoyaltyReferralCode.objects.filter(code=code).first()
    if row is None:
        return False, "Код приглашения не найден"
    inviter = row.user_id
    if inviter == uid:
        return False, "Нельзя пригласить самого себя"
    acc = Account.objects.filter(id=uid).only("id", "created_at").first()
    if acc is None:
        return False, "Аккаунт не найден"
    if acc.created_at and now - acc.created_at > timedelta(days=REFERRAL_BIND_DAYS):
        return False, f"Код можно ввести в первые {REFERRAL_BIND_DAYS} дней после регистрации"
    if not Account.objects.filter(id=inviter).exists():
        return False, "Код приглашения не найден"
    why = _same_person(uid, inviter)
    if why:
        return False, why
    try:
        with transaction.atomic():
            _ref, created = LoyaltyReferral.objects.get_or_create(
                user_id=uid, defaults=dict(inviter_id=inviter, code=code, created_at=now))
    except IntegrityError:
        created = False
    if not created:
        return False, "Код приглашения уже введён"
    return True, "Приглашение принято"


def referral_info(uid) -> dict:
    from accounts.models import Account

    acc = Account.objects.filter(id=uid).only("id", "created_at").first()
    ref = LoyaltyReferral.objects.filter(user_id=uid).first()
    until = acc.created_at + timedelta(days=REFERRAL_BIND_DAYS) if acc else None
    mine = LoyaltyReferral.objects.filter(inviter_id=uid)
    return {
        "programV1": config.enabled(),
        "code": referral_code(uid),
        "bonus": int(config.get("BONUS_REFERRAL")),
        "capMonth": int(config.get("CAP_REFERRALS_MONTH")),
        "invitedBy": ref is not None,
        "canBind": bool(config.enabled() and ref is None and until
                        and timezone.now() <= until),
        "bindUntil": until.isoformat() if until else None,
        "invited": mine.count(),
        "rewarded": mine.filter(status=LoyaltyReferral.REWARDED).count(),
    }


def on_purchase_released(lot, now=None):
    """Покупочный лот приглашённого вышел из удержания без возврата — бонус
    пригласившему (первый такой заказ; CAP_REFERRALS_MONTH)."""
    from accounts.models import Account

    if not config.enabled() or lot.source != v1.PURCHASE:
        return None
    now = now or timezone.now()
    ref = LoyaltyReferral.objects.filter(user_id=lot.user_id,
                                         status=LoyaltyReferral.BOUND).first()
    if ref is None or int((lot.meta or {}).get("revoked", 0)):
        return None  # без возврата: заказ с возвратом не считается — ждём следующий
    inviter = ref.inviter_id
    with transaction.atomic():
        lock_wallet(inviter)
        ref = LoyaltyReferral.objects.select_for_update().get(pk=ref.pk)
        if ref.status != LoyaltyReferral.BOUND:
            return ref
        ref.rewarded_at = now

        def close(status, note):
            ref.status, ref.note = status, note[:200]
            ref.save(update_fields=["status", "note", "rewarded_at", "lot_id"])
            return ref

        if not Account.objects.filter(id=inviter).exists():
            return close(LoyaltyReferral.REJECTED, "Пригласивший удалил аккаунт")
        why = _same_person(lot.user_id, inviter)
        if why:
            return close(LoyaltyReferral.REJECTED, why)
        phone = Account.objects.filter(id=lot.user_id).values_list("phone", flat=True).first()
        key = phone_key(phone)
        if key and LoyaltyPhoneGrant.objects.filter(
                key=key, kind=LoyaltyPhoneGrant.REFERRAL).exists():
            return close(LoyaltyReferral.REJECTED, "За этот телефон бонус уже начисляли")
        start, end = month_bounds(month_of(now))
        done = LoyaltyReferral.objects.filter(
            inviter_id=inviter, status=LoyaltyReferral.REWARDED,
            rewarded_at__gte=start, rewarded_at__lt=end).count()
        if done >= int(config.get("CAP_REFERRALS_MONTH")):
            return close(LoyaltyReferral.CAPPED, CAP_MESSAGE)
        amount = int(config.get("BONUS_REFERRAL"))
        if amount <= 0:
            return close(LoyaltyReferral.CAPPED, "Бонус за приглашение выключен")
        lot_r = v1.accrue(inviter, amount, v1.REFERRAL, lot.user_id,
                          event_type="accrue_referral", status=True, now=now,
                          note="Бонус за приглашённого")
        if key:
            LoyaltyPhoneGrant.objects.get_or_create(key=key, kind=LoyaltyPhoneGrant.REFERRAL)
        ref.lot_id = lot_r.pk if lot_r else None
        close(LoyaltyReferral.REWARDED, "")
    v1._notify(inviter, f"+{amount} бонусов", "Приглашённый вами друг сделал первый заказ.")
    return ref
