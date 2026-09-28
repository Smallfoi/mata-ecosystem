"""Аудит 27.09.2026, C06: неполные данные не отключают проверку скорости захвата.

Было: проверка скорости срабатывала, только если клиент сам прислал И дистанцию,
И время; не прислал (или прислал мусор/NaN) — проверки нет, а баллы начислялись
как обычно. Занизил дистанцию — проверка проходила.

Стало:
- дистанция = максимум из присланной и длины самого маршрута (маршрут — нижняя
  граница пройденного, его сервер видит сам). Заниженная/пропущенная дистанция
  больше не помогает;
- время не прислано / не число / не больше нуля → скорость не проверить →
  захват засчитывается на карте (старые сборки не ломаем), но баллы за него
  не начисляются и в ответе `unverified: true`.

Клиент mata_kvartal (territory_provider.dart, run_screen.dart) шлёт оба поля
с июня 2026 — для него ничего не меняется.
"""
from django.db import connection

from common.testutils import ApiTestCase

# Прямоугольник ~5800 м² у Якутска. Длина маршрута (3 отрезка, без замыкания)
# ≈ 111 + 52 + 111 ≈ 275 м.
_POLY = [[62.000, 129.700], [62.001, 129.700], [62.001, 129.701], [62.000, 129.701]]


class CaptureTrustTests(ApiTestCase):
    phone = "+79990009886"

    def _cap(self, cid, **extra):
        return self.api_post(
            "/v1/territories/capture", {"points": _POLY, "captureId": cid, **extra}
        )

    def test_route_length_is_computed(self):
        from territories.views import _route_length_m

        ring = [(lng, lat) for lat, lng in _POLY]
        self.assertAlmostEqual(_route_length_m(ring), 275, delta=15)

    def test_honest_payload_still_awarded(self):
        """Как шлёт реальный клиент: дистанция и время пробежки — баллы есть."""
        from django.utils import timezone

        from runs.models import Run

        Run.objects.create(id="run_honest", user_id=self.uid, distance_m=1200.0,
                           duration_s=420, finished_at=timezone.now())
        r = self._cap("honest", distanceMeters=1200.0, elapsedSeconds=420)
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertGreater(body["points"], 0)
        self.assertNotIn("unverified", body)
        self.assertEqual(self.balance(), body["points"])

    def test_missing_time_gives_no_points(self):
        """Не прислал время — скорость не проверить: зона есть, баллов нет."""
        r = self._cap("no-time", distanceMeters=1200.0)
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["points"], 0)
        self.assertTrue(body["unverified"])
        self.assertGreater(body["areaM2"], 0)  # старая сборка не отбита: зона засчитана
        self.assertEqual(self.balance(), 0)

    def test_missing_both_fields_gives_no_points(self):
        r = self._cap("no-fields")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["points"], 0)
        self.assertEqual(self.balance(), 0)

    def test_garbage_time_gives_no_points(self):
        for i, bad in enumerate(["abc", "NaN", "Infinity", 0, -5, True, [1]]):
            with self.subTest(elapsed=bad):
                # Каждый раз новая земля (иначе баллов не будет и без правки),
                # кулдаун снимаем, состарив метку своей территории.
                pts = [[lat, lng + 0.01 * (i + 1)] for lat, lng in _POLY]
                r = self.api_post("/v1/territories/capture", {
                    "points": pts, "captureId": f"bad-time-{i}",
                    "distanceMeters": 1200.0, "elapsedSeconds": bad,
                })
                self.assertEqual(r.status_code, 200, r.content)
                self.assertEqual(r.json()["points"], 0)
                with connection.cursor() as cur:
                    cur.execute(
                        "UPDATE territories SET captured_at = now() - interval '1 hour' "
                        "WHERE owner_id=%s", [self.uid])
        self.assertEqual(self.balance(), 0)

    def test_understated_distance_is_caught_by_route_length(self):
        """Клиент занизил дистанцию до 1 м — длина маршрута ~275 м за 10 с = 99 км/ч."""
        r = self._cap("liar", distanceMeters=1, elapsedSeconds=10)
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(self.balance(), 0)

    def test_missing_distance_is_taken_from_route(self):
        r = self._cap("no-dist", elapsedSeconds=10)
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(self.balance(), 0)

    def test_garbage_distance_is_taken_from_route(self):
        r = self._cap("nan-dist", distanceMeters="NaN", elapsedSeconds=10)
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(self.balance(), 0)
