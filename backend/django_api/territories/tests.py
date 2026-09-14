"""Регрессии начисления за захват территории (S-04 Phase 2): сервер +50, идемпотентно.
+ плановая чистка протухших зон/защит (доводка Квартала)."""
from django.core.management import call_command
from django.db import connection
from django.test import TestCase, override_settings

from common.testutils import ApiTestCase

# Прямоугольник ~5800 м² у Якутска (> MIN_CAPTURE_AREA_M2, < MAX).
_POLY = [[62.000, 129.700], [62.001, 129.700], [62.001, 129.701], [62.000, 129.701]]


class TerritoryAwardTests(ApiTestCase):
    phone = "+79990002003"

    def test_capture_awards_server_side(self):
        r = self.api_post(
            "/v1/territories/capture", {"points": _POLY, "captureId": "capA"}
        ).json()
        self.assertTrue(r["ok"])
        # Баллы = за новый след (~площадь/100). Для ~5800 м² это ~55-60.
        self.assertEqual(self.balance(), r["points"])
        self.assertGreaterEqual(self.balance(), 50)
        self.assertLessEqual(self.balance(), 62)

    def test_duplicate_capture_no_double(self):
        body = {"points": _POLY, "captureId": "capA"}
        self.api_post("/v1/territories/capture", body)
        awarded = self.balance()
        self.assertGreater(awarded, 0)
        r = self.api_post("/v1/territories/capture", body).json()
        self.assertTrue(r["duplicate"])
        self.assertEqual(self.balance(), awarded)

    def test_speed_cheat_rejected(self):
        r = self.api_post(
            "/v1/territories/capture",
            {"points": _POLY, "captureId": "capFast",
             "distanceMeters": 5000, "elapsedSeconds": 10},
        )
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.balance(), 0)

    def test_client_cannot_mint_runner_territory(self):
        r = self.api_post(
            "/v1/loyalty/transactions",
            {"amount": 9999, "source": "runnerTerritory"},
        )
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.balance(), 0)

    def test_rerun_same_ground_awards_nothing(self):
        # Первый захват — баллы за впервые исследованную землю.
        self.api_post("/v1/territories/capture", {"points": _POLY, "captureId": "c1"})
        first = self.balance()
        self.assertGreater(first, 0)
        # Обходим кулдаун и защиту 24ч, состарив метки времени.
        with connection.cursor() as cur:
            cur.execute("UPDATE territories SET captured_at = now() - interval '1 hour'")
            cur.execute("UPDATE recent_captures SET captured_at = now() - interval '2 days'")
        # Тот же контур снова — нового следа нет → 0 баллов (ферма закрыта).
        r = self.api_post(
            "/v1/territories/capture", {"points": _POLY, "captureId": "c2"}
        ).json()
        self.assertTrue(r["ok"])
        self.assertEqual(r["points"], 0)
        self.assertEqual(self.balance(), first)


class TerritoryViewTests(ApiTestCase):
    """Чтение карты территорий и вечного следа: GET /territories (rel mine/enemy,
    holdHoursLeft) и GET /footprint (накопление площади). Идём через реальный capture."""
    phone = "+79990002005"

    def _capture(self, capture_id="capV"):
        return self.api_post(
            "/v1/territories/capture", {"points": _POLY, "captureId": capture_id}
        )

    def test_captured_territory_listed_as_mine(self):
        self._capture()
        terr = self.api_get("/v1/territories").json()["territories"]
        self.assertEqual(len(terr), 1)
        self.assertEqual(terr[0]["rel"], "mine")
        self.assertGreater(terr[0]["holdHoursLeft"], 0)  # только что взял — защита идёт

    def test_other_owner_shows_as_enemy(self):
        # Чужая свежая территория (прямой INSERT, далеко от моей) → для меня «enemy».
        with connection.cursor() as cur:
            cur.execute(
                "INSERT INTO territories (id, owner_id, geom, captured_at) VALUES "
                "('t_enemy','u_enemy',"
                "ST_GeomFromText('MULTIPOLYGON(((10 10,10 11,11 11,11 10,10 10)))',4326), now())"
            )
        rels = [t["rel"] for t in self.api_get("/v1/territories").json()["territories"]]
        self.assertEqual(rels, ["enemy"])

    def test_footprint_accumulates_after_capture(self):
        self.assertEqual(self.api_get("/v1/footprint").json()["areaM2"], 0)  # до забега
        self._capture()
        fp = self.api_get("/v1/footprint").json()
        self.assertGreater(fp["areaM2"], 0)  # вечный след появился
        self.assertIsNotNone(fp["geojson"])

    def test_too_few_points_rejected(self):
        r = self.api_post("/v1/territories/capture", {"points": _POLY[:2]})
        self.assertEqual(r.status_code, 400)

    def test_list_and_footprint_require_auth(self):
        self.assertEqual(self.client.get("/v1/territories").status_code, 401)
        self.assertEqual(self.client.get("/v1/footprint").status_code, 401)


class TerritoryCleanupTests(TestCase):
    """Команда cleanup_territories удаляет ТОЛЬКО протухшее (>7д зоны, >24ч защита,
    >30д записи идемпотентности), свежее не трогает."""

    _G = "ST_GeomFromText('MULTIPOLYGON(((0 0,0 1,1 1,1 0,0 0)))',4326)"

    def test_cleanup_removes_expired_only(self):
        with connection.cursor() as cur:
            cur.execute(
                "INSERT INTO territories (id, owner_id, geom, captured_at) "
                f"VALUES ('t_old','o_old',{self._G}, now() - interval '8 days')"
            )
            cur.execute(
                "INSERT INTO territories (id, owner_id, geom, captured_at) "
                f"VALUES ('t_new','o_new',{self._G}, now())"
            )
            cur.execute(
                "INSERT INTO recent_captures (owner_id, geom, captured_at) "
                f"VALUES ('o_old',{self._G}, now() - interval '2 days')"
            )
            cur.execute(
                "INSERT INTO recent_captures (owner_id, geom, captured_at) "
                f"VALUES ('o_new',{self._G}, now())"
            )
            # Идемпотентность захвата: старую (>30д) чистим, свежую храним.
            cur.execute(
                "INSERT INTO processed_captures (capture_id, owner_id, created_at) "
                "VALUES ('cap_old','o_old', now() - interval '40 days')"
            )
            cur.execute(
                "INSERT INTO processed_captures (capture_id, owner_id, created_at) "
                "VALUES ('cap_new','o_new', now())"
            )
        call_command("cleanup_territories")
        with connection.cursor() as cur:
            cur.execute("SELECT owner_id FROM territories")
            rows = [r[0] for r in cur.fetchall()]
            self.assertEqual(rows, ["o_new"])  # протухшая удалена, свежая осталась
            cur.execute("SELECT count(*) FROM recent_captures")
            self.assertEqual(cur.fetchone()[0], 1)  # истёкшая защита удалена
            cur.execute("SELECT capture_id FROM processed_captures")
            self.assertEqual([r[0] for r in cur.fetchall()], ["cap_new"])  # старая идемпот. удалена


@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
class TerritoryCleanupTaskTests(TestCase):
    """Чистка вынесена в Celery-задачу beat (D-07). EAGER → .delay() выполняет команду
    синхронно; проверяем, что beat-обёртка удаляет ровно протухшее."""

    _G = "ST_GeomFromText('MULTIPOLYGON(((0 0,0 1,1 1,1 0,0 0)))',4326)"

    def test_cleanup_task_removes_expired(self):
        from territories.tasks import cleanup_expired_territories

        with connection.cursor() as cur:
            cur.execute(
                "INSERT INTO territories (id, owner_id, geom, captured_at) "
                f"VALUES ('t_old','o_old',{self._G}, now() - interval '8 days')"
            )
            cur.execute(
                "INSERT INTO territories (id, owner_id, geom, captured_at) "
                f"VALUES ('t_new','o_new',{self._G}, now())"
            )
        cleanup_expired_territories.delay()  # EAGER → команда выполнится inline
        with connection.cursor() as cur:
            cur.execute("SELECT owner_id FROM territories")
            self.assertEqual([r[0] for r in cur.fetchall()], ["o_new"])
