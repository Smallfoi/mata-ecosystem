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
import hashlib
from datetime import datetime, timedelta
from datetime import timezone as dt_tz

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response

from common.locks import ACTIVITY, lock_user
from common.numeric import BadNumber, bounded_int, finite_float
from common.security import user_id_from_request
from loyalty.models import add_txn
from runs.models import Run
from runs.views import (
    FUTURE_SKEW,
    MAX_DAY_DISTANCE_M,
    MAX_RUN_AGE,
    MAX_RUN_DISTANCE_M,
    MAX_SPEED_MS,
    POINTS_PER_KM,
)
from workouts.models import ExternalWorkout, WorkoutAward

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

    imported = duplicates = skipped = 0
    points_total = 0
    result = []

    for raw in items:
        data, why = _parse_item(raw)
        if not data:
            skipped += 1
            continue

        existing = ExternalWorkout.objects.filter(
            user_id=me, source=source, source_id=data["source_id"]
        ).first()
        if existing:
            duplicates += 1
            result.append(existing.to_json())
            continue

        # Идентификатор детерминированный: одна и та же тренировка одного источника
        # даёт одну и ту же запись даже при гонке двух параллельных запросов.
        wid = hashlib.sha1(f"{me}:{source}:{data['source_id']}".encode()).hexdigest()[:32]

        # Тренировка, реестр и начисление — одно целое (аудит C05): сбой посередине
        # откатывает всё, и повтор той же присылки доводит начисление ровно один раз.
        try:
            with transaction.atomic():
                # Суточный потолок дистанции общий со своими забегами — проверка и
                # запись под той же блокировкой на пользователя (аудит C06).
                lock_user(ACTIVITY, me)
                flag_reason = _validate(me, data)
                same_run = None if flag_reason else _find_same_run(me, data)

                points = 0
                if not flag_reason and not same_run and data["sport"] in RUNNING_SPORTS:
                    points = round(data["distance_m"] / 1000.0 * POINTS_PER_KM)

                # Реестр переживает отключение источника (аудит C02): если по этой
                # тренировке решение уже принималось, второй раз не платим —
                # показываем то, что было начислено тогда.
                prior = WorkoutAward.objects.select_for_update().filter(id=wid).first()
                if prior:
                    points = 0
                workout = ExternalWorkout.objects.create(
                    id=wid,
                    user_id=me,
                    source=source,
                    run_id=same_run.id if same_run else "",
                    points_awarded=prior.points if prior else points,
                    flagged=bool(flag_reason),
                    flag_reason=flag_reason,
                    **data,
                )
                if not prior:
                    txn = None
                    if points:
                        txn = add_txn(
                            me, points, "runnerRun",
                            f"Тренировка из внешнего источника: {workout.distance_km:.1f} км",
                        )
                    WorkoutAward.objects.create(
                        id=wid, user_id=me, source=source, points=points,
                        txn_id=txn.id if txn else "",
                    )
        except IntegrityError:
            # Параллельный запрос с той же тренировкой успел первым — это дубль.
            duplicates += 1
            existing = ExternalWorkout.objects.filter(id=wid).first()
            if existing:
                result.append(existing.to_json())
            continue
        points_total += points
        imported += 1
        result.append(workout.to_json())

    return Response({
        "imported": imported,
        "duplicates": duplicates,
        "skipped": skipped,
        "points": points_total,
        "items": result,
    })


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
