"""Заявки покупателей на возврат (D-112): покупатель оформляет, магазин осматривает и решает.

Покупка как в tests_returns: куртка (позиция 0), две футболки (1, 2), доставка (3).
"""
import os
from datetime import timedelta
from unittest import mock

from django.utils import timezone

from common.testutils import ApiTestCase
from loyalty.models import add_txn
from orders import return_requests as rr
from orders.models import Order, ReturnRequest
from orders.tests_returns import _YK, PAYLOAD, _refund_ok


class ReturnRequestApiTests(ApiTestCase):
    phone = "+79990011201"

    def setUp(self):
        super().setUp()
        self.order = Order.objects.create(
            user_id=self.uid, order_id="SS-RR", total=4400, points_redeemed=900,
            payment_status="paid", payment_id="pay_rr", status="paid",
            payload=dict(PAYLOAD, id="SS-RR"),
        )
        add_txn(self.uid, 2000, "runnerRun", "Баллы за бег")
        add_txn(self.uid, -900, "redeem", "Оплата баллами", "SS-RR")

    def _create(self, lines, method="store"):
        return self.api_post("/v1/orders/SS-RR/return-requests",
                             {"lines": lines, "method": method})

    def test_options_list_goods_only(self):
        r = self.client.get("/v1/orders/SS-RR/return-options",
                            HTTP_AUTHORIZATION=f"Bearer {self.token}")
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertTrue(body["canReturn"])
        self.assertEqual([line["index"] for line in body["lines"]], [0, 1, 2])
        self.assertIn("size", body["reasons"])

    def test_customer_creates_request_and_line_becomes_busy(self):
        r = self._create([{"index": 1, "reason": "size"}])
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["status"], "awaiting")
        again = self._create([{"index": 1, "reason": "style"}])
        self.assertEqual(again.status_code, 409)

    def test_parcel_is_accepted_by_law(self):
        """КС 7-П: дистанционно купленное можно вернуть посылкой — не отклоняем."""
        r = self._create([{"index": 0, "reason": "size"}], method="parcel")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["method"], "parcel")

    def test_defect_needs_description(self):
        self.assertEqual(self._create([{"index": 0, "reason": "defect"}]).status_code, 400)
        r = self._create([{"index": 0, "reason": "defect", "comment": "отклеилась подошва"}])
        self.assertEqual(r.status_code, 201, r.content)
        self.assertTrue(ReturnRequest.objects.get(pk=r.json()["id"]).defect_claimed)

    def test_window_closed_for_good_item_but_open_for_defect(self):
        Order.objects.filter(pk=self.order.pk).update(
            created_at=timezone.now() - timedelta(days=rr.RETURN_DAYS + 1))
        self.assertEqual(self._create([{"index": 1, "reason": "size"}]).status_code, 400)
        r = self._create([{"index": 1, "reason": "defect", "comment": "дырка на шве"}])
        self.assertEqual(r.status_code, 201, r.content)

    def test_unpaid_order_cannot_be_returned(self):
        Order.objects.filter(pk=self.order.pk).update(payment_status="pending")
        self.assertEqual(self._create([{"index": 1, "reason": "size"}]).status_code, 400)

    def test_cancel_only_before_item_received(self):
        rid = self._create([{"index": 1, "reason": "size"}]).json()["id"]
        r = self.api_post(f"/v1/return-requests/{rid}/cancel", {})
        self.assertEqual(r.json()["status"], "canceled")
        # Отменили — вещь снова можно заявить.
        self.assertEqual(self._create([{"index": 1, "reason": "size"}]).status_code, 201)

    def test_other_user_cannot_see_order(self):
        other = Order.objects.create(user_id="u_other", order_id="SS-OT", total=1,
                                     payment_status="paid", payment_id="p")
        r = self.api_post("/v1/orders/SS-OT/return-requests",
                          {"lines": [{"index": 0, "reason": "size"}], "method": "store"})
        self.assertEqual(r.status_code, 404)
        self.assertFalse(other.return_requests.exists())


class ReturnRequestFlowTests(ApiTestCase):
    """Сторона магазина: получили → осмотрели → одобрили (деньги) или отказали."""
    phone = "+79990011202"

    def setUp(self):
        super().setUp()
        self.order = Order.objects.create(
            user_id=self.uid, order_id="SS-RF", total=4400, points_redeemed=900,
            payment_status="paid", payment_id="pay_rf", status="paid",
            payload=dict(PAYLOAD, id="SS-RF"),
        )
        add_txn(self.uid, 2000, "runnerRun", "Баллы за бег")
        add_txn(self.uid, -900, "redeem", "Оплата баллами", "SS-RF")
        self.req = rr.create(self.order, self.uid, [{"index": 1, "reason": "size"}], "store")

    def test_cannot_decide_before_item_is_received(self):
        with self.assertRaises(rr.RequestError):
            rr.approve(self.req, "staff")
        with self.assertRaises(rr.RequestError):
            rr.reject(self.req, "Следы носки", "staff")

    def test_approve_refunds_exactly_the_requested_line(self):
        rr.mark_received(self.req, "staff")
        with mock.patch.dict(os.environ, _YK), \
                mock.patch("orders.payment._http", side_effect=_refund_ok):
            req = rr.approve(self.req, "staff")
        self.assertEqual(req.status, ReturnRequest.APPROVED)
        self.assertEqual(req.order_return.lines, [1])
        self.assertEqual(req.order_return.status, "done")
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, "partially_refunded")

    def test_reject_needs_reason_shown_to_customer(self):
        rr.mark_received(self.req, "staff")
        with self.assertRaises(rr.RequestError):
            rr.reject(self.req, "", "staff")
        req = rr.reject(self.req, "Сняты фабричные ярлыки, следы носки", "staff")
        self.assertEqual(req.status, ReturnRequest.REJECTED)
        self.assertEqual(self.order.returns.count(), 0)

    def test_unbrought_request_expires(self):
        ReturnRequest.objects.filter(pk=self.req.pk).update(
            bring_until=timezone.now() - timedelta(minutes=1))
        self.assertEqual(rr.expire_stale(), 1)
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, ReturnRequest.EXPIRED)
        # Покупатель всё же пришёл — магазин может принять товар по истёкшей заявке.
        rr.mark_received(self.req, "staff")
