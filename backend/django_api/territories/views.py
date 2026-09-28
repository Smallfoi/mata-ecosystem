"""
Территории (D-09) на PostGIS, raw SQL.
- захват по реальному маршруту: своя территория растёт через ST_Union (расширение),
  у чужих вычитается пересечение через ST_Difference (перехват);
- сглаживание/чистка GPS при фиксации: ST_SimplifyPreserveTopology + ST_MakeValid;
- ЖИВОЙ слой (карта/рейтинг/клубы): территория живёт LIVE_TTL_HOURS (7 дней) от
  последнего забега; забег обновляет captured_at и продлевает; протухшие удаляются лениво;
- ВЕЧНЫЙ личный след (footprints): объединение всего, что юзер когда-либо пробежал —
  растёт и НЕ уменьшается (ни временем, ни перехватом). Для профиля (исследовано км²);
- античит: скорость (дистанция = max(присланная, длина маршрута); без времени —
  захват без баллов), мин/макс площадь, кулдаун, суточный потолок под блокировкой;
- загрузка по видимой области (bbox), отметка mine/club/enemy.
Один владелец = одна (мульти)территория (owner_id UNIQUE).
"""
import json
import math
import secrets
from datetime import timedelta

from django.db import connection, transaction
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response

from clubs.models import ClubMember
from common.locks import TERRITORY, lock_user
from common.numeric import BadNumber, finite_float
from common.security import user_id_from_request
from loyalty.models import LoyaltyTransaction

from .awards import claim as claim_capture
from .models import CaptureAward

# Валидный сглаженный captured-полигон из WKT. Порядок обработки — броня от
# GPS-игл (03.09.2026, «Идеальный маршрут»):
# 1) ST_MakeValid — самопересечения «бабочек» становятся отдельными кусками;
# 2) морфологическое ОТКРЫТИЕ: буфер внутрь-наружу ∓CLOSE_EPS_M по geography —
#    тонкие выступы-иглы схлопываются в ноль, тело зоны восстанавливается
#    (лишь острые углы скругляются на ~CLOSE_EPS_M);
# 3) упрощение ~5 м + извлечение полигонов;
# 4) фильтр осколков: куски мельче SLIVER_MIN_M2 выбрасываются — остаётся зона.
CLOSE_EPS_M = 5.0
SLIVER_MIN_M2 = 50.0
_CAP_SQL = """
WITH v AS (
  SELECT ST_MakeValid(ST_GeomFromText(%s, 4326)) AS g
), c AS (
  SELECT ST_Buffer(ST_Buffer(g::geography, -%s), %s)::geometry AS g FROM v
), s AS (
  SELECT ST_Multi(ST_CollectionExtract(
           ST_MakeValid(ST_SimplifyPreserveTopology(g, 0.00005)), 3)) AS g
  FROM c
), d AS (
  SELECT (ST_Dump(g)).geom AS p FROM s
)
SELECT ST_AsEWKT(ST_Multi(ST_Collect(p)))
FROM d WHERE ST_Area(p::geography) >= %s
"""

# Живой слой территорий держится 7 дней без подтверждения забегом (мягкий распад).
# (имя HOLD_HOURS сохраняем — его импортирует leaderboard для фильтра свежести.)
HOLD_HOURS = 168
# Защита свежего захвата (Вариант Б, D-14): кусок, захваченный за последние
# PROTECT_HOURS, нельзя перехватить. Окно подкрутим по живому тесту.
PROTECT_HOURS = 24
# Хранение записей идемпотентности захвата (processed_captures). Клиент из офлайн-очереди
# не переотправит захват старше этого срока (да и территория живёт 7 дней) — безопасно
# чистить, чтобы таблица не пухла бесконечно (по строке на каждый захват навсегда).
PROCESSED_RETENTION_HOURS = 24 * 30  # 30 дней
# Античит.
MIN_CAPTURE_AREA_M2 = 100  # меньше — это не реальная петля, а дрожь GPS
MAX_CAPTURE_AREA_M2 = 2_000_000  # 2 км² за один забег — неправдоподобно (спуфинг/телепорт)
MAX_SPEED_MS = 11.2  # ~40 км/ч — серверный потолок скорости (см. CLAUDE.md)
CAPTURE_COOLDOWN_S = 30  # защита от спама захватами
# Суточный потолок захватов. Кулдауна в 30 секунд мало: он ограничивает темп, но
# не сумму — за сутки это 2880 захватов и 144 000 баллов, то есть деньги в Store
# из воздуха. Живому бегуну двадцати захватов в день с запасом хватает.
MAX_CAPTURES_PER_DAY = 20
TERRITORY_POINTS = 50  # номинал для теста суточного лимита (в capture() больше не плоский)
# Начисление за захват — по НОВОМУ следу: повтор того же места не растит footprint → 0
# баллов (закрывает ферму «круги вокруг киоска»). Большой новый круг ≈ прежние десятки.
AREA_PER_POINT_M2 = 100      # 1 балл за каждые 100 м² впервые исследованной земли
MAX_TERRITORY_POINTS = 100   # потолок за один захват (≥10 000 м² нового следа)


def _parse_ring(pts):
    """Точки контура → [(lng, lat), ...] или None, если хоть одна некорректна (D04).

    Клиент (territory_provider.dart) шлёт [[lat, lng], ...] числами. Раньше мусор
    (строка, словарь, «nan», одна координата) ронял захват в 500 или уходил в
    PostGIS; теперь это понятный 400. Одну битую точку НЕ выбрасываем молча, как в
    треке тропы: контур территории без неё — уже другая фигура.
    """
    ring = []
    for p in pts:
        if not isinstance(p, (list, tuple)) or len(p) < 2:
            return None
        try:
            lat = finite_float(p[0], -90, 90)
            lng = finite_float(p[1], -180, 180)
        except BadNumber:
            return None
        ring.append((lng, lat))
    return ring


_EARTH_R_M = 6_371_008.8
# Пробежки дольше недели не бывает; время вне (0; неделя] — «время неизвестно».
_MAX_ELAPSED_S = 7 * 24 * 3600
_MAX_DISTANCE_M = 10_000_000.0


def _route_length_m(ring):
    """Длина маршрута по точкам [(lng, lat), ...] БЕЗ замыкающего отрезка, м.

    Это нижняя граница пройденного: сервер видит её сам и не зависит от того,
    какую дистанцию клиент решил о себе сообщить (аудит C06).
    """
    total = 0.0
    for (lng1, lat1), (lng2, lat2) in zip(ring, ring[1:]):
        p1, p2 = math.radians(lat1), math.radians(lat2)
        dp, dl = p2 - p1, math.radians(lng2 - lng1)
        a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        total += 2 * _EARTH_R_M * math.asin(min(1.0, math.sqrt(a)))
    return total


def _opt_positive(value, hi):
    """Необязательное положительное число из запроса или None (нет/мусор/≤0)."""
    if value is None:
        return None
    try:
        v = finite_float(value, 0, hi)
    except BadNumber:
        return None
    return v if v > 0 else None


def _club_of(uid):
    m = ClubMember.objects.filter(user_id=uid).first()
    return m.club_id if m else None


@api_view(["POST"])
def capture(request):
    uid = user_id_from_request(request)
    if not uid:
        return Response({"detail": "Нет токена"}, status=401)
    if not isinstance(request.data, dict):
        return Response({"detail": "Ожидается объект"}, status=400)
    pts = request.data.get("points") or []
    if not isinstance(pts, (list, tuple)):
        return Response({"detail": "Некорректные точки маршрута"}, status=400)
    if len(pts) < 3:
        return Response({"detail": "Маршрут слишком короткий для территории"}, status=400)
    # Лимит на размер payload (P0 безопасность): защита от DoS-полигона. Даже ультра-забег
    # после клиентской фильтрации (точка/5м) — тысячи точек, не десятки тысяч.
    if len(pts) > 20_000:
        return Response({"detail": "Слишком много точек в маршруте"}, status=400)

    ring = _parse_ring(pts)  # (lng, lat)
    if ring is None:
        return Response({"detail": "Некорректные точки маршрута"}, status=400)

    # Античит по скорости (аудит C06: неполные данные не отключают проверку).
    # Дистанция — не меньше длины самого маршрута: занизить или не прислать её
    # больше нельзя. Время сервер сам не знает (у точек нет меток): если его нет,
    # оно мусорное или ≤ 0 — скорость не проверить, и такой захват засчитывается
    # на карте (старые сборки не отбиваем), но БЕЗ баллов (`unverified`).
    # mata_kvartal шлёт оба поля с июня 2026 (territory_provider.dart).
    route_m = _route_length_m(ring)
    client_distance = _opt_positive(request.data.get("distanceMeters"), _MAX_DISTANCE_M)
    elapsed = _opt_positive(request.data.get("elapsedSeconds"), _MAX_ELAPSED_S)
    distance = max(client_distance or 0.0, route_m)
    speed_verified = elapsed is not None
    if speed_verified and distance / elapsed > MAX_SPEED_MS:
        return Response(
            {"detail": "Слишком высокая скорость для забега — захват отклонён."},
            status=400,
        )

    if ring[0] != ring[-1]:
        ring.append(ring[0])
    wkt = "POLYGON((" + ", ".join(f"{lng} {lat}" for lng, lat in ring) + "))"
    club_id = _club_of(uid)
    # Идемпотентность (S-04): клиент шлёт captureId; повтор (ретрай офлайн-очереди)
    # не применяем заново — отдаём текущую территорию.
    capture_id = (str(request.data.get("captureId") or "")).strip()[:64] or None
    # id пробежки, к которой относится захват (новые сборки Квартала; старые не
    # шлют — тогда пробежка ищется по времени и цифрам, territories/awards.py).
    run_hint = (str(request.data.get("runId") or "")).strip()[:40]
    with transaction.atomic():
        # Один захват человека за раз (аудит C06): иначе параллельные запросы
        # оба проходят суточный потолок и кулдаун, а новый след (баллы) у обоих
        # считается от одной и той же площади «до» — земля оплачивается дважды.
        lock_user(TERRITORY, uid)
        # Суточный потолок: считаем по начисленным за захват баллам, а не по строкам
        # территорий — территория у человека одна и обновляется, а начисления в
        # истории баллов остаются и врать не могут. Под блокировкой — видим
        # начисления параллельного запроса, который закоммитился раньше.
        since = timezone.now() - timedelta(days=1)
        # Захваты, ждущие свою пробежку (п.4, territories/awards.py), тоже в счёт:
        # иначе, не присылая сводку, можно копить неоплаченные захваты без предела.
        if LoyaltyTransaction.objects.filter(
            user_id=uid, source="runnerTerritory", created_at__gte=since
        ).count() + CaptureAward.objects.filter(
            user_id=uid, status=CaptureAward.PENDING, created_at__gte=since
        ).count() >= MAX_CAPTURES_PER_DAY:
            return Response(
                {"detail": "Слишком много захватов за сутки — попробуй завтра."},
                status=429,
            )
        with connection.cursor() as cur:
            # 0a) дедуп по captureId — ДО кулдауна и любых изменений
            if capture_id:
                cur.execute(
                    "INSERT INTO processed_captures (capture_id, owner_id) "
                    "VALUES (%s, %s) ON CONFLICT (capture_id) DO NOTHING",
                    [capture_id, uid],
                )
                if cur.rowcount == 0:
                    cur.execute(
                        "SELECT ST_AsGeoJSON(geom), ST_Area(geom::geography) "
                        "FROM territories WHERE owner_id=%s",
                        [uid],
                    )
                    row = cur.fetchone()
                    if row:
                        gj, area = row
                        return Response({
                            "ok": True, "duplicate": True, "areaM2": area,
                            "geojson": json.loads(gj), "holdHoursLeft": HOLD_HOURS,
                        })
                    return Response({"ok": True, "duplicate": True, "areaM2": 0, "geojson": None})
            # 0) лениво убираем протухшие (>72ч без обновления) — освобождаем карту
            cur.execute(
                "DELETE FROM territories WHERE captured_at <= now() - make_interval(hours => %s)",
                [HOLD_HOURS],
            )
            # 1) материализуем валидный сглаженный контур ОДИН раз (переиспользуем)
            cur.execute(_CAP_SQL, [wkt, CLOSE_EPS_M, CLOSE_EPS_M, SLIVER_MIN_M2])
            cap_ewkt = (cur.fetchone() or [None])[0]
            if not cap_ewkt or "EMPTY" in cap_ewkt.upper():
                # После закрытия и фильтра осколков не осталось тела зоны —
                # это была дрожь GPS, честно отвечаем как про маленькую петлю.
                return Response(
                    {
                        "detail": "Слишком маленькая территория. "
                        "Замкни контур побольше."
                    },
                    status=400,
                )
            # 2) античит по площади контура (по полному контуру забега)
            cur.execute("SELECT ST_Area(ST_GeomFromEWKT(%s)::geography)", [cap_ewkt])
            cap_area = (cur.fetchone() or [0])[0] or 0
            if cap_area < MIN_CAPTURE_AREA_M2:
                return Response(
                    {
                        "detail": f"Слишком маленькая территория ({round(cap_area)} м²). "
                        f"Замкни контур побольше."
                    },
                    status=400,
                )
            if cap_area > MAX_CAPTURE_AREA_M2:
                return Response(
                    {"detail": "Слишком большая территория за один забег — захват отклонён."},
                    status=400,
                )
            # 3) кулдаун: не чаще раза в CAPTURE_COOLDOWN_S секунд
            cur.execute(
                "SELECT 1 FROM territories WHERE owner_id=%s "
                "AND captured_at > now() - make_interval(secs => %s)",
                [uid, CAPTURE_COOLDOWN_S],
            )
            if cur.fetchone():
                return Response(
                    {"detail": "Слишком частый захват — подожди немного."},
                    status=429,
                )
            # 4) защита 24ч (Вариант Б): из контура вычитаем ЧУЖИЕ защищённые куски
            #    (recent_captures моложе PROTECT_HOURS) → effective = что реально берём.
            cur.execute(
                "DELETE FROM recent_captures WHERE captured_at <= now() - make_interval(hours => %s)",
                [PROTECT_HOURS],
            )
            cur.execute(
                "SELECT ST_AsEWKT(ST_Multi(ST_CollectionExtract(ST_Difference("
                "  ST_GeomFromEWKT(%s),"
                "  COALESCE((SELECT ST_Union(geom) FROM recent_captures "
                "    WHERE owner_id <> %s AND captured_at > now() - make_interval(hours => %s) "
                "      AND ST_Intersects(geom, ST_GeomFromEWKT(%s))),"
                "    'SRID=4326;GEOMETRYCOLLECTION EMPTY'::geometry)"
                "),3)))",
                [cap_ewkt, uid, PROTECT_HOURS, cap_ewkt],
            )
            eff_ewkt = (cur.fetchone() or [None])[0]
            has_gain = bool(eff_ewkt) and "EMPTY" not in eff_ewkt.upper()
            # 5) перехват: срезаем у чужих ТОЛЬКО незащищённую часть (effective)
            if has_gain:
                # 5а) события «кто у кого отрезал» (Квартал 2.0, Ф6) — до среза,
                # пока пересечение ещё видно. Лента угроз клуба живёт на них.
                cur.execute(
                    "INSERT INTO territory_events (victim_owner, attacker, area_m2) "
                    "SELECT owner_id, %s, "
                    "  ST_Area(ST_Intersection(geom, ST_GeomFromEWKT(%s))::geography) "
                    "FROM territories "
                    "WHERE owner_id <> %s AND ST_Intersects(geom, ST_GeomFromEWKT(%s)) "
                    "  AND ST_Area(ST_Intersection(geom, ST_GeomFromEWKT(%s))::geography) > 1",
                    [uid, eff_ewkt, uid, eff_ewkt, eff_ewkt],
                )
                cur.execute(
                    "UPDATE territories SET geom = ST_Multi(ST_CollectionExtract("
                    "ST_Difference(geom, ST_GeomFromEWKT(%s)),3)) "
                    "WHERE owner_id <> %s AND ST_Intersects(geom, ST_GeomFromEWKT(%s))",
                    [eff_ewkt, uid, eff_ewkt],
                )
                cur.execute("DELETE FROM territories WHERE ST_IsEmpty(geom) OR ST_Area(geom)=0")
                # 6) своя территория: union с тем, что реально взяли (effective)
                cur.execute("SELECT 1 FROM territories WHERE owner_id=%s", [uid])
                if cur.fetchone():
                    cur.execute(
                        "UPDATE territories SET geom = ST_Multi(ST_CollectionExtract("
                        "ST_Union(geom, ST_GeomFromEWKT(%s)),3)), club_id=%s, captured_at=now() "
                        "WHERE owner_id=%s",
                        [eff_ewkt, club_id, uid],
                    )
                else:
                    cur.execute(
                        "INSERT INTO territories (id,owner_id,club_id,geom,captured_at) "
                        "VALUES (%s,%s,%s,ST_GeomFromEWKT(%s),now())",
                        [f"t_{secrets.token_hex(8)}", uid, club_id, eff_ewkt],
                    )
                # 6a) свежий кусок под защиту 24ч (recent_captures = что реально взяли)
                cur.execute(
                    "INSERT INTO recent_captures (owner_id, geom) VALUES (%s, ST_GeomFromEWKT(%s))",
                    [uid, eff_ewkt],
                )
            # 7) вечный личный след + расчёт НОВОЙ земли для начисления баллов.
            #    Баллы за захват = за впервые исследованные м² (рост footprint), а не
            #    плоские 50: повтор того же круга не добавляет следа → 0 баллов.
            cur.execute(
                "SELECT COALESCE(ST_Area(geom::geography),0) FROM footprints WHERE owner_id=%s",
                [uid],
            )
            fp_row = cur.fetchone()
            fp_before = (fp_row[0] if fp_row else 0) or 0
            if fp_row:
                cur.execute(
                    "UPDATE footprints SET geom = ST_Multi(ST_CollectionExtract("
                    "ST_Union(geom, ST_GeomFromEWKT(%s)),3)), updated_at=now() WHERE owner_id=%s",
                    [cap_ewkt, uid],
                )
            else:
                cur.execute(
                    "INSERT INTO footprints (owner_id,geom,updated_at) "
                    "VALUES (%s,ST_GeomFromEWKT(%s),now())",
                    [uid, cap_ewkt],
                )
            cur.execute(
                "SELECT COALESCE(ST_Area(geom::geography),0) FROM footprints WHERE owner_id=%s",
                [uid],
            )
            fp_after = (cur.fetchone() or [0])[0] or 0
            new_area_m2 = max(0.0, float(fp_after) - float(fp_before))
            territory_points = min(
                round(new_area_m2 / AREA_PER_POINT_M2), MAX_TERRITORY_POINTS
            )
            if not speed_verified:
                territory_points = 0  # скорость не проверить — баллов нет (C06)
            # 7б) захват КВАРТАЛОВ (D-74, Ф2+Ф3): кварталы, чей центр внутри петли,
            #     становятся твоими. Ф3: владение живёт до конца сезона-месяца (старое
            #     владение = свободно), домашний квартал НЕсгораем, а чужой домашний
            #     квартал не перехватывается. Эффективный владелец считается в SQL:
            #     дом → владелец навсегда; иначе — только если захвачен в этом месяце.
            #     Полигонный слой выше живёт параллельно (карта/рейтинг).
            cur.execute(
                "SELECT b.block_id, "
                "  CASE WHEN h.owner_id IS NOT NULL THEN h.owner_id "
                "       WHEN o.captured_at >= date_trunc('month', now()) THEN o.owner_id "
                "       ELSE NULL END AS eff_owner, "
                "  h.owner_id AS home_owner "
                "FROM city_blocks b "
                "LEFT JOIN block_ownership o ON o.block_id = b.block_id "
                "LEFT JOIN home_block h ON h.block_id = b.block_id "
                "WHERE ST_Contains(ST_GeomFromEWKT(%s), b.centroid)",
                [cap_ewkt],
            )
            new_blocks = []
            for block_id, eff_owner, home_owner in cur.fetchall():
                if home_owner is not None and home_owner != uid:
                    continue  # чужой домашний квартал не трогаем (Ф3)
                if eff_owner != uid:
                    new_blocks.append(block_id)
            for bid in new_blocks:
                cur.execute(
                    "INSERT INTO block_ownership (block_id, owner_id, club_id, captured_at) "
                    "VALUES (%s,%s,%s,now()) ON CONFLICT (block_id) DO UPDATE SET "
                    "owner_id=EXCLUDED.owner_id, club_id=EXCLUDED.club_id, captured_at=now()",
                    [bid, uid, club_id],
                )
            blocks_gained = len(new_blocks)
            # Моих действующих кварталов: свежие в этом сезоне ИЛИ домашний.
            cur.execute(
                "SELECT COUNT(*) FROM block_ownership o "
                "LEFT JOIN home_block h ON h.block_id = o.block_id "
                "WHERE o.owner_id=%s AND (h.owner_id=%s "
                "   OR o.captured_at >= date_trunc('month', now()))",
                [uid, uid],
            )
            blocks_total = (cur.fetchone() or [0])[0] or 0
            cur.execute(
                "SELECT ST_AsGeoJSON(geom), ST_Area(geom::geography) "
                "FROM territories WHERE owner_id=%s",
                [uid],
            )
            row = cur.fetchone()
            gj, area = (row[0], row[1]) if row else (None, 0)
            if capture_id:
                cur.execute(
                    "UPDATE processed_captures SET area_m2=%s WHERE capture_id=%s",
                    [area, capture_id],
                )
        # Очки за захват начисляет СЕРВЕР (анти-чит S-04 Phase 2), идемпотентно по
        # captureId, и только за засчитанную пробежку (решение 28.09.2026, п.4):
        # пробежки ещё нет — захват ждёт её сводку, помечена — ждёт модератора.
        # Суточный потолок баллов общий с забегами и импортом (п.1).
        award = {"points": 0, "pending": 0, "reason": "", "capped": 0}
        if capture_id and territory_points > 0:
            award = claim_capture(
                uid, capture_id, territory_points, run_hint,
                client_distance, route_m, elapsed,
            )
    # Аналитика (D-30): успешный захват территории (площадь владения после захвата).
    from analytics.models import E_TERRITORY_CAPTURED, track

    track(E_TERRITORY_CAPTURED, user_id=uid, source="kvartal", areaM2=round(area or 0))
    out = {
        "ok": True,
        "areaM2": round(area or 0),
        "points": award["points"],
        "blocksGained": blocks_gained,
        "blocksTotal": blocks_total,
        "geojson": json.loads(gj) if gj else None,
        "holdHoursLeft": HOLD_HOURS,
    }
    # Новые поля (старые клиенты их не читают).
    if award["pending"]:
        out["pointsPending"] = award["pending"]
        out["pendingReason"] = award["reason"]
    if award["capped"]:
        out.update({"dailyCapReached": True, "pointsCapped": award["capped"],
                    "capReason": award["reason"]})
    if not speed_verified:
        # Новое поле (старые клиенты его не читают): баллы не начислены, потому что
        # без времени пробежки скорость не проверить.
        out["unverified"] = True
    return Response(out)


@api_view(["GET"])
def list_territories(request):
    uid = user_id_from_request(request)
    if not uid:
        return Response({"detail": "Нет токена"}, status=401)
    my_club = _club_of(uid)
    bbox = request.query_params.get("bbox")
    # Упрощение адаптивное: на отдалённом виде сильнее (легче и быстрее),
    # на ближнем зуме (узкий bbox < ~2 км) — ~1 м, чтобы закрас ложился
    # по маршруту, а не «примерно рядом» («Идеальный маршрут», 03.09).
    tolerance = 0.00003
    if bbox:
        try:
            _a, _b, _c, _d = (float(x) for x in bbox.split(","))
            if abs(_c - _a) < 0.02 and abs(_d - _b) < 0.02:
                tolerance = 0.00001
        except Exception:
            pass  # некорректный bbox отсеет основная ветка ниже
    simplify = f"ST_SimplifyPreserveTopology(geom,{tolerance})"
    # Остаток удержания в часах (для UI «защищено ещё Nч»).
    hold_left = (
        "EXTRACT(EPOCH FROM (captured_at + make_interval(hours => %s) - now())) / 3600.0"
    )
    cols = (
        f"owner_id, club_id, ST_AsGeoJSON({simplify}), {hold_left}, "
        "EXTRACT(EPOCH FROM captured_at) * 1000"
    )
    # Активны только территории, удерживаемые < 72ч назад.
    fresh = "captured_at > now() - make_interval(hours => %s)"
    with connection.cursor() as cur:
        if bbox:
            try:
                a, b, c, d = (float(x) for x in bbox.split(","))
                if not all(math.isfinite(v) for v in (a, b, c, d)):
                    raise ValueError("not finite")
            except Exception:
                return Response({"detail": "bbox=minLng,minLat,maxLng,maxLat"}, status=400)
            cur.execute(
                f"SELECT {cols} FROM territories "
                f"WHERE {fresh} AND geom && ST_MakeEnvelope(%s,%s,%s,%s,4326)",
                [HOLD_HOURS, HOLD_HOURS, a, b, c, d],
            )
        else:
            cur.execute(
                f"SELECT {cols} FROM territories WHERE {fresh}",
                [HOLD_HOURS, HOLD_HOURS],
            )
        rows = cur.fetchall()
    # Имена владельцев — публичная часть паспорта квартала (Ф2): как в рейтинге.
    from common.people import names_of

    names = names_of([r[0] for r in rows])
    out = []
    for owner_id, club_id, gj, hours_left, captured_ms in rows:
        rel = "mine" if owner_id == uid else (
            "club" if club_id and club_id == my_club else "enemy"
        )
        out.append(
            {
                "ownerId": owner_id,
                "ownerName": names.get(owner_id, "Бегун"),
                "clubId": club_id,
                "rel": rel,
                "holdHoursLeft": round(max(0.0, float(hours_left or 0)), 1),
                "capturedAtMs": int(captured_ms or 0),
                "geojson": json.loads(gj),
            }
        )
    return Response({"territories": out})


@api_view(["GET"])
def footprint(request):
    """Вечный личный след: вся когда-либо пробежанная площадь (не уменьшается).
    Для профиля — «исследовано N км²». geojson — упрощённый контур для будущей heatmap."""
    uid = user_id_from_request(request)
    if not uid:
        return Response({"detail": "Нет токена"}, status=401)
    with connection.cursor() as cur:
        cur.execute(
            "SELECT ST_Area(geom::geography), "
            "ST_AsGeoJSON(ST_SimplifyPreserveTopology(geom,0.00005)) "
            "FROM footprints WHERE owner_id=%s",
            [uid],
        )
        row = cur.fetchone()
    if not row:
        return Response({"areaM2": 0, "geojson": None})
    area, gj = row
    return Response(
        {"areaM2": round(area or 0), "geojson": json.loads(gj) if gj else None}
    )
