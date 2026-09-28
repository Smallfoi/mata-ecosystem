"""Городские кварталы (D-74, Ф1): загрузка seed и отдача карты /v1/blocks."""
from django.core.management import call_command
from django.db import connection

from common.testutils import ApiTestCase


def _count():
    with connection.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM city_blocks")
        return cur.fetchone()[0]


def _central_block():
    """Квартал у пл. Ленина + его центр (block_id, lng, lat) — для тест-петли захвата."""
    with connection.cursor() as cur:
        cur.execute(
            "SELECT block_id, ST_X(centroid), ST_Y(centroid) FROM city_blocks "
            "ORDER BY centroid <-> ST_SetSRID(ST_MakePoint(129.732, 62.027), 4326) LIMIT 1"
        )
        return cur.fetchone()


class BlocksTests(ApiTestCase):
    phone = "+79990002050"

    @classmethod
    def setUpTestData(cls):
        call_command("load_blocks")  # реальные ~632 квартала Якутска из seed

    def test_seed_loaded(self):
        self.assertGreaterEqual(_count(), 600)

    def test_districts_present(self):
        with connection.cursor() as cur:
            cur.execute(
                "SELECT COUNT(DISTINCT district) FROM city_blocks WHERE district IS NOT NULL"
            )
            self.assertGreaterEqual(cur.fetchone()[0], 5)

    def test_load_is_idempotent(self):
        before = _count()
        call_command("load_blocks")
        self.assertEqual(_count(), before)

    def test_list_requires_auth(self):
        self.assertEqual(self.client.get("/v1/blocks").status_code, 401)

    def test_list_returns_blocks(self):
        r = self.api_get("/v1/blocks").json()
        self.assertGreaterEqual(len(r["blocks"]), 600)
        b = r["blocks"][0]
        self.assertIn("blockId", b)
        self.assertEqual(b["rel"], "free")
        self.assertEqual(b["geojson"]["type"], "Polygon")

    def test_bbox_filters_subset(self):
        allb = len(self.api_get("/v1/blocks").json()["blocks"])
        sub = len(
            self.api_get("/v1/blocks?bbox=129.72,62.02,129.74,62.035").json()["blocks"]
        )
        self.assertGreater(sub, 0)
        self.assertLess(sub, allb)

    def test_bad_bbox_returns_400(self):
        self.assertEqual(self.api_get("/v1/blocks?bbox=abc").status_code, 400)


class BlockCaptureTests(ApiTestCase):
    """Захват по кварталам (D-74, Ф2): петля метит кварталы с центром внутри."""

    phone = "+79990002060"

    @classmethod
    def setUpTestData(cls):
        call_command("load_blocks")

    def _box(self):
        bid, lng, lat = _central_block()
        d = 0.0006  # ~130x60 м вокруг центра квартала — центр гарантированно внутри
        return bid, [[lat - d, lng - d], [lat + d, lng - d], [lat + d, lng + d], [lat - d, lng + d]]

    def test_capture_marks_blocks_mine(self):
        bid, box = self._box()
        r = self.api_post(
            "/v1/territories/capture", {"points": box, "captureId": "b1"}
        ).json()
        self.assertTrue(r["ok"])
        self.assertGreaterEqual(r["blocksGained"], 1)
        self.assertEqual(r["blocksTotal"], r["blocksGained"])
        blocks = self.api_get("/v1/blocks").json()["blocks"]
        mine = {b["blockId"] for b in blocks if b["rel"] == "mine"}
        self.assertIn(bid, mine)
        self.assertEqual(len(mine), r["blocksGained"])

    def test_recapture_same_ground_no_new(self):
        _, box = self._box()
        self.api_post("/v1/territories/capture", {"points": box, "captureId": "b1"})
        with connection.cursor() as cur:  # обойти кулдаун полигонного слоя
            cur.execute("UPDATE territories SET captured_at = now() - interval '1 hour'")
            cur.execute("UPDATE recent_captures SET captured_at = now() - interval '2 days'")
        r = self.api_post(
            "/v1/territories/capture", {"points": box, "captureId": "b2"}
        ).json()
        self.assertTrue(r["ok"])
        self.assertEqual(r["blocksGained"], 0)

    def test_enemy_sees_other_owner(self):
        bid, box = self._box()
        self.api_post("/v1/territories/capture", {"points": box, "captureId": "b1"})
        other = self.new_user("+79990002061")
        blocks = self.api_get("/v1/blocks", token=other).json()["blocks"]
        row = next(b for b in blocks if b["blockId"] == bid)
        self.assertEqual(row["rel"], "enemy")
        self.assertEqual(row["ownerId"], self.uid)
        self.assertIsNotNone(row["ownerName"])


class BlockSeasonHomeTests(ApiTestCase):
    """Ф3 (D-74): сезон-месяц + несгораемый домашний квартал + приватность."""

    phone = "+79990002070"

    @classmethod
    def setUpTestData(cls):
        call_command("load_blocks")

    def _box(self):
        bid, lng, lat = _central_block()
        d = 0.0006
        return bid, [[lat - d, lng - d], [lat + d, lng - d], [lat + d, lng + d], [lat - d, lng + d]]

    def _row(self, blocks, bid):
        return next((b for b in blocks if b["blockId"] == bid), None)

    def test_set_home_marks_mine_and_home(self):
        bid, _ = self._box()
        r = self.api_post("/v1/blocks/home", {"blockId": bid}).json()
        self.assertTrue(r["ok"])
        row = self._row(self.api_get("/v1/blocks").json()["blocks"], bid)
        self.assertEqual(row["rel"], "mine")
        self.assertTrue(row["home"])

    def test_home_not_intercepted_and_anonymous_to_others(self):
        bid, box = self._box()
        self.api_post("/v1/blocks/home", {"blockId": bid})
        other = self.new_user("+79990002071")
        self.api_post(
            "/v1/territories/capture", {"points": box, "captureId": "h1"}, token=other
        )
        row = self._row(self.api_get("/v1/blocks", token=other).json()["blocks"], bid)
        self.assertEqual(row["rel"], "enemy")   # виден как занятый
        self.assertIsNone(row["ownerId"])       # но аноним (privacy дома)
        self.assertIsNone(row["ownerName"])
        mine = self._row(self.api_get("/v1/blocks").json()["blocks"], bid)
        self.assertEqual(mine["rel"], "mine")
        self.assertTrue(mine["home"])

    def test_season_reset_frees_stale_ownership(self):
        _bid, box = self._box()
        self.api_post("/v1/territories/capture", {"points": box, "captureId": "s1"})
        with connection.cursor() as cur:  # состарить владение на прошлый сезон
            cur.execute(
                "UPDATE block_ownership SET captured_at = "
                "date_trunc('month', now()) - interval '5 days'"
            )
        blocks = self.api_get("/v1/blocks").json()["blocks"]
        self.assertEqual([b for b in blocks if b["rel"] == "mine"], [])

    def test_set_home_rejected_on_enemy_block(self):
        bid, box = self._box()
        other = self.new_user("+79990002072")
        self.api_post(
            "/v1/territories/capture", {"points": box, "captureId": "e1"}, token=other
        )
        self.assertEqual(
            self.api_post("/v1/blocks/home", {"blockId": bid}).status_code, 409
        )

class NearestBlockTests(ApiTestCase):
    """Подсказка «обеги этот круг» (D-74): один ближайший СВОБОДНЫЙ квартал."""

    phone = "+79990002051"

    # Площадь Ленина — центр Якутска, кварталы вокруг точно есть.
    LAT, LON = 62.027, 129.732

    @classmethod
    def setUpTestData(cls):
        call_command("load_blocks")

    def _nearest(self, lat=None, lon=None):
        return self.api_get(
            f"/v1/blocks/nearest?lat={lat or self.LAT}&lon={lon or self.LON}"
        )

    def test_requires_auth(self):
        self.assertEqual(
            self.client.get(f"/v1/blocks/nearest?lat={self.LAT}&lon={self.LON}").status_code,
            401,
        )

    def test_requires_coordinates(self):
        self.assertEqual(self.api_get("/v1/blocks/nearest").status_code, 400)
        self.assertEqual(self.api_get("/v1/blocks/nearest?lat=62&lon=nope").status_code, 400)
        self.assertEqual(self.api_get("/v1/blocks/nearest?lat=999&lon=0").status_code, 400)

    def test_returns_runnable_loop(self):
        """Подсказка бесполезна без длины круга: человек решает по ней, побежит ли."""
        b = self._nearest().json()["block"]
        self.assertIsNotNone(b)
        self.assertEqual(b["rel"], "free")
        self.assertGreaterEqual(b["loopMeters"], 300)
        self.assertLessEqual(b["loopMeters"], 5000)
        self.assertEqual(b["geojson"]["type"], "Polygon")

    def test_suggests_the_closest_one(self):
        """Ближайший — значит ближайший: дальше него свободных быть не должно."""
        b = self._nearest().json()["block"]
        with connection.cursor() as cur:
            cur.execute(
                "SELECT MIN(ST_Distance(geom::geography, "
                "ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography)) FROM city_blocks "
                "WHERE ST_Perimeter(geom::geography) BETWEEN 300 AND 5000",
                [self.LON, self.LAT],
            )
            closest = cur.fetchone()[0]
        self.assertAlmostEqual(b["distanceMeters"], round(closest), delta=1)

    def test_owned_block_is_not_suggested(self):
        """Свой квартал не предлагаем: повтор не даёт баллов, бежать туда незачем."""
        first = self._nearest().json()["block"]
        with connection.cursor() as cur:
            cur.execute(
                "INSERT INTO block_ownership (block_id, owner_id, captured_at) "
                "VALUES (%s,%s,now())",
                [first["blockId"], self.uid],
            )
        again = self._nearest().json()["block"]
        self.assertNotEqual(again["blockId"], first["blockId"])

    def test_far_away_gets_no_suggestion(self):
        """В сотне километров от города подсказывать нечего — и это не ошибка."""
        r = self._nearest(lat=60.0, lon=120.0)
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.json()["block"])

