"""Чек оплаты из ЮKassa уходит в 1С вместе с заказом (D-101)."""
import os
from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from integrations.onec_orders import order_to_json, pending_orders
from orders import payment_receipt
from orders.lifecycle import mark_paid
from orders.models import Order
from orders.payment import PaymentError, PaymentUncertain

RECEIPTS_ON = {"PAYMENT_RECEIPT": "1"}

YK_RECEIPT = {
    "id": "rt-1", "type": "payment", "payment_id": "yk-1", "status": "succeeded",
    "fiscal_document_number": "3986", "fiscal_storage_number": "9288000100115785",
    "fiscal_attribute": "2617603921", "registered_at": "2026-10-07T10:06:42.985Z",
}


def _order(oid="MATA-R1", **kw):
    fields = dict(user_id="u-receipt", order_id=oid, total=1000, payment_status="pending",
                  payment_id=f"yk-{oid}", payload={"items": [], "checkoutData": {}})
    fields.update(kw)
    return Order.objects.create(**fields)


def _receipts_on(test):
    """Касса подключена — на весь тест, включая setUp (декоратор класса setUp не задевает)."""
    patcher = mock.patch.dict(os.environ, RECEIPTS_ON)
    patcher.start()
    test.addCleanup(patcher.stop)


def _fetch(*items):
    return mock.patch("orders.payment_receipt.fetch_receipts", return_value=list(items))


class PaidOrderWaitsForReceiptTests(TestCase):
    @mock.patch.dict(os.environ, RECEIPTS_ON)
    def test_paid_order_waits_for_receipt(self):
        order = _order()
        mark_paid(order)
        order.refresh_from_db()
        self.assertEqual(order.receipt, {"status": payment_receipt.WAITING})
        self.assertIsNotNone(order.paid_at)

    def test_no_wait_when_receipts_are_off(self):
        """Касса не подключена — чека не будет, заказ не ждёт."""
        order = _order()
        mark_paid(order)
        order.refresh_from_db()
        self.assertEqual(order.receipt, {})
        self.assertIsNotNone(order.paid_at)

    @mock.patch.dict(os.environ, RECEIPTS_ON)
    def test_test_payment_has_no_receipt(self):
        """Тестовая оплата (D-97) идёт без денег и без чека — ждать нечего."""
        order = _order(is_test=True, payment_id="TEST-MATA-R1")
        mark_paid(order)
        order.refresh_from_db()
        self.assertEqual(order.receipt, {})

    @mock.patch.dict(os.environ, RECEIPTS_ON)
    def test_repeat_confirmation_does_not_reset_receipt(self):
        """ЮKassa повторяет уведомление — полученный чек не затирается ожиданием."""
        order = _order()
        mark_paid(order)
        with _fetch(YK_RECEIPT):
            payment_receipt.sync_waiting()
        mark_paid(order)
        order.refresh_from_db()
        self.assertEqual(order.receipt["status"], payment_receipt.SUCCEEDED)


class ReceiptSyncTests(TestCase):
    def setUp(self):
        _receipts_on(self)
        self.order = _order()
        mark_paid(self.order)
        self.order.refresh_from_db()

    def test_fiscal_details_are_stored(self):
        with _fetch(YK_RECEIPT) as fetch:
            self.assertEqual(payment_receipt.sync_waiting(), {"checked": 1, "done": 1})
        fetch.assert_called_once_with("yk-MATA-R1")
        self.order.refresh_from_db()
        self.assertEqual(payment_receipt.for_1c(self.order), {
            "id": "rt-1", "fiscalDocumentNumber": "3986",
            "fiscalStorageNumber": "9288000100115785", "fiscalAttribute": "2617603921",
            "registeredAt": "2026-10-07T10:06:42.985Z",
        })

    def test_receipt_still_in_cashbox_keeps_waiting(self):
        with _fetch(dict(YK_RECEIPT, status="pending")):
            self.assertEqual(payment_receipt.sync_waiting()["done"], 0)
        with _fetch():
            self.assertEqual(payment_receipt.sync_waiting()["done"], 0)
        self.order.refresh_from_db()
        self.assertEqual(self.order.receipt["status"], payment_receipt.WAITING)

    def test_refund_receipt_is_not_taken_for_payment(self):
        with _fetch(dict(YK_RECEIPT, type="refund", id="rt-refund")):
            payment_receipt.sync_waiting()
        self.order.refresh_from_db()
        self.assertEqual(self.order.receipt["status"], payment_receipt.WAITING)

    def test_network_failure_retries_next_pass(self):
        with mock.patch("orders.payment_receipt.fetch_receipts",
                        side_effect=PaymentUncertain("таймаут")):
            payment_receipt.sync_waiting()
        self.order.refresh_from_db()
        self.assertEqual(self.order.receipt["status"], payment_receipt.WAITING)

    def test_refused_request_stops_waiting(self):
        """ЮKassa отказала (например, касса не через неё) — повтор не поможет."""
        with mock.patch("orders.payment_receipt.fetch_receipts",
                        side_effect=PaymentError("ЮKassa 403: forbidden")):
            payment_receipt.sync_waiting()
        self.order.refresh_from_db()
        self.assertEqual(self.order.receipt["status"], payment_receipt.UNAVAILABLE)
        self.assertIsNone(payment_receipt.for_1c(self.order))

    def test_canceled_receipt_is_not_sent_as_fiscal(self):
        with _fetch(dict(YK_RECEIPT, status="canceled")):
            payment_receipt.sync_waiting()
        self.order.refresh_from_db()
        self.assertEqual(self.order.receipt["status"], payment_receipt.CANCELED)
        self.assertIsNone(payment_receipt.for_1c(self.order))


class ReceiptGoesToOneCTests(TestCase):
    def setUp(self):
        _receipts_on(self)
        self.order = _order()
        mark_paid(self.order)
        self.order.refresh_from_db()

    def _queue(self):
        return [o.order_id for o in pending_orders()]

    def test_order_waits_for_receipt_before_warehouse(self):
        self.assertEqual(self._queue(), [])

    def test_order_with_receipt_goes_with_fiscal_details(self):
        with _fetch(YK_RECEIPT):
            payment_receipt.sync_waiting()
        self.assertEqual(self._queue(), ["MATA-R1"])
        self.order.refresh_from_db()
        self.assertEqual(order_to_json(self.order)["receipt"]["fiscalDocumentNumber"], "3986")

    def test_broken_cashbox_does_not_stop_warehouse(self):
        """Чека нет полчаса — заказ уходит в 1С без него, сборка не встаёт."""
        Order.objects.filter(pk=self.order.pk).update(
            paid_at=timezone.now() - timedelta(minutes=payment_receipt.WAIT_MINUTES + 1))
        self.assertEqual(self._queue(), ["MATA-R1"])
        self.order.refresh_from_db()
        self.assertIsNone(order_to_json(self.order)["receipt"])

    def test_order_without_receipt_expectation_is_not_held(self):
        """Обычный заказ без ожидания чека (касса не подключена) — в очереди сразу."""
        other = _order("MATA-R2", payment_status="paid", paid_at=timezone.now())
        self.assertIn(other.order_id, self._queue())
        self.assertIsNone(order_to_json(other)["receipt"])
