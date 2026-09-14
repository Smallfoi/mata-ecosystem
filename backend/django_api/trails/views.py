"""API троп: приём трека, список троп, создание, доски.

Контракт (ECOSYSTEM_API.md → Trails).
"""
import uuid
from datetime import datetime
from datetime import timezone as dt_tz

from django.db import connection
from django.db.models import Min
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response

from common.people import club_names_of, names_of
from common.security import user_id_from_request
from league.models import RunnerProfile
from league.services import age_group, group_label
from trails import matching
from trails.models import PendingTrack, Trail, TrailAttempt


def _grow_footprint(user_id, track):
    """Растим личный «исследованный» след (D-74, вариант A): коридор ~25 м вдоль
    трека объединяем в footprints (вечный след). По нему открывается туман в режиме
    «Исследование». Хранит агрегат-полигон, не сырой трек (как и вся footprints)."""
    line = "LINESTRING(" + ", ".join(f"{p[1]} {p[0]}" for p in track) + ")"
    with connection.cursor() as cur:
        cur.execute(
            "SELECT ST_AsEWKT(ST_Multi(ST_CollectionExtract(ST_MakeValid("
            "ST_Buffer(ST_GeomFromText(%s,4326)::geography, 25)::geometry),3)))",
            [line],
        )
        corridor = (cur.fetchone() or [None])[0]
        if not corridor or "EMPTY" in corridor.upper():
            return
        cur.execute("SELECT 1 FROM footprints WHERE owner_id=%s", [user_id])
        if cur.fetchone():
            cur.execute(
                "UPDATE footprints SET geom=ST_Multi(ST_CollectionExtract("
                "ST_Union(geom, ST_GeomFromEWKT(%s)),3)), updated_at=now() WHERE owner_id=%s",
                [corridor, user_id],
            )
        else:
            cur.execute(
                "INSERT INTO footprints (owner_id, geom, updated_at) "
                "VALUES (%s, ST_GeomFromEWKT(%s), now())",
                [user_id, corridor],
            )

MAX_TRACK_POINTS = 6000     # ~8 часов при точке в 5 секунд
MAX_TRAIL_POINTS = 500
MIN_TRAIL_LENGTH_M = 200    # короче — это не тропа, а перекрёсток
MAX_TRAIL_LENGTH_M = 42_195
NEARBY_PAD_DEG = 0.09       # ~10 км по широте: столько ищем «тропы рядом»


def _points(raw, with_time=False):
    """Разобрать точки из запроса. Мусор молча отбрасываем: один битый замер
    GPS не повод отклонить весь забег."""
    out = []
    for p in raw or []:
        try:
            lat = float(p[0])
            lon = float(p[1])
        except (TypeError, ValueError, IndexError):
            continue
        if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
            continue
        if with_time:
            try:
                ms = int(p[2])
            except (TypeError, ValueError, IndexError):
                continue
            out.append([lat, lon, ms])
        else:
            out.append([lat, lon])
    return out


@api_view(["POST"])
def submit_track(request):
    """Телефон присылает трек забега; сервер сверяет его с тропами и забывает трек.

    Ответ — только результаты: какие тропы пройдены и за сколько.
    """
    me = user_id_from_request(request)
    if not me:
        return Response({"detail": "Нет токена"}, status=401)

    profile = RunnerProfile.objects.filter(user_id=me).first()
    if profile and not profile.trails_enabled:
        # Человек выключил участие в тропах — трек не храним даже временно.
        return Response({"attempts": [], "skipped": "trailsDisabled"})

    data = request.data if isinstance(request.data, dict) else {}
    run_id = str(data.get("runId") or "").strip()[:40]
    if not run_id:
        return Response({"detail": "Нет runId"}, status=400)

    track = _points(data.get("points"), with_time=True)
    if len(track) < 2:
        return Response({"detail": "Слишком короткий трек"}, status=400)
    if len(track) > MAX_TRACK_POINTS:
        track = track[:MAX_TRACK_POINTS]

    PendingTrack.objects.update_or_create(
        run_id=run_id,
        defaults={"user_id": me, "points": track, "received_at": timezone.now()},
    )

    min_lat, max_lat, min_lon, max_lon = matching.bbox([[p[0], p[1]] for p in track])
    candidates = Trail.objects.filter(
        is_public=True,
        min_lat__lte=max_lat + 0.01,
        max_lat__gte=min_lat - 0.01,
        min_lon__lte=max_lon + 0.01,
        max_lon__gte=min_lon - 0.01,
    )

    found = []
    for trail in candidates:
        hit = matching.match(trail.points, track)
        if not hit:
            continue
        started = datetime.fromtimestamp(hit["startedAtMs"] / 1000, tz=dt_tz.utc)
        attempt, _ = TrailAttempt.objects.update_or_create(
            trail_id=trail.id,
            run_id=run_id,
            defaults={
                "id": f"{trail.id}:{run_id}",
                "user_id": me,
                "started_at": started,
                "duration_s": hit["durationS"],
            },
        )
        found.append({**attempt.to_json(), "trailName": trail.name})

    # Исследование карты (D-74, A): растим личный след из трека для тумана.
    # Сбой следа не должен ломать ответ по тропам.
    if len(track) >= 2:
        try:
            _grow_footprint(me, track)
        except Exception:
            pass

    return Response({"attempts": found})


@api_view(["GET", "POST"])
def trails(request):
    me = user_id_from_request(request)
    if not me:
        return Response({"detail": "Нет токена"}, status=401)

    if request.method == "GET":
        qs = Trail.objects.filter(is_public=True)
        lat = request.query_params.get("lat")
        lon = request.query_params.get("lon")
        if lat and lon:
            try:
                lat, lon = float(lat), float(lon)
                qs = qs.filter(
                    min_lat__lte=lat + NEARBY_PAD_DEG,
                    max_lat__gte=lat - NEARBY_PAD_DEG,
                    min_lon__lte=lon + NEARBY_PAD_DEG,
                    max_lon__gte=lon - NEARBY_PAD_DEG,
                )
            except ValueError:
                pass

        items = list(qs[:100])
        ids = [t.id for t in items]
        mine = set(
            TrailAttempt.objects.filter(
                user_id=me, trail_id__in=ids
            ).values_list("trail_id", flat=True)
        )

        # Квартал 2.0 (Ф0): двойная мотивация прямо в списке — «твоё лучшее»
        # и «чаще всех» за 90 дней. Троп ≤ 100 — считаем батчево.
        from datetime import timedelta as _td

        from django.db.models import Count, Min
        from django.utils import timezone as dj_tz

        my_best = {
            r["trail_id"]: r
            for r in TrailAttempt.objects.filter(user_id=me, trail_id__in=ids)
            .values("trail_id")
            .annotate(best=Min("duration_s"), n=Count("id"))
        }
        freq_leader = {}
        for r in (
            TrailAttempt.objects.filter(
                trail_id__in=ids,
                started_at__gte=dj_tz.now() - _td(days=90),
            )
            .values("trail_id", "user_id")
            .annotate(n=Count("id"))
        ):
            cur = freq_leader.get(r["trail_id"])
            if not cur or (r["n"], r["user_id"]) > (cur["n"], cur["user_id"]):
                freq_leader[r["trail_id"]] = r
        from common.people import names_of

        leader_names = names_of([r["user_id"] for r in freq_leader.values()])

        def _extras(tid):
            best = my_best.get(tid)
            leader = freq_leader.get(tid)
            return {
                "myBestS": best["best"] if best else None,
                "myAttempts": best["n"] if best else 0,
                "frequentLeader": (
                    {
                        "name": leader_names.get(leader["user_id"], "Бегун"),
                        "count": leader["n"],
                        "isMe": leader["user_id"] == me,
                    }
                    if leader
                    else None
                ),
            }

        return Response({
            "items": [
                {
                    **t.to_json(),
                    "createdByMe": t.created_by == me,
                    "attemptedByMe": t.id in mine,
                    **_extras(t.id),
                }
                for t in items
            ]
        })

    # POST — тропу рисует человек: клуб отмечает свой круг, бегун — маршрут у дома.
    data = request.data if isinstance(request.data, dict) else {}
    name = str(data.get("name") or "").strip()[:120]
    if not name:
        return Response({"detail": "Нужно название тропы"}, status=400)

    pts = _points(data.get("points"))
    if len(pts) < 2:
        return Response({"detail": "Нужны точки маршрута"}, status=400)
    if len(pts) > MAX_TRAIL_POINTS:
        pts = matching.simplify(pts, min_gap_m=25.0)[:MAX_TRAIL_POINTS]
    else:
        pts = matching.simplify(pts)

    length = matching.line_length_m(pts)
    if length < MIN_TRAIL_LENGTH_M:
        return Response({"detail": "Тропа короче 200 метров"}, status=400)
    if length > MAX_TRAIL_LENGTH_M:
        return Response({"detail": "Тропа длиннее марафона"}, status=400)

    min_lat, max_lat, min_lon, max_lon = matching.bbox(pts)
    trail = Trail.objects.create(
        id=uuid.uuid4().hex[:24],
        name=name,
        city=str(data.get("city") or "").strip()[:120],
        points=pts,
        length_m=length,
        min_lat=min_lat, max_lat=max_lat, min_lon=min_lon, max_lon=max_lon,
        created_by=me,
    )
    return Response({**trail.to_json(), "createdByMe": True, "attemptedByMe": False})


@api_view(["GET"])
def boards(request, trail_id):
    """Четыре доски тропы. Та же мысль, что и в лиге: у каждой свой победитель."""
    me = user_id_from_request(request)
    if not me:
        return Response({"detail": "Нет токена"}, status=401)

    trail = Trail.objects.filter(id=trail_id).first()
    if not trail:
        return Response({"detail": "Тропа не найдена"}, status=404)

    board = request.query_params.get("board", "fastest")
    if board not in ("fastest", "mine", "frequent", "mylane"):
        board = "fastest"

    attempts = TrailAttempt.objects.filter(trail_id=trail_id)

    if board == "mine":
        # Мой прогресс: попытки по времени, лучшая — сверху.
        rows = [
            {
                "attemptId": a.id,
                "startedAtMs": int(a.started_at.timestamp() * 1000),
                "durationS": a.duration_s,
            }
            for a in attempts.filter(user_id=me).order_by("-started_at")[:50]
        ]
        best = min((r["durationS"] for r in rows), default=None)
        return Response({
            "trail": {"id": trail.id, "name": trail.name, "lengthM": round(trail.length_m)},
            "board": board,
            "unit": "с",
            "me": {"attempts": len(rows), "best": best},
            "top": rows,
        })

    if board == "frequent":
        # Кто бежал чаще за 90 дней — «местная легенда» в нашем исполнении:
        # за этим может гнаться вся база, а не только самые быстрые.
        since = timezone.now() - timezone.timedelta(days=90)
        counts = {}
        for a in attempts.filter(started_at__gte=since).only("user_id"):
            counts[a.user_id] = counts.get(a.user_id, 0) + 1
        ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        return _ranked_response(trail, board, ranked, me, "попыток")

    # fastest и mylane: лучшее время каждого
    best_by_user = (
        attempts.values("user_id").annotate(best=Min("duration_s")).order_by("best")
    )
    pairs = [(r["user_id"], r["best"]) for r in best_by_user]

    group = None
    if board == "mylane":
        profile = RunnerProfile.objects.filter(user_id=me).first()
        my_age = age_group(profile.birth_year) if profile else None
        my_gender = (profile.gender or "") if profile else ""
        if not my_age or not my_gender:
            return Response({
                "trail": {"id": trail.id, "name": trail.name, "lengthM": round(trail.length_m)},
                "board": board, "unit": "с", "needsProfile": True,
                "me": {"place": None, "of": 0, "value": None, "aheadOf": 0}, "top": [],
            })
        peers = {
            p.user_id
            for p in RunnerProfile.objects.filter(gender=my_gender).only("user_id", "birth_year", "gender")
            if age_group(p.birth_year) == my_age
        }
        pairs = [(uid, v) for uid, v in pairs if uid in peers]
        group = {"age": my_age, "gender": my_gender, "label": group_label(my_age, my_gender)}

    body = _ranked_response(trail, board, pairs, me, "с")
    if group:
        body.data["group"] = group
    return body


def _ranked_response(trail, board, ranked, me, unit):
    """Общий вид доски: топ, моё место и сколько человек позади."""
    uids = [uid for uid, _ in ranked[:20]]
    names = names_of(uids)
    clubs = club_names_of(uids)
    top = [
        {
            "userId": uid,
            "name": names.get(uid, "—"),
            "club": clubs.get(uid),
            "value": value,
            "place": i + 1,
            "isMe": uid == me,
        }
        for i, (uid, value) in enumerate(ranked[:20])
    ]
    place = next((i + 1 for i, (uid, _) in enumerate(ranked) if uid == me), None)
    value = next((v for uid, v in ranked if uid == me), None)
    return Response({
        "trail": {"id": trail.id, "name": trail.name, "lengthM": round(trail.length_m)},
        "board": board,
        "unit": unit,
        "me": {
            "place": place,
            "of": len(ranked),
            "value": value,
            "aheadOf": (len(ranked) - place) if place else 0,
        },
        "top": top,
    })
