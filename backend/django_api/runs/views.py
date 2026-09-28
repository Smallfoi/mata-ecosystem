"""Синхронизация истории пробежек + серверный расчёт очков (анти-чит S-04).
- GET  /v1/runs            → история пользователя (сводки, новые сверху);
- POST /v1/runs            → загрузить завершённый забег (идемпотентно по id);
                             СЕРВЕР сам валидирует забег и начисляет очки за бег
                             (клиент очки больше не присылает — иначе их можно подделать).
Требуется Bearer-токен. Сырой GPS-маршрут НЕ принимаем/не храним (приватность §2)."""
from datetime import datetime, timedelta, timezone as dt_timezone

from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response

from common.locks import ACTIVITY, lock_user
from common.numeric import BadNumber, bounded_int, finite_float
from common.security import user_id_from_request
from loyalty.models import LoyaltyTransaction, add_txn

from .models import Run
# Пороги и цена километра — общие для приёма забега, разбора и часов (runs/rules.py).
from .rules import (  # noqa: F401  (re-export: workouts берёт POINTS_PER_KM отсюда)
    FUTURE_SKEW,
    MAX_DAY_DISTANCE_M,
    MAX_RUN_AGE,
    MAX_RUN_DISTANCE_M,
    MAX_RUNS_PER_DAY,
    MAX_SPEED_MS,
    POINTS_PER_KM,
    REVIEW_FLAGGED_THRESHOLD,
    REVIEW_WINDOW,
    points_for,
)

_MAX = 100

# Жёсткие границы разбора (аудит D04). Не античит — тот в _validate и ставит флаг;
# это защита от значений, которые ломают базу/datetime или пишут в историю
# бесконечную дистанцию. Клиент (completed_runs_provider.dart) шлёт метры double,
# секунды int, время в мс — всё это с большим запасом внутри границ.
_MAX_DISTANCE_M = 10_000_000.0
_MAX_DURATION_S = 30 * 24 * 3600
_MAX_TIMESTAMP_MS = 4_102_444_800_000   # 01.01.2100
_MAX_ZONES = 1_000_000

# Не заваливать человека уведомлениями: о том, что забеги ушли на проверку,
# сообщаем не чаще раза в сутки (иначе накрутчик получит десяток писем подряд,
# а честный бегун с одним сбоем GPS — ровно одно).
FLAG_NOTICE_COOLDOWN = 24 * 3600


def _validate(uid, distance_m, duration_s, finished, mock=False):
    """Возвращает причину флага (str) или '' если забег правдоподобен."""
    now = timezone.now()
    # Клиент сообщил о поддельной геолокации (Android mock-provider) — сразу флаг.
    if mock:
        return "Подделка местоположения (mock GPS)"
    # Anti-replay (S-04): время забега в будущем или слишком старое — подделка.
    if finished > now + FUTURE_SKEW:
        return "Дата забега в будущем"
    if finished < now - MAX_RUN_AGE:
        return "Слишком старый забег (возможный реплей)"
    if distance_m <= 0:
        return "Нулевая дистанция"
    if duration_s <= 0:
        return "Нет длительности забега"
    if distance_m / duration_s > MAX_SPEED_MS:
        return "Скорость выше 40 км/ч (спуфинг/телепорт)"
    if distance_m > MAX_RUN_DISTANCE_M:
        return "Дистанция за забег неправдоподобна"
    # Суточные лимиты за календарный день (UTC).
    day_start = finished.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    todays = list(
        Run.objects.filter(
            user_id=uid, flagged=False, finished_at__gte=day_start,
            finished_at__lt=day_end,
        )
    )
    if len(todays) >= MAX_RUNS_PER_DAY:  # анти-спам: слишком много забегов за сутки
        return "Слишком много забегов за день"

    # Дистанцию считаем по СВОИМ забегам И импорту с часов вместе. Раздельные
    # потолки обходятся тривиально: набрал лимит импортом, потом столько же
    # своими забегами — и суточная норма удвоилась. Импорт (workouts/views.py)
    # уже считает обе стороны; здесь этого не хватало.
    from workouts.models import ExternalWorkout

    imported = sum(
        w.distance_m
        for w in ExternalWorkout.objects.filter(
            user_id=uid, flagged=False, run_id="",
            started_at__gte=day_start, started_at__lt=day_end,
        )
    )
    if sum(r.distance_m for r in todays) + imported + distance_m > MAX_DAY_DISTANCE_M:
        return "Превышен суточный лимит дистанции"
    return ""


def _maybe_flag_for_review(uid):
    """Накопилось много флагнутых забегов за окно → помечаем аккаунт на ревью.
    Бан НЕ автоматический — это сигнал модератору присмотреться (S-04, hold/review)."""
    from accounts.models import Account

    since = timezone.now() - REVIEW_WINDOW
    flagged_count = Run.objects.filter(
        user_id=uid, flagged=True, created_at__gte=since
    ).count()
    if flagged_count >= REVIEW_FLAGGED_THRESHOLD:
        Account.objects.filter(id=uid, needs_review=False).update(needs_review=True)


def _notify_on_hold(uid):
    """Сказать бегуну, что забег ушёл на проверку.

    Раньше помеченный забег просто не приносил баллов, и человек оставался в
    тишине: сам он видит обычную пробежку, а баллов нет — выглядит как поломка.
    Пишем один раз в сутки и без обвинений: решение принимает человек, а сбой
    GPS случается и у честных бегунов. Сбой уведомления не должен ронять приём
    забега — он уже сохранён.
    """
    if not cache.add(f"run_hold_notice_{uid}", 1, FLAG_NOTICE_COOLDOWN):
        return
    try:
        from notifications.models import create_notification

        create_notification(
            uid,
            "Забег на проверке",
            "Данные забега выглядят необычно, поэтому баллы пока не начислены. "
            "Проверим вручную — если всё в порядке, баллы придут.",
            type="system",
        )
    except Exception:
        pass


def _run_id_taken_by_other(rid, uid):
    """runId уже принадлежит другому человеку через трек или попытку тропы."""
    from trails.models import PendingTrack, TrailAttempt

    return (
        PendingTrack.objects.filter(run_id=rid).exclude(user_id=uid).exists()
        or TrailAttempt.objects.filter(run_id=rid).exclude(user_id=uid).exists()
    )


def _finish_award(run):
    """Довести начисление, которое не дошло (аудит C05).

    До этой правки забег и транзакция писались раздельно: обрыв между ними
    оставлял забег с `points_awarded > 0` без транзакции, а повтор из офлайн-очереди
    отвечал «дубль» и ничего не чинил. Теперь повтор доначисляет ровно один раз:
    строка забега блокируется, наличие транзакции по run_id проверяется под
    блокировкой. Помеченные и отклонённые забеги (flagged) не трогаем — там
    решение за модератором.
    """
    if run.flagged or run.points_awarded <= 0:
        return
    with transaction.atomic():
        locked = Run.objects.select_for_update().filter(id=run.id).first()
        if not locked or locked.flagged or locked.points_awarded <= 0:
            return
        if LoyaltyTransaction.objects.filter(
            user_id=locked.user_id, run_id=locked.id, source="runnerRun"
        ).exists():
            return
        add_txn(locked.user_id, locked.points_awarded, "runnerRun",
                f"Пробежка {locked.distance_km:.1f} км", None, locked.id)


@api_view(["GET", "POST"])
def runs(request):
    uid = user_id_from_request(request)
    if not uid:
        return Response({"detail": "Нет токена"}, status=401)

    if request.method == "GET":
        rows = Run.objects.filter(user_id=uid)[:_MAX]
        return Response([r.to_json() for r in rows])

    # POST — загрузка завершённого забега
    d = request.data
    if not isinstance(d, dict):
        return Response({"detail": "Ожидается объект забега"}, status=400)
    rid = (str(d.get("id") or "")).strip()[:40]
    if not rid:
        return Response({"detail": "Нет id забега"}, status=400)

    # Повтор (ретрай/офлайн-очередь) с тем же id ничего не задваивает — отдаём как есть.
    existing = Run.objects.filter(id=rid).first()
    if existing:
        if existing.user_id != uid:
            return Response({"detail": "Конфликт id"}, status=409)
        _finish_award(existing)
        return Response({
            "ok": True, "duplicate": True,
            "flagged": existing.flagged, "flagReason": existing.flag_reason,
            "pointsAwarded": existing.points_awarded, "run": existing.to_json(),
        })

    # Трек забега мог прийти раньше сводки (аудит C01): если этот runId уже занят
    # треком или попыткой тропы другого человека — забег не его.
    if _run_id_taken_by_other(rid, uid):
        return Response({"detail": "Конфликт id"}, status=409)

    try:
        distance_m = finite_float(d.get("distanceMeters") or 0, 0, _MAX_DISTANCE_M)
        duration_s = bounded_int(d.get("elapsedSeconds") or 0, 0, _MAX_DURATION_S)
        captured_zones = bounded_int(d.get("capturedZones") or 0, 0, _MAX_ZONES)
        ms = d.get("finishedAtMs")
        finished = (
            datetime.fromtimestamp(
                bounded_int(ms, 0, _MAX_TIMESTAMP_MS) / 1000, tz=dt_timezone.utc
            )
            if ms is not None
            else timezone.now()
        )
    except BadNumber:
        return Response({"detail": "Некорректные числа в забеге"}, status=400)

    mock = bool(d.get("mockDetected"))  # клиент сообщает о mock-GPS (Android)

    # Забег и начисление — одно целое (аудит C05): сбой посередине откатывает оба,
    # и повтор из офлайн-очереди проходит заново. Run.id (PK) — уникальный ключ:
    # параллельный повтор упрётся в него и получит ответ «дубль».
    try:
        with transaction.atomic():
            # Суточные лимиты (число забегов, дистанция вместе с импортом с часов)
            # проверяем и записываем под блокировкой на пользователя (аудит C06):
            # иначе параллельные забеги с разными id все видят «лимит не достигнут».
            lock_user(ACTIVITY, uid)
            # Анти-чит: считаем очки на сервере; неправдоподобный забег → флаг + 0 очков.
            reason = _validate(uid, distance_m, duration_s, finished, mock=mock)
            flagged = bool(reason)
            points = 0 if flagged else points_for(distance_m)
            run = Run.objects.create(
                id=rid,
                user_id=uid,
                distance_m=distance_m,
                duration_s=duration_s,
                captured_territory=bool(d.get("capturedTerritory")),
                captured_zones=captured_zones,
                finished_at=finished,
                points_awarded=points,
                flagged=flagged,
                flag_reason=reason,
            )
            # Начисляем за бег ровно один раз на забег. Если транзакция по этому
            # runId уже есть (защита от рассинхрона) — не дублируем.
            if points > 0 and not LoyaltyTransaction.objects.filter(
                user_id=uid, run_id=rid, source="runnerRun"
            ).exists():
                add_txn(uid, points, "runnerRun",
                        f"Пробежка {distance_m / 1000.0:.1f} км", None, rid)
    except IntegrityError:
        existing = Run.objects.filter(id=rid).first()
        if not existing or existing.user_id != uid:
            return Response({"detail": "Конфликт id"}, status=409)
        return Response({
            "ok": True, "duplicate": True,
            "flagged": existing.flagged, "flagReason": existing.flag_reason,
            "pointsAwarded": existing.points_awarded, "run": existing.to_json(),
        })

    # Вехи пожизненных километров (Квартал 2.0, Ф4) — идемпотентно.
    if not flagged:
        from runs.milestones import award_milestones

        award_milestones(uid, distance_m / 1000.0)

    # Режим доверия: если забегов с флагом накопилось много — пометить на ревью.
    if flagged:
        _maybe_flag_for_review(uid)
        _notify_on_hold(uid)

    # Аналитика (D-30): завершённый забег (км/очки/флаг).
    from analytics.models import E_RUN_FINISHED, track

    track(E_RUN_FINISHED, user_id=uid, source="kvartal",
          km=round(distance_m / 1000.0, 2), points=points, flagged=flagged)

    return Response({
        "ok": True, "duplicate": False,
        "flagged": flagged, "flagReason": reason,
        "pointsAwarded": points, "run": run.to_json(),
    })


# Разбор помеченных забегов живёт в runs/review.py. Здесь оставлена ссылка:
# на `runs.views.approve_run` уже завязаны админ-действия и тесты.
from .review import approve_run  # noqa: E402,F401  (после моделей — избегаем цикла)
