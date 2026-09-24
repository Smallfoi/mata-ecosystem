"""Тестовая оплата (D-97): пройти весь путь заказа без денег.

1С-разработчику нужно проверить цикл целиком — заказ, выгрузка в 1С, статусы.
Ключей ЮKassa ещё нет, а без номера платежа заказ в 1С не уходит: именно номер
платежа служит доказательством, что деньги прошли.

Поэтому отдельному аккаунту даётся право «оплачивать» без денег. Такой заказ
помечается тестовым у нас и в выгрузке — спутать его с продажей нельзя.
"""
from django.utils import timezone

from accounts.models import Account
from common.testutils import ApiTestCase
from integrations.onec_orders import order_to_json, pending_orders
from orders.lifecycle import HOLD_MINUTES, expire_unpaid
from orders.models import Order


class TestPaymentTests(ApiTestCase):
    phone = "+79990004410"

    def _order(self, order_id="SS-T1"):
        return Order.objects.create(
            user_id=self.uid, order_id=order_id, total=5000, status="pending",
            payment_status="pending",
            payload={"id": order_id, "items": [
                {"productName": "Кроссовки", "price": 5000, "quantity": 1},
            ]},
        )

    def test_ordinary_account_is_not_paid_for_free(self):
        """Без права заказ оплачивается обычным путём, а не «просто так»."""
        order = self._order()
        r = self.api_post(f"/v1/orders/{order.order_id}/pay", {})
        order.refresh_from_db()
        self.assertFalse(order.is_test)
        self.assertEqual(order.payment_id, "", "у обычного заказа не должно быть номера теста")
        # И на сборку такой заказ не уходит: номера платежа нет.
        self.assertNotIn(order.order_id, [o.order_id for o in pending_orders()])

    def test_test_payer_goes_through(self):
        Account.objects.filter(id=self.uid).update(test_payment=True)
        order = self._order("SS-T2")

        r = self.api_post(f"/v1/orders/{order.order_id}/pay", {})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "paid")
        self.assertTrue(body["test"])

        order.refresh_from_db()
        self.assertTrue(order.is_test)
        self.assertEqual(order.payment_status, "paid")
        self.assertEqual(order.status, "paid")
        self.assertTrue(order.payment_id.startswith("TEST-"))

    def test_test_order_reaches_1c_queue(self):
        """Главное: заказ доходит до 1С — иначе проверять нечего."""
        Account.objects.filter(id=self.uid).update(test_payment=True)
        order = self._order("SS-T3")
        self.api_post(f"/v1/orders/{order.order_id}/pay", {})

        queue = [o.order_id for o in pending_orders()]
        self.assertIn("SS-T3", queue)

    def test_payload_says_it_is_a_test(self):
        """1С должна видеть пометку, чтобы не провести тест как продажу."""
        Account.objects.filter(id=self.uid).update(test_payment=True)
        order = self._order("SS-T4")
        self.api_post(f"/v1/orders/{order.order_id}/pay", {})
        order.refresh_from_db()

        self.assertIs(order_to_json(order)["test"], True)

    def test_ordinary_order_payload_is_not_a_test(self):
        order = self._order("SS-T5")
        self.assertIs(order_to_json(order)["test"], False)

    def test_right_can_be_taken_away(self):
        """Проверка закончилась — право снимают, и оплата снова обычная."""
        Account.objects.filter(id=self.uid).update(test_payment=True)
        first = self._order("SS-T6")
        self.api_post(f"/v1/orders/{first.order_id}/pay", {})
        first.refresh_from_db()
        self.assertTrue(first.is_test)

        Account.objects.filter(id=self.uid).update(test_payment=False)
        second = self._order("SS-T7")
        self.api_post(f"/v1/orders/{second.order_id}/pay", {})
        second.refresh_from_db()
        self.assertFalse(second.is_test)

    def test_stale_test_order_is_canceled_without_asking_yookassa(self):
        """Платежа «TEST-…» в ЮKassa нет — спрашивать её про него нельзя."""
        from datetime import timedelta

        order = self._order("SS-T8")
        Order.objects.filter(pk=order.pk).update(
            is_test=True, payment_id="TEST-SS-T8",
            created_at=timezone.now() - timedelta(minutes=HOLD_MINUTES + 1),
        )

        stats = expire_unpaid()
        order.refresh_from_db()
        self.assertEqual(order.payment_status, "canceled")
        self.assertGreaterEqual(stats["canceled"], 1)
        self.assertEqual(stats["errors"], 0)
