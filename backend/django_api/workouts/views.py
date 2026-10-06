"""Приём тренировок из внешних источников (Health Connect, файлы, партнёрские API).

Контракт: ECOSYSTEM_API.md → Workouts.

Три правила, без которых импорт превращается в дыру:
  1. повторная присылка той же тренировки не создаёт вторую и не начисляет очки
     заново — источники присылают одно и то же по многу раз, это норма;
  2. тренировка с часов и наш собственный забег в те же минуты — одно событие;
     очки за него уже начислены, второй раз не платим;
  3. импорт проходит тот же античит, что и свой забег: снаружи данные приходят
     от приложения, которое мы не контролируем.
"""
from datetime import datetime, timedelta
from datetime import timezone as dt_tz

from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response

from common.numeric import BadNumber, bounded_int, finite_float
from common.security import user_id_from_request
from runs.models import Run
from runs.views import (
    FUTURE_SKEW,
    MAX_DAY_DISTANCE_M,
    MAX_RUN_AGE,
    MAX_RUN_DISTANCE_M,
    MAX_SPEED_MS,
    POINTS_PER_KM,
)
from workouts.models import ExternalWorkout
from workouts.service import accept as _accept

def accept_workout(user_id, source, data):
    """Принять тренировку общим путём, передав ему наши правила проверки."""
    return _accept(
        user_id, source, data,
        validate=_validate,
        find_same_run=_find_same_run,
        running_sports=RUNNING_SPORTS,
        points_per_km=POINTS_PER_KM,
    )


MAX_ITEMS_PER_REQUEST = 200
# Насколько тренировка с часов может разойтись во времени с нашим забегом и всё
# ещё быть тем же событием. Часы и телефон стартуют не одновременно: человек
# запускает запись на часах, потом достаёт телефон.
SAME_EVENT_WINDOW = timedelta(minutes=20)
VALID_SOURCES = {s[0] for s in ExternalWorkout.SOURCES}
# Виды спорта, за которые начисляем очки. Всё остальное (велосипед, плавание)
# импортируем и показываем, но в беговые баллы не превращаем.
RUNNING_SPORTS = {"", "run", "running", "trail_running", "treadmill", "walking", "hiking"}

# Жёсткие границы разбора (аудит D04). Это не античит (он ниже, в _validate), а
# защита от значений, которые ломают datetime/базу: за ними — пропуск элемента.
MAX_TIMESTAMP_MS = 4_102_444_800_000   # 01.01.2100
MAX_DURATION_S = 30 * 24 * 3600
MAX_DISTANCE_M = 10_000_000.0
MAX_OPTIONAL_INT = 1_000_000


def _parse_item(raw):
    """Разбор одной тренировки. Возвращает (данные, причина отказа)."""
    if not isinstance(raw, dict):
        return None, "не объект"
    source_id = str(raw.get("sourceId") or "").strip()[:120]
    if not source_id:
        return None, "нет sourceId"
    # Границы шире любой реальной тренировки, но уже, чем ломает базу и datetime:
    # IntegerField — 32 бита, fromtimestamp падает на годах за 9999 (аудит D04).
    try:
        started_ms = bounded_int(raw.get("startedAtMs"), 0, MAX_TIMESTAMP_MS)
        duration_s = bounded_int(raw.get("durationS") or 0, 0, MAX_DURATION_S)
        distance_m = finite_float(raw.get("distanceM") or 0, 0, MAX_DISTANCE_M)
    except BadNumber:
        return None, "нечисловые поля"

    def opt_int(key):
        # Пульс и калории — справочно: мусор отбрасываем, тренировку не теряем.
        v = raw.get(key)
        if v is None:
            return None
        try:
            return bounded_int(v, 0, MAX_OPTIONAL_INT)
        except BadNumber:
            return None

    return {
        "source_id": source_id,
        "started_at": datetime.fromtimestamp(started_ms / 1000, tz=dt_tz.utc),
        "duration_s": duration_s,
        "distance_m": distance_m,
        "sport": str(raw.get("sport") or "").strip().lower()[:30],
        "avg_hr": opt_int("avgHr"),
        "max_hr": opt_int("maxHr"),
        "calories": opt_int("calories"),
    }, ""


def _validate(uid, data):
    """Тот же здравый смысл, что и для своих забегов: невозможное не засчитываем."""
    now = timezone.now()
    started = data["started_at"]
    if started > now + FUTURE_SKEW:
        return "Дата тренировки в будущем"
    if started < now - MAX_RUN_AGE:
        return "Слишком старая тренировка"
    if data["distance_m"] <= 0:
        return "Нулевая дистанция"
    if data["duration_s"] <= 0:
        return "Нет длительности"
    if data["distance_m"] / data["duration_s"] > MAX_SPEED_MS:
        return "Скорость выше 40 км/ч"
    if data["distance_m"] > MAX_RUN_DISTANCE_M:
        return "Дистанция неправдоподобна"

    # Суточный потолок считаем по всему вместе — своим забегам и импорту.
    # Иначе достаточно завести второй источник, чтобы обойти лимит.
    day_start = started.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    own = sum(
        r.distance_m
        for r in Run.objects.filter(
            user_id=uid, flagged=False, finished_at__gte=day_start, finished_at__lt=day_end
        )
    )
    imported = sum(
        w.distance_m
        for w in ExternalWorkout.objects.filter(
            user_id=uid, flagged=False, run_id="", started_at__gte=day_start, started_at__lt=day_end
        )
    )
    if own + imported + data["distance_m"] > MAX_DAY_DISTANCE_M:
        return "Превышен суточный лимит дистанции"
    return ""


def _find_same_run(uid, data):
    """Наш забег, который на самом деле та же тренировка.

    Человек бежит с часами и с телефоном — приходят две записи об одном выходе.
    Считаем их одним событием, если они пересекаются по времени и дистанция
    близка: часы и телефон меряют чуть по-разному, но не вдвое.
    """
    started = data["started_at"]
    finished = started + timedelta(seconds=data["duration_s"])
    candidates = Run.objects.filter(
        user_id=uid,
        finished_at__gte=started - SAME_EVENT_WINDOW,
        finished_at__lte=finished + SAME_EVENT_WINDOW,
    )
    for run in candidates:
        if data["distance_m"] <= 0 or run.distance_m <= 0:
            continue
        ratio = min(run.distance_m, data["distance_m"]) / max(run.distance_m, data["distance_m"])
        if ratio >= 0.75:
            return run
    return None


@api_view(["POST"])
def import_workouts(request):
    me = user_id_from_request(request)
    if not me:
        return Response({"detail": "Нет токена"}, status=401)

    body = request.data if isinstance(request.data, dict) else {}
    source = str(body.get("source") or "").strip().lower()
    if source not in VALID_SOURCES:
        return Response({"detail": "Неизвестный источник"}, status=400)

    items = body.get("items")
    if not isinstance(items, list):
        return Response({"detail": "Нет списка тренировок"}, status=400)
    items = items[:MAX_ITEMS_PER_REQUEST]

    from loyalty import config as loyalty_config

    v1_on = loyalty_config.enabled()
    imported = duplicates = skipped = 0
    points_total = 0
    bonus_total = 0
    capped_total, cap_note = 0, ""
    result = []

    for raw in items:
        data, why = _parse_item(raw)
        if not data:
            skipped += 1
            continue

        workout, outcome = accept_workout(me, source, data)
        if outcome == "duplicate":
            duplicates += 1
            if workout:
                result.append(workout.to_json())
            continue
        if getattr(workout, "points_capped", 0):
            capped_total += workout.points_capped
            cap_note = workout.cap_reason
        points_total += getattr(workout, "points_this_time", 0)
        imported += 1
        item = workout.to_json()
        act = getattr(workout, "bonus_act", None)
        if act is not None:
            bonus_total += getattr(workout, "bonus_this_time", 0)
            # Новое поле (программа v1): решение по бонусу за эту тренировку.
            item["bonus"] = {"amount": act.amount, "status": act.status, "reason": act.reason}
        result.append(item)

    out = {
        "imported": imported,
        "duplicates": duplicates,
        "skipped": skipped,
        "points": points_total,
        "items": result,
    }
    if v1_on:
        # Программа v1: «points» — начисленные бонусы (то, что попало в кошелёк).
        out["points"] = bonus_total
    if capped_total:
        # Новые поля (старые клиенты их не читают): часть баллов срезал потолок.
        out.update({"dailyCapReached": True, "pointsCapped": capped_total,
                    "capReason": cap_note})
    return Response(out)


@api_view(["GET"])
def workouts(request):
    me = user_id_from_request(request)
    if not me:
        return Response({"detail": "Нет токена"}, status=401)
    qs = ExternalWorkout.objects.filter(user_id=me)
    source = request.query_params.get("source")
    if source in VALID_SOURCES:
        qs = qs.filter(source=source)
    return Response({"items": [w.to_json() for w in qs[:200]]})


@api_view(["DELETE"])
def disconnect(request, source):
    """Человек отключил источник — удаляем всё, что от него пришло.

    Это требование и Apple, и Garmin, и просто честность: данные остаются, пока
    человек разрешает их брать. Начисленные баллы не отзываем — он их заработал.
    Реестр учтённых тренировок (WorkoutAward) остаётся: в нём нет самих данных,
    только след «за это уже заплачено» — иначе переподключение платило бы снова.
    """
    me = user_id_from_request(request)
    if not me:
        return Response({"detail": "Нет токена"}, status=401)
    if source not in VALID_SOURCES:
        return Response({"detail": "Неизвестный источник"}, status=400)
    removed, _ = ExternalWorkout.objects.filter(user_id=me, source=source).delete()
    return Response({"removed": removed})
