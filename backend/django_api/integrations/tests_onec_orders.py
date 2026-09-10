"""Обратный поток обмена с 1С: заказы МАТА → 1С и статусы обратно (D-62 §5).

Здесь речь о деньгах покупателя, поэтому проверяем не «работает ли», а «что будет,
когда пойдёт не так»: оборванная связь, повторный запрос, чужой заказ, статус,
пришедший дважды.
"""
import os
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone

from catalog.models import Product
from common.testutils import ApiTestCase
from integrations.models import OneCExchange
from notifications.models import Notification
from orders.models import Order

TOKEN = "test-1c-token"
PULL = "/v1/integrations/1c/orders"
ACK = "/v1/integrations/1c/orders/ack"
STATUS = "/v1/integrations/1c/orders/status"


@override_settings(INTEGRATION_1C_TOKEN=TOKEN)
class OneCOrderFlowTests(TestCase):
    def setUp(self):
        Product.objects.create(id="p1", name="Кроссовки", category_id="shoes",
                               price=11990, article="AR-X1", external_id="GUID-1")
        self.order = self._order("MATA-1")
        # Создание заказа само по себе шлёт уведомление (orders/signals.py).
        # Чистим, чтобы считать ровно то, что породил обмен с 1С.
        Notification.objects.all().delete()

    def _order(self, oid, *, payment="paid", payment_id=None, user="u1"):
        """По умолчанию — заказ, оплату которого подтвердила ЮKassa (D-72)."""
        if payment_id is None:
            payment_id = f"yk-{oid}" if payment == "paid" else ""
        return Order.objects.create(
            user_id=user, order_id=oid, total=11990, payment_status=payment,
            payment_id=payment_id, points_redeemed=100,
            payload={
                "id": oid,
                "deliveryCost": 0,
                "items": [{"productId": "p1", "productName": "Кроссовки",
                           "size": "42", "color": "Чёрный", "quantity": 1,
                           "price": 11990}],
                "checkoutData": {"name": "Михаил", "phone": "+79148278470",
                                 "email": "m@example.com", "city": "Якутск",
                                 "street": "Ленина", "house": "1", "apartment": "5",
                                 "deliveryType": "courier", "paymentType": "online"},
            },
        )

    def _get(self, url, token=TOKEN):
        headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"} if token else {}
        return self.client.get(url, **headers)

    def _post(self, url, payload, token=TOKEN):
        headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"} if token else {}
        return self.client.post(url, payload, content_type="application/json", **headers)

    # ── выдача ──────────────────────────────────────────────────────────────

    def test_token_required_everywhere(self):
        self.assertEqual(self.client.get(PULL).status_code, 401)
        self.assertEqual(self.client.post(ACK, {}, content_type="application/json").status_code, 401)
        self.assertEqual(self.client.post(STATUS, {}, content_type="application/json").status_code, 401)

    def test_order_has_everything_warehouse_needs(self):
        body = self._get(PULL).json()
        self.assertEqual(len(body["orders"]), 1)
        o = body["orders"][0]
        self.assertEqual(o["orderId"], "MATA-1")
        self.assertEqual(o["customer"]["phone"], "+79148278470")
        self.assertEqual(o["total"], 11990)
        self.assertEqual(o["pointsRedeemed"], 100)
        self.assertEqual(o["address"], "Якутск, Ленина, 1, 5")
        item = o["items"][0]
        # Главное: позиция названа так, как её знает 1С, а не только нашим id.
        self.assertEqual(item["id"], "GUID-1")
        self.assertEqual(item["article"], "AR-X1")
        self.assertEqual(item["size"], "42")
        self.assertEqual(item["qty"], 1)

    def test_unpaid_order_is_not_handed_over(self):
        """Ждёт оплату — на склад не уходит, иначе соберут неоплаченное."""
        self._order("MATA-2", payment="pending")
        ids = [o["orderId"] for o in self._get(PULL).json()["orders"]]
        self.assertEqual(ids, ["MATA-1"])

    def test_paid_order_is_handed_over(self):
        self._order("MATA-3", payment="paid")
        ids = [o["orderId"] for o in self._get(PULL).json()["orders"]]
        self.assertIn("MATA-3", ids)

    def test_order_needing_no_payment_is_not_handed_over(self):
        """«Оплата не требуется» больше не пропуск на склад: путь один — СБП (D-72)."""
        self._order("MATA-N", payment="none")
        ids = [o["orderId"] for o in self._get(PULL).json()["orders"]]
        self.assertNotIn("MATA-N", ids)

    def test_paid_without_yookassa_payment_is_not_handed_over(self):
        """«Оплачено» без номера платежа ЮKassa (режим разработки) — не на склад."""
        self._order("MATA-D", payment="paid", payment_id="")
        ids = [o["orderId"] for o in self._get(PULL).json()["orders"]]
        self.assertNotIn("MATA-D", ids)

    def test_oldest_first(self):
        old = self._order("MATA-OLD")
        Order.objects.filter(pk=old.pk).update(
            created_at=timezone.now() - timezone.timedelta(days=2))
        ids = [o["orderId"] for o in self._get(PULL).json()["orders"]]
        self.assertEqual(ids[0], "MATA-OLD")

    def test_limit_is_capped(self):
        for i in range(3):
            self._order(f"MATA-L{i}")
        self.assertEqual(len(self._get(PULL + "?limit=2").json()["orders"]), 2)
        # Мусор в limit не должен ронять выдачу.
        self.assertEqual(self._get(PULL + "?limit=abc").status_code, 200)

    # ── подтверждение приёма ────────────────────────────────────────────────

    def test_order_stays_in_queue_until_acked(self):
        """Оборвалась связь после выдачи — заказ обязан прийти снова."""
        self._get(PULL)
        self.assertEqual(len(self._get(PULL).json()["orders"]), 1)

        r = self._post(ACK, {"orderIds": ["MATA-1"]})
        self.assertEqual(r.json()["acked"], 1)
        self.assertEqual(self._get(PULL).json()["orders"], [])

    def test_repeat_ack_is_not_an_error(self):
        self._post(ACK, {"orderIds": ["MATA-1"]})
        r = self._post(ACK, {"orderIds": ["MATA-1"]})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["acked"], 0)

    def test_ack_reports_unknown_orders(self):
        r = self._post(ACK, {"orderIds": ["MATA-1", "нет-такого"]})
        self.assertEqual(r.json()["acked"], 1)
        self.assertEqual(r.json()["unknown"], ["нет-такого"])

    def test_ack_wants_a_list(self):
        self.assertEqual(self._post(ACK, {"orderIds": "MATA-1"}).status_code, 400)

    # ── статусы обратно ─────────────────────────────────────────────────────

    def test_status_moves_order_and_notifies_customer(self):
        r = self._post(STATUS, {"orders": [
            {"orderId": "MATA-1", "status": "shipped", "number": "УТ-000123"}]})
        self.assertEqual(r.json()["updated"], 1)
        o = Order.objects.get(order_id="MATA-1")
        self.assertEqual(o.status, "shipped")
        self.assertEqual(o.onec_status, "shipped")
        self.assertEqual(o.onec_number, "УТ-000123")
        n = Notification.objects.filter(user_id="u1").latest("id")
        self.assertEqual(n.title, "Заказ отправлен")
        self.assertEqual(n.order_id, "MATA-1")

    def test_warehouse_stages_do_not_change_order_status(self):
        """«Принят» и «собран» — кухня склада: покупателю сообщаем, статус не двигаем."""
        self._post(STATUS, {"orders": [{"orderId": "MATA-1", "status": "assembled"}]})
        o = Order.objects.get(order_id="MATA-1")
        self.assertEqual(o.status, "pending")       # общий статус на месте
        self.assertEqual(o.onec_status, "assembled")
        self.assertEqual(Notification.objects.filter(user_id="u1").count(), 1)

    def test_same_status_twice_does_not_spam(self):
        self._post(STATUS, {"orders": [{"orderId": "MATA-1", "status": "shipped"}]})
        r = self._post(STATUS, {"orders": [{"orderId": "MATA-1", "status": "shipped"}]})
        self.assertEqual(r.json()["updated"], 0)
        self.assertEqual(Notification.objects.filter(user_id="u1").count(), 1)

    def test_cancel_maps_to_our_status(self):
        self._post(STATUS, {"orders": [{"orderId": "MATA-1", "status": "canceled"}]})
        self.assertEqual(Order.objects.get(order_id="MATA-1").status, "cancelled")

    def test_status_takes_order_off_the_queue(self):
        """Статус пришёл — значит документ у 1С есть, даже если ack потерялся."""
        self._post(STATUS, {"orders": [{"orderId": "MATA-1", "status": "accepted"}]})
        self.assertEqual(self._get(PULL).json()["orders"], [])

    def test_unknown_status_reported_not_applied(self):
        r = self._post(STATUS, {"orders": [{"orderId": "MATA-1", "status": "чтототам"}]})
        self.assertEqual(r.json()["updated"], 0)
        self.assertTrue(r.json()["errors"])
        self.assertEqual(Order.objects.get(order_id="MATA-1").status, "pending")

    def test_unknown_order_reported(self):
        r = self._post(STATUS, {"orders": [{"orderId": "нет-такого", "status": "shipped"}]})
        self.assertTrue(any("нет-такого" in e for e in r.json()["errors"]))

    # ── журнал ──────────────────────────────────────────────────────────────

    def test_everything_lands_in_the_journal(self):
        self._get(PULL)
        self._post(ACK, {"orderIds": ["MATA-1"]})
        self._post(STATUS, {"orders": [{"orderId": "MATA-1", "status": "shipped"}]})
        ops = list(OneCExchange.objects.values_list("operation", flat=True))
        self.assertIn("orders", ops)
        self.assertIn("order-status", ops)


@override_settings(INTEGRATION_1C_TOKEN=TOKEN)
class UnpaidOrderStaysOffWarehouseTests(ApiTestCase):
    """Сквозная проверка через API: на склад — только оплата, подтверждённая ЮKassa (D-72).

    Тесты выше создают заказ сразу с нужным статусом оплаты и поэтому не видели
    главного: API само рождало каждый заказ как «оплата не требуется».
    """
    phone = "+79990002092"

    def setUp(self):
        super().setUp()
        Product.objects.create(id="p-e2e", name="Футболка", category_id="wear", price=500)

    def _pull(self):
        r = self.client.get(PULL, HTTP_AUTHORIZATION=f"Bearer {TOKEN}")
        return [o["orderId"] for o in r.json()["orders"]]

    def _order(self, oid, pay_type="sbp"):
        r = self.api_post("/v1/orders", {
            "id": oid, "total": 500,
            "items": [{"productId": "p-e2e", "quantity": 1}],
            "checkoutData": {"paymentType": pay_type},
        })
        self.assertEqual(r.status_code, 200, r.content)

    @mock.patch.dict(os.environ, {"PAYMENT_PROVIDER": "yookassa"})
    def test_order_reaches_warehouse_only_after_confirmed_payment(self):
        self._order("MATA-E1")
        self.assertNotIn("MATA-E1", self._pull())
        Order.objects.filter(order_id="MATA-E1").update(payment_status="paid",
                                                       payment_id="yk-e1")
        self.assertIn("MATA-E1", self._pull())

    @mock.patch.dict(os.environ, {"PAYMENT_PROVIDER": "yookassa"})
    def test_pay_on_delivery_choice_does_not_bypass_payment(self):
        """Старый клиент ещё шлёт «при получении» — оплату это не отменяет."""
        self._order("MATA-E2", "cod")
        self.assertNotIn("MATA-E2", self._pull())

    @mock.patch.dict(os.environ, {"DJANGO_DEBUG": "1"})
    def test_dev_shortcut_paid_order_never_reaches_warehouse(self):
        """Режим разработки «оплачивает» без ЮKassa — такой заказ на склад не идёт."""
        self._order("MATA-E3")
        self.api_post("/v1/orders/MATA-E3/pay", {})
        self.assertEqual(Order.objects.get(order_id="MATA-E3").payment_status, "paid")
        self.assertNotIn("MATA-E3", self._pull())
