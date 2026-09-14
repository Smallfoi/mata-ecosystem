"""Городские кварталы (D-74, Ф1): загрузка seed и отдача карты /v1/blocks."""
from django.core.management import call_command
from django.db import connection

from common.testutils import ApiTestCase


def _count():
    with connection.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM city_blocks")
        return cur.fetchone()[0]


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
