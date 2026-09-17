"""Регрессии анти-чита бега (S-04): сервер сам считает очки, чит/реплей → flagged/0."""
import time

from django.test import TestCase

from common.testutils import ApiTestCase

_NOW_MS = int(time.time() * 1000)
_DAY_MS = 86_400_000
# Базовый правдоподобный забег: 5 км за 30 мин (10 км/ч), завершён только что.
_OK = {"distanceMeters": 5000, "elapsedSeconds": 1800, "finishedAtMs": _NOW_MS}


class RunAntiCheatTests(ApiTestCase):
    phone = "+79990002001"

    def test_valid_run_awards_server_side(self):
        r = self.api_post("/v1/runs", {"id": "r1", **_OK}).json()
        self.assertFalse(r["flagged"])
        self.assertEqual(r["pointsAwarded"], 50)  # 5 км × 10
        self.assertEqual(self.balance(), 50)

    def test_duplicate_run_no_double_award(self):
        self.api_post("/v1/runs", {"id": "r1", **_OK})
        r = self.api_post("/v1/runs", {"id": "r1", **_OK}).json()
        self.assertTrue(r["duplicate"])
        self.assertEqual(self.balance(), 50)

    def test_speed_cheat_flagged_zero(self):
        r = self.api_post(
            "/v1/runs",
            {"id": "r2", "distanceMeters": 5000, "elapsedSeconds": 10,
             "finishedAtMs": _NOW_MS},
        ).json()
        self.assertTrue(r["flagged"])
        self.assertEqual(r["pointsAwarded"], 0)
        self.assertEqual(self.balance(), 0)

    def test_distance_cheat_flagged(self):
        r = self.api_post(
            "/v1/runs",
            {"id": "r3", "distanceMeters": 500000, "elapsedSeconds": 200000,
             "finishedAtMs": _NOW_MS},
        ).json()
        self.assertTrue(r["flagged"])
        self.assertEqual(self.balance(), 0)

    def test_future_run_flagged(self):
        r = self.api_post(
            "/v1/runs",
            {"id": "r4", "distanceMeters": 5000, "elapsedSeconds": 1800,
             "finishedAtMs": _NOW_MS + 2 * _DAY_MS},
        ).json()
        self.assertTrue(r["flagged"])
        self.assertEqual(self.balance(), 0)

    def test_old_run_flagged_replay(self):
        r = self.api_post(
            "/v1/runs",
            {"id": "r5", "distanceMeters": 5000, "elapsedSeconds": 1800,
             "finishedAtMs": _NOW_MS - 40 * _DAY_MS},
        ).json()
        self.assertTrue(r["flagged"])
        self.assertEqual(self.balance(), 0)

    def test_too_many_runs_per_day_flagged(self):
        # 30 валидных забегов за сутки — ок; 31-й → flagged (анти-спам).
        for i in range(30):
            r = self.api_post(
                "/v1/runs",
                {"id": f"rc{i}", "distanceMeters": 1000, "elapsedSeconds": 600,
                 "finishedAtMs": _NOW_MS},
            ).json()
            self.assertFalse(r["flagged"], f"забег {i} должен быть валидным")
        over = self.api_post(
            "/v1/runs",
            {"id": "rc_over", "distanceMeters": 1000, "elapsedSeconds": 600,
             "finishedAtMs": _NOW_MS},
        ).json()
        self.assertTrue(over["flagged"])
        self.assertEqual(over["pointsAwarded"], 0)

    def test_mock_gps_flagged_zero(self):
        # Клиент сообщил о подделке геолокации → забег флагается, 0 очков.
        r = self.api_post("/v1/runs", {"id": "rm1", "mockDetected": True, **_OK}).json()
        self.assertTrue(r["flagged"])
        self.assertIn("mock", r["flagReason"].lower())
        self.assertEqual(r["pointsAwarded"], 0)
        self.assertEqual(self.balance(), 0)

    def test_account_flagged_for_review_after_repeated_cheating(self):
        # Накопление флагнутых забегов помечает аккаунт «на ревью» (порог 5).
        from accounts.models import Account
        for i in range(4):
            self.api_post("/v1/runs", {"id": f"rmk{i}", "mockDetected": True, **_OK})
        self.assertFalse(Account.objects.get(id=self.uid).needs_review)  # 4 < порога
        self.api_post("/v1/runs", {"id": "rmk_5", "mockDetected": True, **_OK})
        self.assertTrue(Account.objects.get(id=self.uid).needs_review)   # 5 → ревью

    def test_runs_list_exposes_pending_review(self):
        # Карточка истории показывает «на проверке»: GET /runs отдаёт pendingReview.
        self.api_post("/v1/runs", {"id": "r_ok", **_OK})
        self.api_post("/v1/runs", {
            "id": "r_flag", "distanceMeters": 5000, "elapsedSeconds": 10,
            "finishedAtMs": _NOW_MS,
        })
        rows = {r["id"]: r for r in self.api_get("/v1/runs").json()}
        self.assertFalse(rows["r_ok"]["flagged"])
        self.assertFalse(rows["r_ok"]["pendingReview"])
        self.assertTrue(rows["r_flag"]["flagged"])
        self.assertTrue(rows["r_flag"]["pendingReview"])
        # После разбора модератором метка снимается.
        from runs.models import Run
        from runs.views import approve_run
        approve_run(Run.objects.get(id="r_flag"))
        rows = {r["id"]: r for r in self.api_get("/v1/runs").json()}
        self.assertFalse(rows["r_flag"]["pendingReview"])

    def test_client_cannot_mint_runner_run(self):
        r = self.api_post(
            "/v1/loyalty/transactions",
            {"amount": 9999, "source": "runnerRun", "runId": "x"},
        )
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.balance(), 0)

    def test_approve_flagged_run_awards_points_idempotent(self):
        """S-04 ф.2: модератор одобряет флаг-забег → очки начисляются один раз."""
        from runs.models import Run
        from runs.views import approve_run

        # Спид-чит: 5 км за 10 с → flagged, 0 очков.
        self.api_post("/v1/runs", {
            "id": "r_mod", "distanceMeters": 5000, "elapsedSeconds": 10,
            "finishedAtMs": _NOW_MS,
        })
        run = Run.objects.get(id="r_mod")
        self.assertTrue(run.flagged)
        self.assertEqual(self.balance(), 0)
        # Одобрение → снят флаг + 50 очков (5 км × 10).
        self.assertEqual(approve_run(run), 50)
        run.refresh_from_db()
        self.assertFalse(run.flagged)
        self.assertEqual(run.points_awarded, 50)
        self.assertEqual(self.balance(), 50)
        # Повторное одобрение не дублирует начисление.
        approve_run(run)
        self.assertEqual(self.balance(), 50)


class ModeratorGroupTests(TestCase):
    """S-10 ф.2: команда создаёт группу «Модератор» с ограниченными правами."""

    def test_setup_moderator_group(self):
        from django.contrib.auth.models import Group
        from django.core.management import call_command

        call_command("setup_moderator_group")
        g = Group.objects.get(name="Модератор")
        codes = set(g.permissions.values_list("codename", flat=True))
        # Может модерировать забеги/отзывы/аккаунты.
        self.assertIn("change_run", codes)
        self.assertIn("change_review", codes)
        self.assertIn("change_account", codes)
        # НЕ полный админ: не правит товары.
        self.assertNotIn("change_product", codes)
