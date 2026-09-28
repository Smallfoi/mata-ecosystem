"""Аудит 27.09.2026: C05 (забег и начисление — одно целое, повтор доводит
недостающее начисление ровно один раз), C01 (чужой runId), D04 (некорректные числа).
"""
from unittest import mock

from django.utils import timezone

from common.testutils import ApiTestCase
from loyalty.models import LoyaltyTransaction
from runs.models import Run
from trails.models import PendingTrack


class RunsAuditTests(ApiTestCase):
    phone = "+79990009882"

    def _body(self, rid="ra_1", **over):
        body = {
            "id": rid,
            "distanceMeters": 5000.0,
            "elapsedSeconds": 1800,
            "finishedAtMs": int(timezone.now().timestamp() * 1000),
            "capturedTerritory": False,
            "capturedZones": 0,
            "mockDetected": False,
        }
        body.update(over)
        return body

    def _run_txns(self, rid):
        return LoyaltyTransaction.objects.filter(
            user_id=self.uid, run_id=rid, source="runnerRun"
        )

    # ── C05 ────────────────────────────────────────────────────────────────

    def test_crash_between_run_and_award_leaves_nothing_and_retry_awards_once(self):
        with mock.patch("runs.views.add_txn", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self.api_post("/v1/runs", self._body("ra_crash"))
        self.assertFalse(Run.objects.filter(id="ra_crash").exists())

        r = self.api_post("/v1/runs", self._body("ra_crash"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["pointsAwarded"], 50)
        self.api_post("/v1/runs", self._body("ra_crash"))
        self.assertEqual(self._run_txns("ra_crash").count(), 1)
        self.assertEqual(self.balance(), 50)

    def test_retry_repairs_run_saved_without_award(self):
        """Состояние с прода: забег сохранён с баллами, а транзакции нет (обрыв
        между двумя записями до этой правки). Повтор доводит начисление один раз."""
        Run.objects.create(
            id="ra_orphan", user_id=self.uid, distance_m=4000, duration_s=1500,
            finished_at=timezone.now(), points_awarded=40,
        )
        r = self.api_post("/v1/runs", self._body("ra_orphan", distanceMeters=4000.0))
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["duplicate"])
        self.api_post("/v1/runs", self._body("ra_orphan", distanceMeters=4000.0))
        self.assertEqual(self._run_txns("ra_orphan").count(), 1)
        self.assertEqual(self.balance(), 40)

    def test_retry_does_not_pay_flagged_or_rejected_run(self):
        Run.objects.create(
            id="ra_flag", user_id=self.uid, distance_m=4000, duration_s=1500,
            finished_at=timezone.now(), points_awarded=0, flagged=True,
        )
        self.api_post("/v1/runs", self._body("ra_flag"))
        self.assertEqual(self.balance(), 0)

    # ── C01 (со стороны сводки) ─────────────────────────────────────────────

    def test_run_id_of_foreign_track_is_conflict(self):
        PendingTrack.objects.create(run_id="ra_foreign", user_id="someone_else", points=[])
        r = self.api_post("/v1/runs", self._body("ra_foreign"))
        self.assertEqual(r.status_code, 409)
        self.assertFalse(Run.objects.filter(id="ra_foreign").exists())

    def test_own_track_first_then_run_is_fine(self):
        PendingTrack.objects.create(run_id="ra_mine", user_id=self.uid, points=[])
        r = self.api_post("/v1/runs", self._body("ra_mine"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Run.objects.get(id="ra_mine").user_id, self.uid)

    # ── D04 ────────────────────────────────────────────────────────────────

    def test_bad_numbers_are_400_without_saving(self):
        cases = [
            {"distanceMeters": "abc"},
            {"distanceMeters": "Infinity"},
            {"distanceMeters": "nan"},
            {"distanceMeters": -5},
            {"elapsedSeconds": "12x"},
            {"elapsedSeconds": 10 ** 12},
            {"finishedAtMs": "yesterday"},
            {"finishedAtMs": 10 ** 20},
            {"capturedZones": 10 ** 12},
            {"distanceMeters": True},
        ]
        for i, over in enumerate(cases):
            rid = f"ra_bad_{i}"
            r = self.api_post("/v1/runs", self._body(rid, **over))
            self.assertEqual(r.status_code, 400, over)
            self.assertFalse(Run.objects.filter(id=rid).exists(), over)
        self.assertEqual(self.balance(), 0)

    def test_non_dict_body_is_400(self):
        r = self.client.post(
            "/v1/runs", data="[1]", content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.token}",
        )
        self.assertEqual(r.status_code, 400)

    def test_client_shape_still_accepted(self):
        """Ровно то, что шлёт mata_kvartal (_syncRun): double-дистанция, int-секунды,
        мс-время; без finishedAtMs — «сейчас», как раньше."""
        r = self.api_post("/v1/runs", self._body("ra_ok", distanceMeters=5012.37))
        self.assertEqual(r.status_code, 200)
        body = self._body("ra_ok2")
        del body["finishedAtMs"]
        self.assertEqual(self.api_post("/v1/runs", body).status_code, 200)
