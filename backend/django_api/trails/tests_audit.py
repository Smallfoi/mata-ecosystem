"""Аудит 27.09.2026: C01 (трек и попытки троп привязаны к владельцу забега)
и D04 (мусор в треке — не 500).

Порядок в клиенте (completed_runs_provider.dart): сначала сводка /v1/runs, после
её успеха — трек. Но старые сборки и офлайн-повторы могут прислать трек раньше
сводки, поэтому «забега ещё нет ни у кого» — законный случай.
"""
from django.utils import timezone

from common.testutils import ApiTestCase
from runs.models import Run
from trails import matching
from trails.models import PendingTrack, Trail, TrailAttempt
from trails.tests import line, track_along


class TrailOwnershipTests(ApiTestCase):
    phone = "+79990009883"
    other_phone = "+79990009884"

    def setUp(self):
        super().setUp()
        pts = line()
        min_lat, max_lat, min_lon, max_lon = matching.bbox(pts)
        self.trail = Trail.objects.create(
            id="t_audit", name="Аудит", points=pts,
            length_m=matching.line_length_m(pts),
            min_lat=min_lat, max_lat=max_lat, min_lon=min_lon, max_lon=max_lon,
        )
        self.other_token = self.new_user(self.other_phone)
        from accounts.models import Account

        self.other_uid = Account.objects.get(phone=self.other_phone).id

    def _send(self, run_id, token=None):
        return self.api_post(
            "/v1/runs/track",
            {"runId": run_id, "points": track_along(self.trail.points, lead=2, tail=2)},
            token=token,
        )

    def test_foreign_run_is_rejected(self):
        Run.objects.create(id="run_a", user_id=self.other_uid, distance_m=1000,
                           duration_s=600, finished_at=timezone.now())
        r = self._send("run_a")
        self.assertEqual(r.status_code, 409)
        self.assertFalse(PendingTrack.objects.filter(run_id="run_a").exists())
        self.assertFalse(TrailAttempt.objects.filter(run_id="run_a").exists())

    def test_foreign_track_is_not_overwritten(self):
        """Забега ещё нет, но трек с этим runId уже прислал другой — владелец не меняется."""
        self.assertEqual(self._send("run_b", token=self.other_token).status_code, 200)
        r = self._send("run_b")
        self.assertEqual(r.status_code, 409)
        self.assertEqual(PendingTrack.objects.get(run_id="run_b").user_id, self.other_uid)
        self.assertEqual(
            set(TrailAttempt.objects.filter(run_id="run_b").values_list("user_id", flat=True)),
            {self.other_uid},
        )

    def test_foreign_attempt_after_track_cleanup_is_rejected(self):
        """Трек удалён через 14 дней (D-60), а попытка осталась — её тоже не перехватить."""
        self._send("run_c", token=self.other_token)
        PendingTrack.objects.filter(run_id="run_c").delete()
        self.assertEqual(self._send("run_c").status_code, 409)
        self.assertEqual(TrailAttempt.objects.get(run_id="run_c").user_id, self.other_uid)

    def test_track_before_run_is_allowed_and_repeat_is_idempotent(self):
        r1 = self._send("run_d")
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(len(r1.json()["attempts"]), 1)
        r2 = self._send("run_d")
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(TrailAttempt.objects.filter(run_id="run_d").count(), 1)
        self.assertEqual(PendingTrack.objects.get(run_id="run_d").user_id, self.uid)

    def test_own_run_then_track_is_fine(self):
        Run.objects.create(id="run_e", user_id=self.uid, distance_m=1000,
                           duration_s=600, finished_at=timezone.now())
        self.assertEqual(self._send("run_e").status_code, 200)

    # ── D04 ────────────────────────────────────────────────────────────────

    def test_garbage_points_do_not_crash(self):
        pts = track_along(self.trail.points)
        junk = [{"lat": 1}, "x", None, ["inf", 1, 2],
                [62.0, 129.0, "Infinity"], [62.0, 129.0, 10 ** 30]]
        r = self.api_post("/v1/runs/track", {"runId": "run_j", "points": junk + pts})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()["attempts"]), 1)

    def test_absurd_timestamps_are_dropped(self):
        """Метки времени за пределами разумного — не точки, а не 500 при сверке."""
        pts = [[p[0], p[1], 10 ** 17 + i] for i, p in enumerate(track_along(self.trail.points))]
        r = self.api_post("/v1/runs/track", {"runId": "run_k", "points": pts})
        self.assertEqual(r.status_code, 400)
        self.assertFalse(PendingTrack.objects.filter(run_id="run_k").exists())

    def test_non_dict_body_is_400(self):
        r = self.client.post(
            "/v1/runs/track", data="[1]", content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.token}",
        )
        self.assertEqual(r.status_code, 400)
