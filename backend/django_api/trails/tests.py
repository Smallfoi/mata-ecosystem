"""Тропы: сверка трека, попытки, доски, удаление треков (D-60).

Главное, что здесь проверяется, — цена ошибки в обе стороны. Засчитать лишнее
значит пустить в таблицу того, кто проехал мимо на велосипеде. Не засчитать
настоящее значит сделать вид, что человек не бежал; второй раз он не проверит.
"""
from datetime import timedelta

from django.db import connection
from django.utils import timezone

from common.testutils import ApiTestCase
from league.models import RunnerProfile
from trails import matching
from trails.models import PendingTrack, Trail, TrailAttempt
from trails.tasks import cleanup_tracks

# Прямой отрезок в Якутске. Шаг между точками ~100 м: на широте 62° градус
# долготы это примерно 52 км, поэтому 0.002° и дают сотню метров. Меньше брать
# нельзя — при допуске в 40 м соседние точки накрывали бы друг друга, и проверка
# «бежал по тропе» перестала бы что-либо проверять.
BASE_LAT = 62.0280
BASE_LON = 129.7320

NOW_MS = int(timezone.now().timestamp() * 1000)


def line(n=10, step_lon=0.002, lat=BASE_LAT, lon=BASE_LON):
    return [[lat, lon + step_lon * i] for i in range(n)]


def track_along(points, start_ms=None, step_s=30, lead=0, tail=0):
    """Трек, который идёт по линии. lead/tail — точки до и после тропы:
    так выглядит настоящий забег, где тропа — только часть маршрута."""
    start_ms = NOW_MS if start_ms is None else start_ms
    pts = []
    t = start_ms
    for i in range(lead):
        pts.append([points[0][0], points[0][1] - 0.0004 * (lead - i), t])
        t += step_s * 1000
    for p in points:
        pts.append([p[0], p[1], t])
        t += step_s * 1000
    for i in range(tail):
        pts.append([points[-1][0], points[-1][1] + 0.0004 * (i + 1), t])
        t += step_s * 1000
    return pts


class MatchingTests(ApiTestCase):
    """Чистая проверка алгоритма — без базы и HTTP."""

    phone = "+79990009201"

    def test_track_along_trail_is_a_pass(self):
        trail = line()
        hit = matching.match(trail, track_along(trail, lead=3, tail=3))
        self.assertIsNotNone(hit)
        self.assertGreater(hit["durationS"], 0)

    def test_time_counts_from_entry_to_exit(self):
        """Время тропы — от входа до выхода, а не по всему забегу."""
        trail = line(n=5)
        tr = track_along(trail, step_s=60, lead=4, tail=4)
        hit = matching.match(trail, tr)
        # Пять точек тропы = четыре промежутка по минуте.
        self.assertEqual(hit["durationS"], 4 * 60)

    def test_parallel_street_is_not_a_pass(self):
        """Бежал по соседней улице — тропа не засчитана."""
        trail = line()
        aside = [[p[0] + 0.0025, p[1]] for p in trail]   # ~280 м в стороне
        self.assertIsNone(matching.match(trail, track_along(aside)))

    def test_cut_corner_is_not_a_pass(self):
        """Срезал середину — покрытие ниже порога, попытки нет."""
        trail = line(n=12)
        half = trail[:3] + trail[-3:]
        self.assertIsNone(matching.match(trail, track_along(half)))

    def test_wrong_direction_is_not_a_pass(self):
        trail = line()
        self.assertIsNone(matching.match(trail, track_along(list(reversed(trail)))))

    def test_car_speed_rejected(self):
        """Тропа «пройдена» за секунды — это не бег."""
        trail = line(n=10)
        self.assertIsNone(matching.match(trail, track_along(trail, step_s=0.2)))

    def test_simplify_keeps_ends(self):
        pts = line(n=40, step_lon=0.0001)   # очень плотная линия: точки через ~5 м
        s = matching.simplify(pts)
        self.assertLess(len(s), len(pts))
        self.assertEqual(s[0], pts[0])
        self.assertEqual(s[-1], pts[-1])


class TrailApiTests(ApiTestCase):
    phone = "+79990009202"

    def _trail(self, name="Круг у Талого", points=None, owner=None):
        pts = points or line()
        min_lat, max_lat, min_lon, max_lon = matching.bbox(pts)
        return Trail.objects.create(
            id=f"t_{name[:6]}_{Trail.objects.count()}",
            name=name,
            points=pts,
            length_m=matching.line_length_m(pts),
            min_lat=min_lat, max_lat=max_lat, min_lon=min_lon, max_lon=max_lon,
            created_by=owner or "",
        )

    # ── приём трека ─────────────────────────────────────────────────────────

    def test_track_creates_attempt(self):
        trail = self._trail()
        r = self.api_post("/v1/runs/track", {
            "runId": "run_t1",
            "points": track_along(trail.points, lead=2, tail=2),
        })
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()["attempts"]), 1)
        self.assertEqual(TrailAttempt.objects.filter(trail_id=trail.id).count(), 1)

    def test_track_is_stored_only_temporarily(self):
        """Трек сохраняется — но как материал для разбора, а не навсегда (D-60)."""
        trail = self._trail()
        self.api_post("/v1/runs/track", {"runId": "run_t2", "points": track_along(trail.points)})
        kept = PendingTrack.objects.get(run_id="run_t2")
        self.assertEqual(kept.user_id, self.uid)

        kept.received_at = timezone.now() - timedelta(days=15)
        kept.save()
        cleanup_tracks()
        self.assertFalse(PendingTrack.objects.filter(run_id="run_t2").exists())
        # Попытка остаётся: удаляем маршрут, а не результат.
        self.assertTrue(TrailAttempt.objects.filter(run_id="run_t2").exists())

    def test_track_not_accepted_when_trails_disabled(self):
        """Выключил участие — трек не уходит вовсе, даже на 14 дней."""
        RunnerProfile.objects.update_or_create(
            user_id=self.uid, defaults={"trails_enabled": False}
        )
        trail = self._trail()
        r = self.api_post("/v1/runs/track", {"runId": "run_t3", "points": track_along(trail.points)})
        self.assertEqual(r.json()["skipped"], "trailsDisabled")
        self.assertFalse(PendingTrack.objects.filter(run_id="run_t3").exists())
        self.assertEqual(TrailAttempt.objects.count(), 0)

    def test_same_run_does_not_double_count(self):
        trail = self._trail()
        body = {"runId": "run_t4", "points": track_along(trail.points)}
        self.api_post("/v1/runs/track", body)
        self.api_post("/v1/runs/track", body)
        self.assertEqual(TrailAttempt.objects.filter(trail_id=trail.id).count(), 1)

    def test_track_requires_auth(self):
        self.assertEqual(self.client.post("/v1/runs/track").status_code, 401)

    # ── резервная копия треков (D-86) ───────────────────────────────────────

    def test_backup_keeps_track_past_retention(self):
        """Включён бэкап — трек не удаляется по 14-дневному правилу (D-86)."""
        RunnerProfile.objects.update_or_create(
            user_id=self.uid, defaults={"track_backup": True}
        )
        trail = self._trail()
        self.api_post("/v1/runs/track", {"runId": "run_bk1", "points": track_along(trail.points)})
        kept = PendingTrack.objects.get(run_id="run_bk1")
        kept.received_at = timezone.now() - timedelta(days=40)
        kept.save()
        cleanup_tracks()
        self.assertTrue(PendingTrack.objects.filter(run_id="run_bk1").exists())

    def test_backup_stores_track_even_when_trails_disabled(self):
        """Тропы выключены, но бэкап включён — трек хранится (только для владельца),
        со тропами не сверяется."""
        RunnerProfile.objects.update_or_create(
            user_id=self.uid,
            defaults={"trails_enabled": False, "track_backup": True},
        )
        trail = self._trail()
        r = self.api_post("/v1/runs/track", {"runId": "run_bk2", "points": track_along(trail.points)})
        self.assertEqual(r.json()["skipped"], "trailsDisabledBackup")
        self.assertTrue(PendingTrack.objects.filter(run_id="run_bk2").exists())
        self.assertEqual(TrailAttempt.objects.count(), 0)  # сверки нет

    def test_get_track_returns_own_track_only(self):
        """Владелец забирает свой трек обратно; чужой не отдаётся (D-86)."""
        trail = self._trail()
        self.api_post("/v1/runs/track", {"runId": "run_bk3", "points": track_along(trail.points)})
        r = self.api_get("/v1/runs/run_bk3/track")
        self.assertEqual(r.status_code, 200)
        self.assertGreaterEqual(len(r.json()["points"]), 2)
        # Чужой трек не виден: тот же run_id у другого пользователя не отдаём.
        PendingTrack.objects.create(
            run_id="run_alien", user_id="u_someone_else", points=[[1, 2, 0], [3, 4, 1]]
        )
        self.assertEqual(self.api_get("/v1/runs/run_alien/track").json()["points"], [])

    def test_get_track_empty_when_none(self):
        self.assertEqual(self.api_get("/v1/runs/run_missing/track").json()["points"], [])

    def test_get_track_requires_auth(self):
        self.assertEqual(self.client.get("/v1/runs/run_x/track").status_code, 401)

    # ── создание троп ───────────────────────────────────────────────────────

    def test_create_trail(self):
        r = self.api_post("/v1/trails/", {"name": "Набережная", "points": line(n=12)})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["createdByMe"])
        self.assertGreater(r.json()["lengthM"], 200)

    def test_too_short_trail_rejected(self):
        r = self.api_post("/v1/trails/", {"name": "Перекрёсток", "points": line(n=2, step_lon=0.0005)})
        self.assertEqual(r.status_code, 400)

    def test_trail_needs_name(self):
        self.assertEqual(self.api_post("/v1/trails/", {"points": line()}).status_code, 400)

    def test_list_marks_mine(self):
        trail = self._trail(owner=self.uid)
        self.api_post("/v1/runs/track", {"runId": "run_t5", "points": track_along(trail.points)})
        items = self.api_get("/v1/trails/").json()["items"]
        row = next(i for i in items if i["id"] == trail.id)
        self.assertTrue(row["createdByMe"])
        self.assertTrue(row["attemptedByMe"])

    def test_list_filters_by_location(self):
        near = self._trail(name="Рядом")
        self._trail(name="Далеко", points=line(lat=55.75, lon=37.62))
        items = self.api_get(f"/v1/trails/?lat={BASE_LAT}&lon={BASE_LON}").json()["items"]
        names = [i["name"] for i in items]
        self.assertIn(near.name, names)
        self.assertNotIn("Далеко", names)

    # ── доски ───────────────────────────────────────────────────────────────

    def test_fastest_board(self):
        trail = self._trail()
        self.api_post("/v1/runs/track", {"runId": "r1", "points": track_along(trail.points, step_s=40)})
        body = self.api_get(f"/v1/trails/{trail.id}/boards?board=fastest").json()
        self.assertEqual(body["me"]["place"], 1)
        self.assertEqual(body["top"][0]["isMe"], True)

    def test_my_progress_board_lists_attempts(self):
        trail = self._trail()
        self.api_post("/v1/runs/track", {"runId": "r2", "points": track_along(trail.points, step_s=40)})
        self.api_post("/v1/runs/track", {
            "runId": "r3",
            "points": track_along(trail.points, start_ms=NOW_MS + 3_600_000, step_s=30),
        })
        body = self.api_get(f"/v1/trails/{trail.id}/boards?board=mine").json()
        self.assertEqual(body["me"]["attempts"], 2)
        self.assertEqual(body["me"]["best"], 9 * 30)   # лучшая из двух попыток

    def test_frequent_board_counts_passes(self):
        trail = self._trail()
        for i in range(3):
            self.api_post("/v1/runs/track", {
                "runId": f"rf{i}",
                "points": track_along(trail.points, start_ms=NOW_MS - i * 86_400_000),
            })
        body = self.api_get(f"/v1/trails/{trail.id}/boards?board=frequent").json()
        self.assertEqual(body["me"]["value"], 3)
        self.assertEqual(body["unit"], "попыток")

    def test_mylane_board_needs_profile(self):
        trail = self._trail()
        self.api_post("/v1/runs/track", {"runId": "r4", "points": track_along(trail.points)})
        body = self.api_get(f"/v1/trails/{trail.id}/boards?board=mylane").json()
        self.assertTrue(body["needsProfile"])

    def test_boards_404_for_unknown_trail(self):
        self.assertEqual(self.api_get("/v1/trails/nope/boards").status_code, 404)


class ExploreFootprintTests(ApiTestCase):
    """Исследование карты (D-74, вариант A): любой забег растит вечный след
    (footprints) — по нему в приложении открывается «туман». Трек не обязан
    совпасть с тропой: свободный бег тоже открывает город."""

    phone = "+79990009203"

    def _footprint_area(self):
        with connection.cursor() as cur:
            cur.execute(
                "SELECT COALESCE(ST_Area(geom::geography),0) "
                "FROM footprints WHERE owner_id=%s",
                [self.uid],
            )
            row = cur.fetchone()
        return float(row[0]) if row else 0.0

    def test_free_run_grows_footprint(self):
        """Свободный бег без единой тропы всё равно открывает карту."""
        self.assertEqual(self._footprint_area(), 0.0)
        r = self.api_post("/v1/runs/track", {
            "runId": "fp_1",
            "points": track_along(line(n=10)),
        })
        self.assertEqual(r.status_code, 200)
        self.assertGreater(self._footprint_area(), 0.0)

    def test_run_elsewhere_expands_footprint(self):
        """Забег в новом районе увеличивает исследованную площадь."""
        self.api_post("/v1/runs/track",
                      {"runId": "fp_2", "points": track_along(line(n=10))})
        after_first = self._footprint_area()
        far = line(n=10, lat=BASE_LAT + 0.05, lon=BASE_LON + 0.05)
        self.api_post("/v1/runs/track",
                      {"runId": "fp_3", "points": track_along(far)})
        self.assertGreater(self._footprint_area(), after_first)

    def test_rerun_same_route_does_not_shrink(self):
        """Повтор того же маршрута не уменьшает след — union монотонен."""
        self.api_post("/v1/runs/track",
                      {"runId": "fp_4", "points": track_along(line(n=10))})
        area1 = self._footprint_area()
        self.api_post("/v1/runs/track",
                      {"runId": "fp_5", "points": track_along(line(n=10))})
        self.assertGreaterEqual(self._footprint_area(), area1 - 1.0)

    def test_trails_disabled_no_footprint(self):
        """Выключил участие в тропах — трек не приходит, след не растёт."""
        RunnerProfile.objects.update_or_create(
            user_id=self.uid, defaults={"trails_enabled": False}
        )
        self.api_post("/v1/runs/track",
                      {"runId": "fp_6", "points": track_along(line(n=10))})
        self.assertEqual(self._footprint_area(), 0.0)
