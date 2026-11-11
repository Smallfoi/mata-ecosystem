"""Возвраты и отмены → 1С (D-123, паспорт §7.4).

Что проверяем: в очередь идёт только то, по чему деньги уже вернулись и что 1С
знает; номер возврата совпадает с номером заявки; одинаковые вещи склеиваются в
строку с количеством; повторный ack не ошибка; отмена отличается от возврата.
"""
import os
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone

from catalog.models import Product
from integrations.models import OneCExchange
from orders import cancel as oc
from orders import return_requests as rr
from orders.models import Order, OrderReturn
from orders.returns import make_return
from orders.tests_returns import _YK, _refund_ok

TOKEN = "test-1c-token"
PULL = "/v1/integrations/1c/returns"
ACK = "/v1/integrations/1c/returns/ack"


@override_settings(INTEGRATION_1C_TOKEN=TOKEN)
class OneCReturnsTests(TestCase):
    def setUp(self):
        Product.objects.create(id="p1", name="Кроссовки", category_id="shoes",
                               price=5000, article="AR-X1", external_id="GUID-1")
        Product.objects.create(id="p2", name="Футболка", category_id="tops",
                               price=1000, article="TS-1", external_id="GUID-2")
        self.order = Order.objects.create(
            user_id="u1", order_id="МАТА-11112222", total=7300, payment_status="paid",
            payment_id="yk-1", points_redeemed=0, onec_number="УТ-000777",
            onec_taken_at=timezone.now(), onec_status="delivered",
            onec_status_at=timezone.now(),
            payload={
                "id": "МАТА-11112222",
                "deliveryCost": 300,
                "items": [
                    {"productId": "p1", "productName": "Кроссовки", "size": "42",
                     "color": "Чёрный", "quantity": 1, "price": 5000},
                    {"productId": "p2", "productName": "Футболка", "size": "M",
                     "color": "Белый", "quantity": 2, "price": 1000},
                ],
                "checkoutData": {"name": "Михаил", "phone": "+79148278470",
                                 "email": "m@example.com", "paymentType": "online"},
            },
        )

    def _get(self, token=TOKEN):
        headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"} if token else {}
        return self.client.get(PULL, **headers)

    def _ack(self, body, token=TOKEN):
        headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"} if token else {}
        return self.client.post(ACK, body, content_type="application/json", **headers)

    def _refund(self, indexes, **kw):
        with mock.patch.dict(os.environ, _YK), \
                mock.patch("orders.payment._http", side_effect=_refund_ok):
            return make_return(self.order.pk, indexes, by="test", **kw)

    def test_token_required(self):
        self.assertEqual(self._get(token=None).status_code, 401)
        self.assertEqual(self._ack({"returnIds": []}, token=None).status_code, 401)

    def test_done_return_is_queued_with_items_and_money(self):
        ret = self._refund([1, 2])  # обе футболки
        body = self._get().json()["returns"]
        self.assertEqual(len(body), 1)
        row = body[0]
        self.assertEqual(row["returnId"], ret.number)
        self.assertEqual(row["returnId"], "МАТА-11112222-В1")
        self.assertEqual(row["type"], "return")
        self.assertEqual(row["orderId"], "МАТА-11112222")
        self.assertEqual(row["orderDocument"], "УТ-000777")
        # Две одинаковые футболки — одна строка с количеством.
        self.assertEqual(len(row["items"]), 1)
        item = row["items"][0]
        self.assertEqual((item["article"], item["id"], item["size"], item["qty"]),
                         ("TS-1", "GUID-2", "M", 2))
        self.assertEqual(item["refund"], 2000.0)
        self.assertEqual(row["amount"], 2000.0)
        self.assertEqual(row["deliveryRefund"], 0.0)
        self.assertTrue(OneCExchange.objects.filter(operation="returns").exists())

    def test_last_items_carry_delivery(self):
        self._refund([0, 1, 2])
        row = self._get().json()["returns"][0]
        self.assertEqual(row["deliveryRefund"], 300.0)
        self.assertEqual(row["amount"], 7300.0)

    def test_pending_or_failed_refund_is_not_queued(self):
        OrderReturn.objects.create(order=self.order, lines=[0], amount_kop=500000,
                                   status="pending", seq=1)
        OrderReturn.objects.create(order=self.order, lines=[1], amount_kop=100000,
                                   status="failed", seq=2)
        self.assertEqual(self._get().json()["returns"], [])

    def test_order_unknown_to_1c_is_not_queued(self):
        Order.objects.filter(pk=self.order.pk).update(onec_taken_at=None)
        self._refund([0])
        self.assertEqual(self._get().json()["returns"], [])

    def test_ack_removes_from_queue_and_keeps_document_number(self):
        ret = self._refund([0])
        r = self._ack({"returnIds": [ret.number, "МАТА-0-В9"],
                       "documents": {ret.number: "ВЗ-000045"}})
        self.assertEqual(r.json(), {"acked": 1, "unknown": ["МАТА-0-В9"]})
        self.assertEqual(self._get().json()["returns"], [])
        ret.refresh_from_db()
        self.assertEqual(ret.onec_number, "ВЗ-000045")
        # Повторный ack — не ошибка и ничего не ломает.
        self.assertEqual(self._ack({"returnIds": [ret.number]}).json()["acked"], 0)

    def test_request_number_matches_return_number(self):
        req = rr.create(self.order, "u1", [{"index": 0, "reason": "size"}], "store")
        rr.mark_received(req, "staff")
        with mock.patch.dict(os.environ, _YK), \
                mock.patch("orders.payment._http", side_effect=_refund_ok):
            req = rr.approve(req, "staff")
        row = self._get().json()["returns"][0]
        self.assertEqual(row["returnId"], req.number)
        self.assertEqual(row["items"][0]["reason"], "size")
        # Следующий возврат по заказу — следующий номер, без столкновений.
        nxt = self._refund([1])
        self.assertEqual(nxt.number, "МАТА-11112222-В2")

    def test_cancel_is_marked_as_cancel(self):
        Order.objects.filter(pk=self.order.pk).update(onec_status="assembled",
                                                      onec_status_at=timezone.now())
        self.order.refresh_from_db()
        with mock.patch.dict(os.environ, _YK), \
                mock.patch("orders.payment._http", side_effect=_refund_ok):
            self.assertEqual(oc.cancel_order(self.order, "u1")["status"], "requested")
            oc.confirm_cancel(self.order, "staff")
        row = self._get().json()["returns"][0]
        self.assertEqual(row["type"], "cancel")
        self.assertEqual(row["amount"], 7300.0)
