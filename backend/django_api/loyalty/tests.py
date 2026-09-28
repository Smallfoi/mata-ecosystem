"""Регрессии траты баллов + гейт демо-баллов."""
import os
from unittest import mock

from django.test import TestCase

from common.testutils import ApiTestCase
from loyalty.models import LoyaltyTransaction, add_txn, seed_runner_points
from notifications.models import Notification


def _order_with_points(uid, oid, points, total=None):
    """Заказ, получивший скидку баллами, — прежний /loyalty/redeem списывает только
    на существующий заказ и ровно его скидку (аудит B02)."""
    from orders.models import Order

    return Order.objects.create(
        user_id=uid, order_id=oid, points_redeemed=points,
        total=points * 10 if total is None else total,
        payment_status="pending", status="pending", payload={"id": oid},
    )


class LevelUpNotificationTests(TestCase):
    """Уведомление при росте уровня лояльности (бег/территории/покупки → add_txn)."""

    def _levels(self, uid):
        return Notification.objects.filter(user_id=uid, type="level")

    def test_crossing_threshold_notifies_once(self):
        uid = "u_lvl_a"
        add_txn(uid, 150, "runnerRun", "пробежка")  # basic — без уведомления
        self.assertEqual(self._levels(uid).count(), 0)
        add_txn(uid, 100, "runnerRun", "пробежка")  # 250 → silver
        self.assertEqual(self._levels(uid).count(), 1)
        self.assertIn("Серебро", self._levels(uid).first().title)

    def test_no_duplicate_within_same_level(self):
        uid = "u_lvl_b"
        add_txn(uid, 250, "runnerRun")  # → silver (1)
        add_txn(uid, 50, "runnerRun")  # 300, всё ещё silver
        self.assertEqual(self._levels(uid).count(), 1)

    def test_redeem_does_not_notify(self):
        uid = "u_lvl_c"
        add_txn(uid, 600, "manual")  # → gold (1)
        add_txn(uid, -500, "redeem")  # списание (amount<0) — без уведомления
        self.assertEqual(self._levels(uid).count(), 1)
        self.assertIn("Золото", self._levels(uid).first().title)


class SeedGateTests(TestCase):
    def test_seed_off_by_default(self):
        # Без SEED_DEMO_POINTS новый аккаунт получает 0 баллов (реальные данные).
        seed_runner_points("u_seed_a")
        self.assertEqual(
            LoyaltyTransaction.objects.filter(user_id="u_seed_a").count(), 0
        )

    @mock.patch.dict(os.environ, {"SEED_DEMO_POINTS": "1"})
    def test_seed_on_when_flag_set(self):
        seed_runner_points("u_seed_b")
        self.assertEqual(
            LoyaltyTransaction.objects.filter(user_id="u_seed_b").count(), 5
        )


class RedeemTests(ApiTestCase):
    phone = "+79990002004"

    def _seed(self, amount):
        # Начисляем напрямую (модельная функция, минуя эндпоинт-блокировку).
        add_txn(self.uid, amount, "manual", "тестовый баланс")

    def test_cannot_redeem_more_than_balance(self):
        self._seed(100)
        _order_with_points(self.uid, "o1", 300)  # 300 из 3300 — правила проходят
        r = self.api_post("/v1/loyalty/redeem", {"amount": 300, "orderId": "o1"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.balance(), 100)  # не списалось

    def test_redeem_idempotent_by_order(self):
        self._seed(100)
        _order_with_points(self.uid, "o1", 60)
        self.api_post("/v1/loyalty/redeem", {"amount": 60, "orderId": "o1"})
        r = self.api_post("/v1/loyalty/redeem", {"amount": 60, "orderId": "o1"}).json()
        self.assertTrue(r["deduped"])
        self.assertEqual(self.balance(), 40)  # списано один раз


class LevelBoundaryTests(TestCase):
    """Границы уровней (бизнес-логика): basic<200, silver 200–499, gold 500–999,
    platinum≥1000 — фиксируем ровно на порогах, чтобы не съехали."""

    def test_level_for_exact_boundaries(self):
        from loyalty.models import level_for

        cases = {
            0: "basic", 199: "basic",
            200: "silver", 499: "silver",
            500: "gold", 999: "gold",
            1000: "platinum", 5000: "platinum",
        }
        for balance, level in cases.items():
            self.assertEqual(level_for(balance), level, f"баланс {balance}")

    def test_level_for_negative_is_basic(self):
        from loyalty.models import level_for

        self.assertEqual(level_for(-100), "basic")

    def test_balance_of_sums_positive_and_negative(self):
        from loyalty.models import balance_of

        add_txn("u_bal", 100, "runnerRun")
        add_txn("u_bal", 50, "purchase")
        add_txn("u_bal", -30, "redeem")
        self.assertEqual(balance_of("u_bal"), 120)

    def test_balance_of_unknown_user_zero(self):
        from loyalty.models import balance_of

        self.assertEqual(balance_of("u_nobody"), 0)


class LoyaltyAccountCacheTests(ApiTestCase):
    """Карточка лояльности GET /loyalty/account (баланс/уровень/история) — read-only,
    кэш по uid + инвалидация из add_txn (D-29). Авторитетные проверки — мимо кэша."""

    phone = "+79990002010"

    def test_account_returns_balance_level_history(self):
        add_txn(self.uid, 100, "manual", "начисление")
        add_txn(self.uid, 100, "runnerRun", "бег")
        d = self.api_get("/v1/loyalty/account").json()
        # balance — тратимое; баллы за бег созревают 3 дня (решение 28.09.2026).
        self.assertEqual(d["balance"], 100)
        self.assertEqual(d["total"], 200)
        self.assertEqual(d["pending"], 100)
        self.assertEqual(d["level"], "silver")  # уровень — по всему балансу
        self.assertEqual(len(d["transactions"]), 2)

    def test_account_cache_invalidated_on_txn(self):
        self.assertEqual(self.api_get("/v1/loyalty/account").json()["balance"], 0)  # кэш
        add_txn(self.uid, 250, "manual")  # add_txn сбрасывает кэш
        d = self.api_get("/v1/loyalty/account").json()
        self.assertEqual(d["balance"], 250)
        self.assertEqual(d["level"], "silver")  # пересчитано (баланс+уровень)

    def test_redeem_uses_authoritative_balance_not_cache(self):
        # Баланс 100, кэшируем показ. Redeem обязан списывать по РЕАЛЬНОМУ балансу,
        # а не по (потенциально устаревшему) кэшу — иначе можно уйти в минус.
        add_txn(self.uid, 100, "manual")
        _order_with_points(self.uid, "o1", 100)
        _order_with_points(self.uid, "o2", 50)
        self.assertEqual(self.api_get("/v1/loyalty/account").json()["balance"], 100)  # кэш
        r = self.api_post("/v1/loyalty/redeem", {"amount": 100, "orderId": "o1"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["balance"], 0)  # списано авторитетно
        # Повторная трата — отклонена по реальному балансу 0, не по кэшу «100».
        r2 = self.api_post("/v1/loyalty/redeem", {"amount": 50, "orderId": "o2"})
        self.assertEqual(r2.status_code, 400)
        # А показ после списания — свежий (redeem инвалидировал через add_txn).
        self.assertEqual(self.api_get("/v1/loyalty/account").json()["balance"], 0)
