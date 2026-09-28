"""Кошелёк баллов: одинаковые правила списания на всех путях (аудит B02) и
атомарность — блокировка кошелька, нет двойных начислений и сверхрасхода (B03).

Конкурентные тесты — TransactionTestCase + потоки: у каждого потока своё соединение
с PostgreSQL, транзакции настоящие (в CI и в контейнере — тот же Postgres).
"""
import threading
import time
from unittest import mock

from django.db import connection, connections
from django.test import TransactionTestCase

from common.testutils import ApiTestCase
from loyalty.models import LoyaltyTransaction, add_txn, balance_of
from orders.models import Order


def _order(uid, oid, total, points, payment_status="pending"):
    return Order.objects.create(
        user_id=uid, order_id=oid, total=total, points_redeemed=points,
        payment_status=payment_status, status="pending", payload={"id": oid},
    )


class LegacyRedeemRulesTests(ApiTestCase):
    """POST /v1/loyalty/redeem (старые сборки Store) — те же правила, что при оформлении."""

    phone = "+79990002301"

    def setUp(self):
        super().setUp()
        add_txn(self.uid, 1000, "runnerRun", "Баллы за бег",
                available_at=None)  # созревшие (правило 3 дней — tests_maturation)

    def _redeem(self, amount, oid):
        body = {"amount": amount, "description": "Оплата баллами"}
        if oid is not None:
            body["orderId"] = oid
        return self.api_post("/v1/loyalty/redeem", body)

    def test_without_order_id_nothing_is_spent(self):
        r = self._redeem(900, None)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.balance(), 1000)

    def test_unknown_order_nothing_is_spent(self):
        """Раньше: 900 баллов на несуществующий заказ — списывалось, 30% не проверялись,
        а потом заказ с тем же id проходил с «уже списанными» 900."""
        r = self._redeem(900, "SS-NOPE")
        self.assertIn(r.status_code, (400, 404))
        self.assertEqual(self.balance(), 1000)
        # И заказ, оформленный после, не прячется за «уже списанным»: 900 > 30% от 1000.
        from orders.tests import _catalog_items

        r = self.api_post("/v1/orders", {
            "id": "SS-NOPE", "total": 100, "pointsRedeemed": 900,
            "items": _catalog_items(1000),
        })
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.balance(), 1000)

    def test_more_than_30_percent_refused(self):
        _order(self.uid, "SS-L30", total=600, points=400)  # 400 из 1000 = 40%
        r = self._redeem(400, "SS-L30")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.balance(), 1000)

    def test_below_minimum_refused(self):
        _order(self.uid, "SS-LMIN", total=951, points=49)
        r = self._redeem(49, "SS-LMIN")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.balance(), 1000)

    def test_amount_must_match_the_order(self):
        _order(self.uid, "SS-LEQ", total=700, points=300)
        r = self._redeem(250, "SS-LEQ")  # заказ получил скидку 300, а просят списать 250
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.balance(), 1000)

    def test_canceled_order_is_not_charged(self):
        _order(self.uid, "SS-LCX", total=700, points=300, payment_status="canceled")
        r = self._redeem(300, "SS-LCX")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.balance(), 1000)

    def test_valid_order_is_charged_once(self):
        """Заказ с баллами, по которому списания ещё нет, — списываем ровно раз."""
        _order(self.uid, "SS-LOK", total=700, points=300)
        r = self._redeem(300, "SS-LOK")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["balance"], 700)
        self.assertEqual(r.json()["spent"], 300)
        r = self._redeem(300, "SS-LOK").json()
        self.assertTrue(r["deduped"])
        self.assertEqual(self.balance(), 700)

    def test_old_store_flow_order_then_redeem(self):
        """Выпущенный Store: POST /orders (сервер списал) → /loyalty/redeem — 200, без повтора."""
        from orders.tests import _catalog_items

        r = self.api_post("/v1/orders", {
            "id": "SS-LST", "total": 700, "pointsRedeemed": 300,
            "items": _catalog_items(1000),
        })
        self.assertEqual(r.status_code, 200)
        r = self._redeem(300, "SS-LST")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["deduped"])
        self.assertEqual(self.balance(), 700)


class RedeemForOrderRulesTests(ApiTestCase):
    """redeem_for_order не прекращает проверки, если по заказу уже есть списание."""

    phone = "+79990002302"

    def test_existing_redeem_is_still_checked(self):
        from orders.awards import redeem_for_order

        add_txn(self.uid, 1000, "runnerRun", "Баллы за бег",
                available_at=None)  # созревшие (правило 3 дней — tests_maturation)
        # Списание, сделанное в обход правил (старый путь), — 90% заказа.
        add_txn(self.uid, -900, "redeem", "Оплата баллами", "SS-EX")
        self.assertNotEqual(redeem_for_order(self.uid, "SS-EX", 900, 1000), "")

    def test_repeat_with_same_amount_is_idempotent(self):
        from orders.awards import redeem_for_order

        add_txn(self.uid, 1000, "runnerRun", "Баллы за бег",
                available_at=None)  # созревшие (правило 3 дней — tests_maturation)
        self.assertEqual(redeem_for_order(self.uid, "SS-RP", 300, 1000), "")
        self.assertEqual(redeem_for_order(self.uid, "SS-RP", 300, 1000), "")
        self.assertEqual(self.balance(), 700)

    def test_repeat_with_other_amount_refused(self):
        from orders.awards import redeem_for_order

        add_txn(self.uid, 1000, "runnerRun", "Баллы за бег",
                available_at=None)  # созревшие (правило 3 дней — tests_maturation)
        self.assertEqual(redeem_for_order(self.uid, "SS-RO", 300, 1000), "")
        self.assertNotEqual(redeem_for_order(self.uid, "SS-RO", 200, 1000), "")
        self.assertEqual(self.balance(), 700)


_real_balance_of = balance_of


def _slow_balance_of(user_id):
    """Баланс с паузой: расширяет окно гонки «прочитал баланс → записал»,
    чтобы без блокировки кошелька гонка воспроизводилась детерминированно."""
    value = _real_balance_of(user_id)
    time.sleep(0.3)
    return value


def _run_parallel(n, fn):
    """Запустить fn(i) в n потоках разом. Возвращает (результаты, ошибки)."""
    barrier = threading.Barrier(n)
    results, errors = [None] * n, []

    def worker(i):
        try:
            barrier.wait()
            results[i] = fn(i)
        except Exception as e:  # noqa: BLE001 — ошибка в потоке = провал теста
            errors.append(repr(e))
        finally:
            connections.close_all()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    return results, errors


class WalletConcurrencyTests(TransactionTestCase):
    """B03: гонки на настоящем PostgreSQL — нет сверхрасхода и двойных начислений."""

    UID = "u_wallet_race"

    def setUp(self):
        if connection.vendor != "postgresql":
            self.skipTest("конкурентный тест — только на PostgreSQL")

    def test_parallel_redeems_do_not_overspend(self):
        from orders.awards import redeem_for_order

        add_txn(self.UID, 300, "runnerRun", "Баллы за бег",
                available_at=None)  # созревшие (правило 3 дней — tests_maturation)
        with mock.patch("loyalty.models.balance_of", _slow_balance_of):
            results, errors = _run_parallel(
                5, lambda i: redeem_for_order(self.UID, f"SS-RACE{i}", 300, 1000)
            )
        self.assertEqual(errors, [])
        self.assertEqual(sum(1 for r in results if r == ""), 1, results)
        self.assertEqual(_real_balance_of(self.UID), 0)

    def test_parallel_redeems_same_order_spend_once(self):
        from orders.awards import redeem_for_order

        add_txn(self.UID, 1000, "runnerRun", "Баллы за бег",
                available_at=None)  # созревшие (правило 3 дней — tests_maturation)
        with mock.patch("loyalty.models.balance_of", _slow_balance_of):
            results, errors = _run_parallel(
                5, lambda i: redeem_for_order(self.UID, "SS-SAME", 300, 1000)
            )
        self.assertEqual(errors, [])
        self.assertEqual(
            LoyaltyTransaction.objects.filter(
                user_id=self.UID, order_id="SS-SAME", source="redeem"
            ).count(),
            1,
        )
        self.assertEqual(_real_balance_of(self.UID), 700)

    def test_parallel_accruals_award_once(self):
        """Вебхук ЮKassa и перепроверка статуса приходят одновременно — баллы за
        покупку и бонус за первый заказ начисляются по одному разу."""
        from orders.awards import accrue_purchase_points

        order = _order(self.UID, "SS-ACC", total=1000, points=0, payment_status="paid")
        with mock.patch("loyalty.models.balance_of", _slow_balance_of):
            _, errors = _run_parallel(5, lambda i: accrue_purchase_points(order))
        self.assertEqual(errors, [])
        rows = LoyaltyTransaction.objects.filter(user_id=self.UID)
        self.assertEqual(rows.filter(source="purchase").count(), 1)
        self.assertEqual(rows.filter(source="registration").count(), 1)
        self.assertEqual(_real_balance_of(self.UID), 100 + 50)

    def test_parallel_refunds_return_once(self):
        """Отмена оплаты из двух мест сразу — списанные баллы возвращаются один раз."""
        from orders.awards import redeem_for_order, refund_redeemed_points

        add_txn(self.UID, 1000, "runnerRun", "Баллы за бег",
                available_at=None)  # созревшие (правило 3 дней — tests_maturation)
        self.assertEqual(redeem_for_order(self.UID, "SS-REF", 300, 1000), "")
        order = _order(self.UID, "SS-REF", total=700, points=300)
        with mock.patch("loyalty.models.balance_of", _slow_balance_of), \
                mock.patch("orders.awards._sum", _slow_sum()):
            _, errors = _run_parallel(4, lambda i: refund_redeemed_points(order))
        self.assertEqual(errors, [])
        self.assertEqual(_real_balance_of(self.UID), 1000)


def _slow_sum():
    from orders import awards

    real = awards._sum

    def slow(order, source):
        value = real(order, source)
        time.sleep(0.2)
        return value

    return slow


class WalletIndexMigrationTests(TransactionTestCase):
    """Миграция 0004: уникальные ключи операций и безопасность при старых дублях."""

    def setUp(self):
        if connection.vendor != "postgresql":
            self.skipTest("частичные индексы — только PostgreSQL")
        import importlib
        from types import SimpleNamespace

        self.mig = importlib.import_module("loyalty.migrations.0004_wallet_unique_ops")
        self.editor = SimpleNamespace(connection=connection)

    def tearDown(self):
        # Вернуть индексы как после migrate — другим тестам.
        LoyaltyTransaction.objects.all().delete()
        self.mig.create_indexes(None, self.editor)

    def _has_index(self, name):
        with connection.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_indexes WHERE indexname = %s", [name])
            return cur.fetchone() is not None

    def test_index_blocks_second_purchase_for_order(self):
        from django.db import IntegrityError

        self.assertTrue(self._has_index("loyalty_txn_uniq_order_op"))
        add_txn("u_idx", 100, "purchase", "Покупка", "SS-IDX")
        with self.assertRaises(IntegrityError):
            add_txn("u_idx", 100, "purchase", "Покупка", "SS-IDX")
        # Частичные возвраты по заказу — несколько строк, это законно.
        add_txn("u_idx", 10, "redeem_refund", "Возврат", "SS-IDX")
        add_txn("u_idx", 10, "redeem_refund", "Возврат", "SS-IDX")

    def test_existing_duplicates_do_not_break_migration(self):
        self.mig.drop_indexes(None, self.editor)
        add_txn("u_dup", 100, "purchase", "Покупка", "SS-DUP")
        add_txn("u_dup", 100, "purchase", "Покупка", "SS-DUP")
        add_txn("u_dup", 50, "registration", "Бонус")
        self.mig.create_indexes(None, self.editor)  # не падает
        self.assertFalse(self._has_index("loyalty_txn_uniq_order_op"))  # пропущен
        self.assertTrue(self._has_index("loyalty_txn_uniq_registration"))  # дублей нет
