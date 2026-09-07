"""Синхронизация истории пробежек + серверный расчёт очков (анти-чит S-04).
- GET  /v1/runs            → история пользователя (сводки, новые сверху);
- POST /v1/runs            → загрузить завершённый забег (идемпотентно по id);
                             СЕРВЕР сам валидирует забег и начисляет очки за бег
                             (клиент очки больше не присылает — иначе их можно подделать).
Требуется Bearer-токен. Сырой GPS-маршрут НЕ принимаем/не храним (приватность §2)."""
from datetime import datetime, timedelta, timezone as dt_timezone

from django.core.cache import cache
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response

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
    rid = (str(d.get("id") or "")).strip()[:40]
    if not rid:
        return Response({"detail": "Нет id забега"}, status=400)

    # Повтор (ретрай/офлайн-очередь) с тем же id ничего не задваивает — отдаём как есть.
    existing = Run.objects.filter(id=rid).first()
    if existing:
        if existing.user_id != uid:
            return Response({"detail": "Конфликт id"}, status=409)
        return Response({
            "ok": True, "duplicate": True,
            "flagged": existing.flagged, "flagReason": existing.flag_reason,
            "pointsAwarded": existing.points_awarded, "run": existing.to_json(),
        })

    distance_m = float(d.get("distanceMeters") or 0)
    duration_s = int(d.get("elapsedSeconds") or 0)

    ms = d.get("finishedAtMs")
    try:
        finished = (
            datetime.fromtimestamp(int(ms) / 1000, tz=dt_timezone.utc)
            if ms is not None
            else timezone.now()
        )
    except (TypeError, ValueError, OSError):
        finished = timezone.now()

    # Анти-чит: считаем очки на сервере; неправдоподобный забег → флаг + 0 очков.
    mock = bool(d.get("mockDetected"))  # клиент сообщает о mock-GPS (Android)
    reason = _validate(uid, distance_m, duration_s, finished, mock=mock)
    flagged = bool(reason)
    points = 0 if flagged else points_for(distance_m)

    run = Run.objects.create(
        id=rid,
        user_id=uid,
        distance_m=distance_m,
        duration_s=duration_s,
        captured_territory=bool(d.get("capturedTerritory")),
        captured_zones=int(d.get("capturedZones") or 0),
        finished_at=finished,
        points_awarded=points,
        flagged=flagged,
        flag_reason=reason,
    )

    # Начисляем за бег ровно один раз на забег (идемпотентность гарантирует Run.id).
    # Если запись транзакции по этому runId уже есть (защита от рассинхрона) — не дублируем.
    if points > 0 and not LoyaltyTransaction.objects.filter(
        user_id=uid, run_id=rid, source="runnerRun"
    ).exists():
        add_txn(uid, points, "runnerRun",
                f"Пробежка {distance_m / 1000.0:.1f} км", None, rid)

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
