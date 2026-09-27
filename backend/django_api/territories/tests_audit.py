"""Аудит 27.09.2026, D04: некорректный запрос захвата — понятный 400 без изменений
в базе, а не 500. Форма, которую шлёт mata_kvartal (territory_provider.dart):
{"points": [[lat, lng], ...], "captureId": str, "distanceMeters"?, "elapsedSeconds"?}.
"""
from django.db import connection

from common.testutils import ApiTestCase
from loyalty.models import LoyaltyTransaction

_POLY = [[62.000, 129.700], [62.001, 129.700], [62.001, 129.701], [62.000, 129.701]]


class TerritoryInputTests(ApiTestCase):
    phone = "+79990009885"

    def _territories(self):
        with connection.cursor() as cur:
            cur.execute("SELECT count(*) FROM territories WHERE owner_id=%s", [self.uid])
            return cur.fetchone()[0]

    def test_bad_points_are_400(self):
        cases = [
            "abcd",
            {"a": 1, "b": 2, "c": 3},
            [[62.0, "x"], [62.001, 129.7], [62.001, 129.701]],
            [[62.0], [62.001, 129.7], [62.001, 129.701]],
            [{"lat": 62}, [62.001, 129.7], [62.001, 129.701], [62.0, 129.701]],
            [["nan", 129.7], [62.001, 129.7], [62.001, 129.701]],
            [["Infinity", 129.7], [62.001, 129.7], [62.001, 129.701]],
            [[95.0, 129.7], [62.001, 129.7], [62.001, 129.701]],
            [[True, 129.7], [62.001, 129.7], [62.001, 129.701]],
        ]
        for i, pts in enumerate(cases):
            r = self.api_post("/v1/territories/capture",
                              {"points": pts, "captureId": f"bad{i}"})
            self.assertEqual(r.status_code, 400, pts)
        self.assertEqual(self._territories(), 0)
        self.assertFalse(LoyaltyTransaction.objects.filter(user_id=self.uid).exists())

    def test_non_dict_body_is_400(self):
        r = self.client.post(
            "/v1/territories/capture", data="[1,2,3]", content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.token}",
        )
        self.assertEqual(r.status_code, 400)

    def test_bad_bbox_is_400(self):
        r = self.api_get("/v1/territories?bbox=nan,nan,nan,nan")
        self.assertEqual(r.status_code, 400)

    def test_client_shape_still_works(self):
        r = self.api_post("/v1/territories/capture", {
            "points": _POLY, "captureId": "okA",
            "distanceMeters": 450.5, "elapsedSeconds": 240,
        })
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])

    def test_garbage_speed_fields_are_still_ignored(self):
        """Как и раньше: нечисловые дистанция/время не блокируют законный захват."""
        r = self.api_post("/v1/territories/capture", {
            "points": _POLY, "captureId": "okB",
            "distanceMeters": "?", "elapsedSeconds": "nan",
        })
        self.assertEqual(r.status_code, 200)
