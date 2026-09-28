"""Жизненный цикл возврата (аудит B04).

«В обработке» ≠ «проведён»: деньги, баллы и статус заказа меняются только по
подтверждению ЮKassa. Уведомление о возврате обрабатывается отдельно от платежа,
повтор уведомления ничего не проводит второй раз, а таймаут — это неизвестный
исход, который досверяется, а не «не прошёл».
"""
import io
import json
import os
import urllib.error
from datetime import timedelta
from unittest import mock

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from loyalty.models import add_txn, balance_of
from orders.models import Order, OrderReturn
from orders.returns import ReturnError, make_return

UID = "u_rfl"
_YK = {"YOOKASSA_SHOP_ID": "654321", "YOOKASSA_SECRET_KEY": "test_secret_key"}

PAYLOAD = {
    "id": "SS-L",
    "deliveryCost": 300,
    "items": [
        {"productName": "Куртка", "price": 3000, "quantity": 1},
        {"productName": "Футболка", "price": 1000, "quantity": 2},
    ],
    "checkoutData": {"phone": "+79148278470", "email": "buyer@example.test"},
}


class _Provider:
    """Поддельная ЮKassa: помнит возвраты по ключу идемпотентности, как настоящая."""

    def __init__(self, status="succeeded"):
        self.status = status
        self.by_key = {}
        self.calls = []

    def __call__(self, method, url, payload=None, headers=None):
        self.calls.append((method, url, payload, headers))
        if method == "POST" and url.endswith("/refunds"):
            key = headers["Idempotence-Key"]
            if key not in self.by_key:
                self.by_key[key] = {
                    "id": f"rf_{len(self.by_key) + 1}", "status": self.status,
                    "payment_id": payload["payment_id"], "amount": payload["amount"],
                }
            return dict(self.by_key[key])
        if method == "GET" and "/refunds/" in url:
            rid = url.rsplit("/", 1)[1]
            for r in self.by_key.values():
                if r["id"] == rid:
                    return dict(r, status=self.status)
            raise AssertionError(f"нет возврата {rid}")
        raise AssertionError(f"неожиданный запрос {method} {url}")


class RefundLifecycleTests(TestCase):
    def setUp(self):
        cache.clear()
        env = mock.patch.dict(os.environ, _YK)
        env.start()
        self.addCleanup(env.stop)
        self.order = Order.objects.create(
            user_id=UID, order_id="SS-L", total=4400, points_redeemed=900,
            payment_status="paid", payment_id="pay_L", status="paid", payload=PAYLOAD,
        )
        add_txn(UID, 2000, "runnerRun", "Баллы за бег")
        add_txn(UID, -900, "redeem", "Оплата баллами", "SS-L")
        add_txn(UID, 440, "purchase", "Покупка на 4400 ₽", "SS-L")
        self.start = balance_of(UID)

    def _return(self, lines, provider):
        with mock.patch("orders.payment._http", side_effect=provider):
            ret = make_return(self.order.pk, lines, by="tester")
        self.order.refresh_from_db()
        return ret

    def _webhook(self, provider, refund_id, event="refund.succeeded"):
        with mock.patch("orders.payment._http", side_effect=provider):
            r = self.client.post(
                "/v1/payments/webhook",
                data=json.dumps({"event": event, "object": {
                    "id": refund_id, "payment_id": "pay_L", "status": "succeeded"}}),
                content_type="application/json",
            )
        self.order.refresh_from_db()
        return r

    def _reconcile(self, provider, age=timedelta(minutes=5)):
        from orders.returns import reconcile_returns

        OrderReturn.objects.update(created_at=timezone.now() - age)
        with mock.patch("orders.payment._http", side_effect=provider):
            stats = reconcile_returns()
        self.order.refresh_from_db()
        return stats

    # ── pending ≠ done ────────────────────────────────────────────────────

    def test_pending_refund_is_not_done(self):
        ret = self._return([1], _Provider(status="pending"))
        self.assertEqual(ret.status, "pending")
        self.assertEqual(ret.refund_id, "rf_1")
        self.assertEqual(self.order.payment_status, "paid")
        self.assertEqual(balance_of(UID), self.start, "баллы — только после подтверждения")

    def test_refund_webhook_completes_pending_refund_once(self):
        yk = _Provider(status="pending")
        ret = self._return([1], yk)
        yk.status = "succeeded"

        r = self._webhook(yk, "rf_1")
        self.assertEqual(r.status_code, 200, r.content)
        ret.refresh_from_db()
        self.assertEqual(ret.status, "done")
        self.assertEqual(self.order.payment_status, "partially_refunded")
        after = balance_of(UID)
        self.assertEqual(after, self.start + ret.points_returned - ret.points_revoked)
        self.assertGreater(ret.points_returned, 0)

        self._webhook(yk, "rf_1")  # ЮKassa повторяет уведомление
        self._reconcile(yk)
        self.assertEqual(balance_of(UID), after, "повтор не проводит баллы второй раз")
        self.assertEqual(OrderReturn.objects.get().status, "done")

    def test_refund_webhook_does_not_ask_about_a_payment(self):
        """Номер возврата — не номер платежа: запрос GET /payments/rf_… не нужен."""
        yk = _Provider(status="pending")
        self._return([1], yk)
        yk.status = "succeeded"
        self._webhook(yk, "rf_1")
        self.assertFalse([c for c in yk.calls if "/payments/" in c[1]])

    def test_canceled_refund_fails_and_frees_the_items(self):
        yk = _Provider(status="pending")
        self._return([1], yk)
        yk.status = "canceled"
        self._webhook(yk, "rf_1", event="refund.canceled")
        self.assertEqual(OrderReturn.objects.get().status, "failed")
        self.assertEqual(self.order.payment_status, "paid")
        self.assertEqual(balance_of(UID), self.start)

        ret = self._return([1], _Provider())
        self.assertEqual(ret.status, "done")

    def test_full_return_confirmed_later_refunds_the_order(self):
        yk = _Provider(status="pending")
        self._return([0, 1, 2], yk)
        self.assertEqual(self.order.status, "paid")
        yk.status = "succeeded"
        self._webhook(yk, "rf_1")
        self.assertEqual(self.order.payment_status, "refunded")
        self.assertEqual(self.order.status, "cancelled")
        self.assertEqual(balance_of(UID), 2000)

    def test_confirmed_amount_must_match(self):
        yk = _Provider(status="pending")
        self._return([1], yk)
        for r in yk.by_key.values():
            r["amount"] = {"value": "1.00", "currency": "RUB"}
        yk.status = "succeeded"
        self._webhook(yk, "rf_1")
        self.assertEqual(OrderReturn.objects.get().status, "pending")
        self.assertEqual(balance_of(UID), self.start)

    def test_unknown_refund_is_acknowledged_not_retried(self):
        yk = _Provider()
        yk.by_key["x"] = {"id": "rf_other", "status": "succeeded", "payment_id": "pay_X",
                          "amount": {"value": "10.00", "currency": "RUB"}}
        r = self._webhook(yk, "rf_other")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["ok"])

    # ── таймаут = неизвестный исход ───────────────────────────────────────

    def _timeout(self, *args, **kwargs):
        raise TimeoutError("timed out")

    def test_timeout_is_uncertain_not_failed(self):
        with mock.patch("urllib.request.urlopen", side_effect=self._timeout):
            ret = make_return(self.order.pk, [1], by="tester")
        self.assertEqual(ret.status, "pending")
        self.assertTrue(ret.error)
        self.assertEqual(balance_of(UID), self.start)
        # Второй возврат по заказу — нельзя: первый мог пройти.
        with self.assertRaises(ReturnError):
            self._return([1], _Provider())

    def test_provider_5xx_is_uncertain(self):
        def boom(*args, **kwargs):
            raise urllib.error.HTTPError("u", 500, "err", {}, io.BytesIO(b"{}"))

        with mock.patch("urllib.request.urlopen", side_effect=boom):
            ret = make_return(self.order.pk, [1], by="tester")
        self.assertEqual(ret.status, "pending")

    def test_provider_4xx_is_a_definite_failure(self):
        def bad(*args, **kwargs):
            raise urllib.error.HTTPError("u", 400, "bad", {}, io.BytesIO(
                b'{"description": "invalid_request"}'))

        with mock.patch("urllib.request.urlopen", side_effect=bad):
            with self.assertRaises(ReturnError):
                make_return(self.order.pk, [1], by="tester")
        self.assertEqual(OrderReturn.objects.get().status, "failed")

    def test_reconcile_resends_with_the_same_key(self):
        with mock.patch("urllib.request.urlopen", side_effect=self._timeout):
            make_return(self.order.pk, [1], by="tester")
        yk = _Provider()
        stats = self._reconcile(yk)
        self.assertEqual(stats["done"], 1)
        ret = OrderReturn.objects.get()
        self.assertEqual(ret.status, "done")
        self.assertEqual(ret.refund_id, "rf_1")
        self.assertEqual(self.order.payment_status, "partially_refunded")
        # Повторная сверка — тот же возврат, без новых запросов на деньги.
        self._reconcile(yk)
        posts = [c for c in yk.calls if c[0] == "POST"]
        self.assertEqual(len(posts), 1)

    def test_reconcile_uses_the_same_key_as_the_first_request(self):
        seen = []

        def timeout_but_remember(req, timeout=None):
            seen.append(req.get_header("Idempotence-key"))
            raise TimeoutError("timed out")

        with mock.patch("urllib.request.urlopen", side_effect=timeout_but_remember):
            make_return(self.order.pk, [1], by="tester")
        yk = _Provider()
        self._reconcile(yk)
        self.assertEqual(yk.calls[0][3]["Idempotence-Key"], seen[0])

    def test_reconcile_asks_status_when_refund_id_known(self):
        yk = _Provider(status="pending")
        self._return([1], yk)
        yk.status = "succeeded"
        stats = self._reconcile(yk)
        self.assertEqual(stats["done"], 1)
        self.assertEqual(yk.calls[-1][0], "GET")

    def test_reconcile_leaves_fresh_returns_alone(self):
        yk = _Provider(status="pending")
        self._return([1], yk)
        stats = self._reconcile(yk, age=timedelta(seconds=10))
        self.assertEqual(stats, {"done": 0, "failed": 0, "waiting": 0, "errors": 0,
                                 "manual": 0})

    def test_reconcile_does_not_resend_after_a_day(self):
        """ЮKassa помнит ключ сутки — повтор позже мог бы вернуть деньги дважды."""
        with mock.patch("urllib.request.urlopen", side_effect=self._timeout):
            make_return(self.order.pk, [1], by="tester")
        yk = _Provider()
        stats = self._reconcile(yk, age=timedelta(days=2))
        self.assertEqual(stats["manual"], 1)
        self.assertFalse(yk.calls)
        self.assertEqual(OrderReturn.objects.get().status, "pending")

    def test_webhook_matches_refund_whose_number_we_never_got(self):
        """Ответ на запрос возврата не дошёл, а уведомление — дошло."""
        with mock.patch("urllib.request.urlopen", side_effect=self._timeout):
            ret = make_return(self.order.pk, [1], by="tester")
        yk = _Provider()
        yk.by_key["k"] = {"id": "rf_9", "status": "succeeded", "payment_id": "pay_L",
                          "amount": {"value": f"{ret.amount_kop / 100:.2f}",
                                     "currency": "RUB"}}
        self._webhook(yk, "rf_9")
        ret.refresh_from_db()
        self.assertEqual(ret.status, "done")
        self.assertEqual(ret.refund_id, "rf_9")
