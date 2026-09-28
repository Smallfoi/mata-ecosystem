"""Правила античита, принятые владельцем 28.09.2026.

1. Суточный потолок баллов за бег — 1000, общий на свои забеги, импорт с часов (п.7)
   и захваты. Сверх потолка — 0 баллов с причиной (не 400).
2. Баллы за активность «созревают» 3 дня: до этого их нельзя потратить.
   `/v1/loyalty/account.balance` — тратимое; `pending`/`total`/`pendingNextAt` — новые.
3. Пока аккаунт на проверке (needs_review), баллы за активность заморожены.
4. Баллы за захват — только за принятую пробежку; захват раньше сводки ждёт её и
   получает баллы ровно один раз.
"""
import time
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from accounts.models import Account
from common.testutils import ApiTestCase
from loyalty.models import LoyaltyTransaction, add_txn, spendable_of, wallet_summary
from orders.models import Order
from runs.models import Run
from runs.review import approve_run, recalculate, reject_run, runner_context
from runs.rules import MAX_DAY_ACTIVITY_POINTS
from territories.models import CaptureAward

_POLY = [[62.000, 129.700], [62.001, 129.700], [62.001, 129.701], [62.000, 129.701]]


def _now_ms():
    return int(time.time() * 1000)


def _run(rid, km, minutes=None, **extra):
    minutes = minutes if minutes is not None else km * 6  # 10 км/ч
    return {"id": rid, "distanceMeters": km * 1000.0, "elapsedSeconds": int(minutes * 60),
            "finishedAtMs": _now_ms(), **extra}


def _day_points(uid):
    """Баллы в суточном бюджете (вехи за пожизненные км идут сверх — они разовые)."""
    return sum(LoyaltyTransaction.objects.filter(
        user_id=uid, source__in=("runnerRun", "runnerTerritory")
    ).values_list("amount", flat=True))


def _mature(uid):
    """«Прошло 3 дня»: все начисления пользователя созрели."""
    LoyaltyTransaction.objects.filter(user_id=uid, available_at__isnull=False).update(
        available_at=timezone.now() - timedelta(seconds=1)
    )


# ─────────────────────────── п.1 и п.7: суточный потолок ───────────────────────────

class DailyPointsCapTests(ApiTestCase):
    phone = "+79990028001"

    def test_runs_capped_at_1000_per_day_without_400(self):
        r1 = self.api_post("/v1/runs", _run("cap1", 60)).json()
        self.assertEqual(r1["pointsAwarded"], 600)
        self.assertNotIn("dailyCapReached", r1)

        r2 = self.api_post("/v1/runs", _run("cap2", 60))
        self.assertEqual(r2.status_code, 200)
        b2 = r2.json()
        self.assertFalse(b2["flagged"])
        self.assertEqual(b2["pointsAwarded"], 400)
        self.assertTrue(b2["dailyCapReached"])
        self.assertEqual(b2["pointsCapped"], 200)
        self.assertIn("1000", b2["capReason"])

        b3 = self.api_post("/v1/runs", _run("cap3", 5)).json()
        self.assertEqual(b3["pointsAwarded"], 0)
        self.assertTrue(b3["dailyCapReached"])
        self.assertEqual(_day_points(self.uid), MAX_DAY_ACTIVITY_POINTS)
        # Забег засчитан (км в зачёт), просто без баллов.
        self.assertFalse(Run.objects.get(id="cap3").flagged)

    def test_duplicate_of_capped_run_keeps_reason_and_does_not_pay(self):
        self.api_post("/v1/runs", _run("d1", 95, minutes=600))
        self.api_post("/v1/runs", _run("d2", 10))
        again = self.api_post("/v1/runs", _run("d2", 10)).json()
        self.assertTrue(again["duplicate"])
        self.assertEqual(again["pointsAwarded"], 50)
        self.assertEqual(again["pointsCapped"], 50)
        self.assertEqual(_day_points(self.uid), 1000)

    def test_recalculate_does_not_top_up_capped_points(self):
        self.api_post("/v1/runs", _run("rc1", 95, minutes=600))
        self.api_post("/v1/runs", _run("rc2", 10))
        self.assertEqual(recalculate(self.uid), {"runs": 0, "delta": 0})
        self.assertEqual(_day_points(self.uid), 1000)

    def test_yesterday_does_not_eat_today(self):
        self.api_post("/v1/runs", _run("y1", 95, minutes=600))
        LoyaltyTransaction.objects.filter(user_id=self.uid).update(
            created_at=timezone.now() - timedelta(days=1, hours=1))
        self.assertEqual(self.api_post("/v1/runs", _run("y2", 10)).json()["pointsAwarded"], 100)

    def test_watch_import_shares_the_budget(self):
        """п.7: импорт с часов — тот же суточный бюджет, что и свой бег."""
        self.api_post("/v1/runs", _run("w1", 90, minutes=600))
        started = _now_ms() - 3 * 3600 * 1000  # другое время — не «тот же забег»
        r = self.api_post("/v1/workouts/import", {
            "source": "healthconnect",
            "items": [{"sourceId": "hc-1", "startedAtMs": started, "durationS": 7200,
                       "distanceM": 20000, "sport": "running"}],
        })
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["points"], 100)
        self.assertTrue(body["dailyCapReached"])
        self.assertEqual(body["pointsCapped"], 100)
        self.assertEqual(body["items"][0]["pointsAwarded"], 100)
        self.assertEqual(_day_points(self.uid), 1000)

    def test_import_first_then_run_is_capped_too(self):
        started = _now_ms() - 5 * 3600 * 1000
        self.api_post("/v1/workouts/import", {
            "source": "healthconnect",
            "items": [{"sourceId": "hc-2", "startedAtMs": started, "durationS": 36000,
                       "distanceM": 95000, "sport": "running"}],
        })
        b = self.api_post("/v1/runs", _run("w2", 10)).json()
        self.assertEqual(b["pointsAwarded"], 50)
        self.assertTrue(b["dailyCapReached"])


# ─────────────────────────────── п.2: созревание ───────────────────────────────

class MaturationTests(ApiTestCase):
    phone = "+79990028002"

    def test_run_points_mature_in_three_days(self):
        self.api_post("/v1/runs", _run("m1", 10))
        txn = LoyaltyTransaction.objects.get(user_id=self.uid, source="runnerRun")
        self.assertIsNotNone(txn.available_at)
        left = txn.available_at - txn.created_at
        self.assertEqual(left, timedelta(days=3))

        acc = self.api_get("/v1/loyalty/account").json()
        self.assertEqual(acc["balance"], 0)          # тратимое — старые Store видят его
        self.assertEqual(acc["pending"], 100)
        self.assertEqual(acc["total"], 100)
        self.assertEqual(acc["pendingNextAmount"], 100)
        self.assertIsNotNone(acc["pendingNextAt"])
        self.assertFalse(acc["frozen"])

        _mature(self.uid)
        cache.clear()
        acc = self.api_get("/v1/loyalty/account").json()
        self.assertEqual(acc["balance"], 100)
        self.assertEqual(acc["pending"], 0)
        self.assertIsNone(acc["pendingNextAt"])

    def test_cannot_spend_unmatured_points(self):
        self.api_post("/v1/runs", _run("m2", 10))
        Order.objects.create(user_id=self.uid, order_id="o-m", total=450, points_redeemed=50,
                             payment_status="pending", status="pending", payload={"id": "o-m"})
        r = self.api_post("/v1/loyalty/redeem", {"amount": 50, "orderId": "o-m"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("3 дня", r.json()["detail"])
        self.assertEqual(r.json()["balance"], 0)
        _mature(self.uid)
        r = self.api_post("/v1/loyalty/redeem", {"amount": 50, "orderId": "o-m"})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["balance"], 50)

    def test_purchase_and_bonus_points_are_available_at_once(self):
        add_txn(self.uid, 70, "purchase", "Покупка", "o-p")
        add_txn(self.uid, 50, "registration", "Бонус")
        self.assertEqual(spendable_of(self.uid), 120)

    def test_old_transactions_count_as_matured(self):
        """Миграция: у проводок до правила available_at пуст — они тратятся."""
        add_txn(self.uid, 300, "runnerRun", "старое", available_at=None)
        self.assertEqual(spendable_of(self.uid), 300)

    def test_milestone_and_territory_points_mature_too(self):
        for src in ("runnerMilestone", "runnerTerritory", "runnerDivision", "runnerSeason"):
            add_txn(self.uid, 10, src)
        self.assertEqual(spendable_of(self.uid), 0)
        self.assertEqual(wallet_summary(self.uid)["pending"], 40)

    def test_revoking_unmatured_points_does_not_hit_spendable(self):
        add_txn(self.uid, 500, "purchase", "Покупка", "o-r")
        self.api_post("/v1/runs", _run("m3", 10))
        run = Run.objects.get(id="m3")
        reject_run(run, notify=False)
        # Отозвали несозревшие 100 — тратимые 500 от покупки не тронуты.
        self.assertEqual(spendable_of(self.uid), 500)
        _mature(self.uid)
        self.assertEqual(spendable_of(self.uid), 500)

    def test_me_stats_balance_is_spendable(self):
        self.api_post("/v1/runs", _run("m4", 10))
        d = self.api_get("/v1/me/stats").json()["loyalty"]
        self.assertEqual(d["balance"], 0)
        self.assertEqual(d["pending"], 100)
        self.assertEqual(d["earned"], 100)


# ───────────────────────── п.3: заморозка на время проверки ─────────────────────────

class FreezeOnReviewTests(ApiTestCase):
    phone = "+79990028003"

    def _flag(self, on=True):
        Account.objects.filter(id=self.uid).update(needs_review=on)
        cache.clear()

    def test_review_freezes_even_matured_activity_points(self):
        add_txn(self.uid, 200, "purchase", "Покупка", "o-f")
        self.api_post("/v1/runs", _run("f1", 10))
        _mature(self.uid)
        self.assertEqual(spendable_of(self.uid), 300)

        self._flag()
        acc = self.api_get("/v1/loyalty/account").json()
        self.assertTrue(acc["frozen"])
        self.assertEqual(acc["balance"], 200)   # покупка — тратится
        self.assertEqual(acc["pending"], 100)   # бег — заморожен
        self.assertIsNone(acc["pendingNextAt"])

        self._flag(False)
        self.assertEqual(spendable_of(self.uid), 300)

    def test_unfreeze_keeps_normal_maturation(self):
        self.api_post("/v1/runs", _run("f2", 10))
        self._flag()
        self._flag(False)
        self.assertEqual(spendable_of(self.uid), 0)  # ещё не созрели
        _mature(self.uid)
        self.assertEqual(spendable_of(self.uid), 100)

    def test_points_from_before_the_rule_are_not_frozen(self):
        add_txn(self.uid, 300, "runnerRun", "старое", available_at=None)
        self._flag()
        self.assertEqual(spendable_of(self.uid), 300)

    def test_frozen_points_cannot_be_redeemed(self):
        self.api_post("/v1/runs", _run("f3", 10))
        _mature(self.uid)
        self._flag()
        Order.objects.create(user_id=self.uid, order_id="o-fz", total=450, points_redeemed=50,
                             payment_status="pending", status="pending",
                             payload={"id": "o-fz"})
        r = self.api_post("/v1/loyalty/redeem", {"amount": 50, "orderId": "o-fz"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("проверки", r.json()["detail"])

    def test_auto_review_flag_refreshes_cached_wallet(self):
        self.api_post("/v1/runs", _run("f4", 10))
        _mature(self.uid)
        cache.clear()
        self.assertFalse(self.api_get("/v1/loyalty/account").json()["frozen"])  # в кэше
        for i in range(5):  # 5 спид-читов → needs_review
            self.api_post("/v1/runs", {"id": f"cheat{i}", "distanceMeters": 5000,
                                       "elapsedSeconds": 10, "finishedAtMs": _now_ms()})
        acc = self.api_get("/v1/loyalty/account").json()
        self.assertTrue(acc["frozen"])
        self.assertEqual(acc["balance"], 0)

    def test_runner_context_reports_frozen_points(self):
        self.api_post("/v1/runs", _run("f5", 10))
        self._flag()
        ctx = runner_context(self.uid)
        self.assertEqual(ctx["frozen_points"], 100)


class FreezeConsoleTests(TestCase):
    """Экран разбора показывает одной строкой, сколько баллов заморожено."""

    def test_page_shows_frozen_line(self):
        from django_otp import DEVICE_ID_SESSION_KEY
        from django_otp.plugins.otp_totp.models import TOTPDevice

        cache.clear()
        owner = User.objects.create_superuser("owner", "o@t.dev", "OwnerPass!2026")
        device = TOTPDevice.objects.create(user=owner, name="t", confirmed=True)
        Account.objects.create(id="u_fz", email="f@t.dev", name="Бегун Ф",
                               phone="+79990028099", needs_review=True)
        add_txn("u_fz", 120, "runnerRun", "Пробежка", None, "r_fz")
        Run.objects.create(id="r_fz2", user_id="u_fz", distance_m=5000, duration_s=10,
                           finished_at=timezone.now(), flagged=True, flag_reason="Скорость")
        self.client.force_login(owner)
        s = self.client.session
        s[DEVICE_ID_SESSION_KEY] = device.persistent_id
        s.save()
        html = self.client.get("/admin/runs-review/?mode=review").content.decode()
        self.assertIn("Заморожено 120 баллов", html)


# ─────────────────────── п.4: захват — только за принятую пробежку ───────────────────────

class CaptureNeedsRunTests(ApiTestCase):
    phone = "+79990028004"
    _M = {"distanceMeters": 1200.0, "elapsedSeconds": 420}

    def _cap(self, cid, **extra):
        return self.api_post("/v1/territories/capture",
                             {"points": _POLY, "captureId": cid, **self._M, **extra})

    def _summary(self, rid, **over):
        body = {"id": rid, "distanceMeters": 1200.0, "elapsedSeconds": 420,
                "finishedAtMs": _now_ms()}
        body.update(over)
        return self.api_post("/v1/runs", body)

    def _terr(self):
        return sum(LoyaltyTransaction.objects.filter(
            user_id=self.uid, source__in=("runnerTerritory", "runnerTerritoryRevoked")
        ).values_list("amount", flat=True))

    def test_capture_before_run_waits_and_pays_once(self):
        """Старая сборка, офлайн/гонка: захват раньше сводки — не отказ, а ожидание."""
        r = self._cap("c-early")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["points"], 0)
        self.assertGreater(body["pointsPending"], 0)
        self.assertIn("пробежка", body["pendingReason"])
        self.assertGreater(body["areaM2"], 0)  # зона на карте засчитана сразу
        self.assertEqual(self._terr(), 0)

        self._summary("run-early")
        paid = self._terr()
        self.assertEqual(paid, body["pointsPending"])
        # Повтор сводки из очереди и повтор захвата — второй раз не платят.
        self._summary("run-early")
        self._cap("c-early")
        self.assertEqual(self._terr(), paid)
        self.assertEqual(CaptureAward.objects.get(capture_id="c-early").run_id, "run-early")

    def test_capture_after_run_pays_immediately(self):
        self._summary("run-first")
        body = self._cap("c-late").json()
        self.assertGreater(body["points"], 0)
        self.assertNotIn("pointsPending", body)

    def test_run_id_from_new_client_links_directly(self):
        body = self._cap("c-id", runId="run-by-id").json()
        self.assertEqual(body["points"], 0)
        # Другая пробежка с теми же цифрами баллы не забирает — захват назвал свою.
        self._summary("run-other")
        self.assertEqual(self._terr(), 0)
        self._summary("run-by-id")
        self.assertGreater(self._terr(), 0)

    def test_capture_without_matching_run_gets_nothing(self):
        self._summary("run-short", distanceMeters=3000.0, elapsedSeconds=1500)
        body = self._cap("c-nomatch").json()
        self.assertEqual(body["points"], 0)
        self.assertGreater(body["pointsPending"], 0)
        self.assertEqual(self._terr(), 0)

    def test_one_paid_capture_per_run(self):
        self._summary("run-one")
        self.assertGreater(self._cap("c-1").json()["points"], 0)
        from django.db import connection

        with connection.cursor() as cur:  # обходим кулдаун
            cur.execute("UPDATE territories SET captured_at = now() - interval '1 hour'")
        poly2 = [[62.003, 129.703], [62.004, 129.703], [62.004, 129.704], [62.003, 129.704]]
        r = self.api_post("/v1/territories/capture",
                          {"points": poly2, "captureId": "c-2", **self._M}).json()
        self.assertEqual(r["points"], 0)
        self.assertEqual(CaptureAward.objects.get(capture_id="c-2").status,
                         CaptureAward.PENDING)

    def test_flagged_run_holds_capture_until_moderator(self):
        self._summary("run-flag", mockDetected=True)
        body = self._cap("c-flag").json()
        self.assertEqual(body["points"], 0)
        self.assertIn("проверке", body["pendingReason"])
        approve_run(Run.objects.get(id="run-flag"), notify=False)
        self.assertEqual(self._terr(), body["pointsPending"])

    def test_rejected_run_capture_never_pays(self):
        self._cap("c-rej")
        self._summary("run-rej", mockDetected=True)  # сводка пришла позже и помечена
        self.assertEqual(CaptureAward.objects.get(capture_id="c-rej").run_id, "run-rej")
        reject_run(Run.objects.get(id="run-rej"), notify=False)
        self.assertEqual(CaptureAward.objects.get(capture_id="c-rej").status,
                         CaptureAward.REJECTED)
        self.assertEqual(self._terr(), 0)

    def test_reject_after_approve_revokes_capture_points(self):
        self._summary("run-ar", mockDetected=True)
        self._cap("c-ar")
        run = Run.objects.get(id="run-ar")
        approve_run(run, notify=False)
        self.assertGreater(self._terr(), 0)
        reject_run(run, notify=False)
        self.assertEqual(self._terr(), 0)

    def test_capture_points_count_in_daily_cap(self):
        self.api_post("/v1/runs", _run("big", 95, minutes=600))  # 950
        self._summary("run-cap")                                  # +12 → 962
        body = self._cap("c-cap").json()
        self.assertEqual(body["points"], 38)
        self.assertTrue(body["dailyCapReached"])
        self.assertGreater(body["pointsCapped"], 0)
        self.assertEqual(_day_points(self.uid), 1000)

    def test_pending_captures_count_toward_capture_limit(self):
        from territories import views as tv

        for i in range(tv.MAX_CAPTURES_PER_DAY):
            CaptureAward.objects.create(capture_id=f"p{i}", user_id=self.uid, points=10)
        self.assertEqual(self._cap("c-over").status_code, 429)
