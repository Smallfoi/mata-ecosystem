"""Суточный лимит дистанции считается по забегам И импорту вместе (аудит 08.09.2026).

Раздельные потолки обходятся тривиально: набрал лимит импортом с часов, потом
столько же своими забегами — и суточная норма удвоилась. Импорт эту сторону
считал правильно, приём забегов — нет.
"""
import time

from common.testutils import ApiTestCase
from django.utils import timezone
from runs.rules import MAX_DAY_DISTANCE_M
from workouts.models import ExternalWorkout


class CombinedDailyDistance(ApiTestCase):
    phone = "+79990004101"

    def _import(self, meters, when=None):
        """Импортированная тренировка, как будто пришла с часов."""
        started = when or timezone.now()
        ExternalWorkout.objects.create(
            id=f"w_{meters}_{started.timestamp()}",
            user_id=self.uid, source="healthConnect", source_id=f"s{meters}",
            sport="running", distance_m=meters, duration_s=int(meters / 3),
            started_at=started, run_id="", flagged=False,
        )

    def _run(self, meters, rid):
        return self.api_post("/v1/runs", {
            "id": rid, "distanceMeters": meters,
            "elapsedSeconds": int(meters / 3),
            "finishedAtMs": int(time.time() * 1000),
        }).json()

    def test_import_then_run_hits_the_shared_cap(self):
        """Раньше так удваивалась суточная норма."""
        self._import(MAX_DAY_DISTANCE_M - 1000)
        out = self._run(5000, "cap_r1")
        self.assertTrue(out["flagged"])
        self.assertEqual(out["flagReason"], "Превышен суточный лимит дистанции")
        self.assertEqual(out["pointsAwarded"], 0)

    def test_normal_run_still_passes(self):
        """Закрутив гайку, нельзя мешать обычному бегуну."""
        self._import(5000)
        out = self._run(5000, "cap_r2")
        self.assertFalse(out["flagged"])
        self.assertEqual(out["pointsAwarded"], 50)

    def test_flagged_import_does_not_count(self):
        """Помеченный импорт баллов не принёс — и лимит занимать не должен."""
        w = ExternalWorkout.objects.create(
            id="w_flagged", user_id=self.uid, source="healthConnect",
            source_id="sf", sport="running", distance_m=MAX_DAY_DISTANCE_M,
            duration_s=50000, started_at=timezone.now(), run_id="", flagged=True,
        )
        self.assertTrue(w.flagged)
        out = self._run(5000, "cap_r3")
        self.assertFalse(out["flagged"])

    def test_import_matched_to_a_run_is_not_double_counted(self):
        """Импорт, признанный тем же забегом (run_id заполнен), уже учтён забегом."""
        self._run(5000, "cap_r4")
        ExternalWorkout.objects.create(
            id="w_same", user_id=self.uid, source="healthConnect", source_id="ss",
            sport="running", distance_m=MAX_DAY_DISTANCE_M - 6000, duration_s=50000,
            started_at=timezone.now(), run_id="cap_r4", flagged=False,
        )
        out = self._run(5000, "cap_r5")
        self.assertFalse(out["flagged"], "дубль импорта съел чужой лимит")
