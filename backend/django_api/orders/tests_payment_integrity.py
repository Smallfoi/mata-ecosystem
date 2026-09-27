"""Целостность оплаты (аудит B01, B05).

B01 — заказ, переданный в оплату, заморожен: повтор того же заказа идемпотентен,
изменение состава или суммы отклоняется, а «оплачено» ставится, только если
платёж провайдера совпал с заказом (сумма, валюта, reference).

B05 — переходы оплаты явные: повторное «оплачено» не отменяет возврат и не
возвращает заказ в сборку, запоздалое «отменено» не отменяет оплаченный заказ.
"""
import json
import os
from unittest import mock

from common.testutils import ApiTestCase
from integrations.onec_orders import pending_orders
from loyalty.models import add_txn
from orders.models import Order

_YK_ENV = {
    "PAYMENT_PROVIDER": "yookassa",
    "YOOKASSA_SHOP_ID": "654321",
    "YOOKASSA_SECRET_KEY": "test_secret_key",
    "YOOKASSA_RETURN_URL": "https://example.test/orders",
}


def _items(total, pid="p-int-1", size="42", qty=1):
    from catalog.models import Product

    Product.objects.get_or_create(
        id=pid, defaults={"name": "Кроссовки", "category_id": "wear", "price": total}
    )
    return [{"productId": pid, "productName": "Кроссовки", "price": total,
             "size": size, "color": "black", "quantity": qty}]


def _yk(status="pending", pid="pay_1", amount=None, currency="RUB", reference=None):
    data = {"id": pid, "status": status,
            "confirmation": {"confirmation_url": f"https://yoomoney.ru/checkout/{pid}"}}
    if amount is not None:
        data["amount"] = {"value": amount, "currency": currency}
    if reference is not None:
        data["metadata"] = {"reference": reference}
    return data


def _paid_for(order, pid="pay_1", **over):
    """«Оплачено» ровно по заказу; `over` подменяет сумму/валюту/reference."""
    kw = {"amount": f"{order.total:.2f}", "reference": f"{order.order_id}-{order.pk}"}
    kw.update(over)
    return _yk(status="succeeded", pid=pid, **kw)


class _YooKassaCase(ApiTestCase):
    """Боевой режим оплаты на весь тест, включая setUp (декоратор класса его не покрывает)."""

    def setUp(self):
        env = mock.patch.dict(os.environ, _YK_ENV)
        env.start()
        self.addCleanup(env.stop)
        super().setUp()


class FrozenOrderTests(_YooKassaCase):
    """B01: после начала оплаты заказ не меняется."""

    phone = "+79990005101"

    def _post(self, oid, total=1000, **kw):
        body = {"id": oid, "total": total, "status": "pending",
                "items": kw.pop("items", None) or _items(total)}
        body.update(kw)
        return self.api_post("/v1/orders", body)

    def _start_payment(self, oid):
        with mock.patch("orders.payment._http", return_value=_yk()):
            r = self.api_post(f"/v1/orders/{oid}/pay", {})
        self.assertEqual(r.status_code, 200, r.content)
        return r

    def _get(self, oid):
        return Order.objects.get(user_id=self.uid, order_id=oid)

    def test_repeat_of_same_order_in_payment_is_idempotent(self):
        """Ретрай/офлайн-очередь шлют тот же заказ ещё раз — это не ошибка."""
        self.assertEqual(self._post("SS-F1").status_code, 200)
        self._start_payment("SS-F1")
        before = self._get("SS-F1")

        r = self._post("SS-F1")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["id"], "SS-F1")
        after = self._get("SS-F1")
        self.assertEqual(after.total, before.total)
        self.assertEqual(after.payment_id, "pay_1")
        self.assertEqual(after.payment_status, "pending")

    def test_changed_total_after_payment_started_is_refused(self):
        self._post("SS-F2", total=1000)
        self._start_payment("SS-F2")

        # Дороже — сумма сходится с каталогом, но платёж уже создан на 1000.
        r = self._post("SS-F2", total=2000, items=_items(1000, qty=2))
        self.assertEqual(r.status_code, 409, r.content)
        order = self._get("SS-F2")
        self.assertEqual(order.total, 1000)
        self.assertEqual(order.payload["items"][0]["quantity"], 1)

    def test_changed_items_same_total_after_payment_started_is_refused(self):
        self._post("SS-F3")
        self._start_payment("SS-F3")
        r = self._post("SS-F3", items=_items(1000, size="44"))
        self.assertEqual(r.status_code, 409, r.content)
        self.assertEqual(self._get("SS-F3").payload["items"][0]["size"], "42")

    def test_changes_before_payment_are_still_accepted(self):
        """Оплата не начата — прежнее поведение: заказ можно переоформить."""
        self._post("SS-F4", total=1000)
        r = self._post("SS-F4", total=2000, items=_items(1000, qty=2))
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self._get("SS-F4").total, 2000)

    def test_repeat_does_not_reset_server_status(self):
        """Клиент шлёт status: pending — отгруженный заказ «принятым» не становится."""
        self._post("SS-F5")
        self._start_payment("SS-F5")
        Order.objects.filter(pk=self._get("SS-F5").pk).update(
            payment_status="paid", status="shipped")
        r = self._post("SS-F5")
        self.assertEqual(r.status_code, 200, r.content)
        order = self._get("SS-F5")
        self.assertEqual(order.status, "shipped")
        self.assertEqual(order.payment_status, "paid")

    def test_client_cannot_create_order_with_its_own_status(self):
        self._post("SS-F6", status="delivered")
        self.assertEqual(self._get("SS-F6").status, "pending")

    def test_order_changed_while_payment_was_created_is_not_linked(self):
        """Переоформили, пока ЮKassa создавала платёж: платёж не привязываем."""
        self._post("SS-F7", total=1000)
        order = self._get("SS-F7")

        def racing_http(method, url, payload=None, headers=None):
            Order.objects.filter(pk=order.pk).update(total=2000, total_kop=200000)
            return _yk(pid="pay_race")

        with mock.patch("orders.payment._http", side_effect=racing_http):
            r = self.api_post("/v1/orders/SS-F7/pay", {})
        self.assertEqual(r.status_code, 409, r.content)
        self.assertNotIn("confirmationUrl", r.json())
        self.assertEqual(self._get("SS-F7").payment_id, "")

    def test_pay_response_keeps_old_contract(self):
        self._post("SS-F8")
        r = self._start_payment("SS-F8")
        self.assertEqual(set(r.json()), {"status", "paymentId", "confirmationUrl", "method"})


class PaymentMatchTests(_YooKassaCase):
    """B01: «оплачено» — только если платёж совпал с заказом."""

    phone = "+79990005102"

    def setUp(self):
        super().setUp()
        self.api_post("/v1/orders", {"id": "SS-M", "total": 1000, "items": _items(1000)})
        with mock.patch("orders.payment._http", return_value=_yk()):
            self.api_post("/v1/orders/SS-M/pay", {})
        self.order = Order.objects.get(user_id=self.uid, order_id="SS-M")
        self.assertEqual(self.order.payment_id, "pay_1")

    def _webhook(self, info):
        with mock.patch("orders.payment._http", return_value=info):
            return self.client.post(
                "/v1/payments/webhook",
                data=json.dumps({"event": "payment.succeeded", "object": {"id": "pay_1"}}),
                content_type="application/json",
            )

    def _state(self):
        self.order.refresh_from_db()
        return self.order.payment_status

    def test_matching_payment_marks_paid(self):
        r = self._webhook(_paid_for(self.order))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self._state(), "paid")

    def test_wrong_amount_is_not_paid(self):
        r = self._webhook(_paid_for(self.order, amount="1.00"))
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["ok"])
        self.assertEqual(self._state(), "pending")
        self.assertEqual(self.balance(), 0)

    def test_wrong_currency_is_not_paid(self):
        self._webhook(_paid_for(self.order, currency="USD"))
        self.assertEqual(self._state(), "pending")

    def test_foreign_reference_is_not_paid(self):
        self._webhook(_paid_for(self.order, reference="SS-M-999999"))
        self.assertEqual(self._state(), "pending")

    def test_missing_amount_is_not_paid(self):
        self._webhook(_yk(status="succeeded"))
        self.assertEqual(self._state(), "pending")

    def test_status_check_also_verifies(self):
        with mock.patch("orders.payment._http",
                        return_value=_paid_for(self.order, amount="999.00")):
            r = self.api_get("/v1/orders/SS-M/payment")
        self.assertEqual(r.json()["status"], "pending")

    def test_background_check_also_verifies(self):
        from datetime import timedelta

        from django.utils import timezone

        from orders.lifecycle import expire_unpaid

        Order.objects.filter(pk=self.order.pk).update(
            created_at=timezone.now() - timedelta(minutes=30))
        with mock.patch("orders.payment._http",
                        return_value=_paid_for(self.order, amount="1.00")):
            stats = expire_unpaid()
        self.assertEqual(stats["errors"], 1)
        self.assertEqual(self._state(), "pending")


class PaymentTransitionTests(_YooKassaCase):
    """B05: повтор подтверждения не откатывает возврат и не шлёт заказ в сборку."""

    phone = "+79990005103"

    def setUp(self):
        super().setUp()
        add_txn(self.uid, 1000, "runnerRun", "Баллы за бег")
        self.api_post("/v1/orders", {"id": "SS-T", "total": 700, "pointsRedeemed": 300,
                                     "items": _items(1000)})
        with mock.patch("orders.payment._http", return_value=_yk()):
            self.api_post("/v1/orders/SS-T/pay", {})
        self.order = Order.objects.get(user_id=self.uid, order_id="SS-T")
        self.assertEqual(self.order.payment_id, "pay_1")

    def _webhook(self, info, event="payment.succeeded"):
        with mock.patch("orders.payment._http", return_value=info):
            return self.client.post(
                "/v1/payments/webhook",
                data=json.dumps({"event": event, "object": {"id": "pay_1"}}),
                content_type="application/json",
            )

    def _set(self, **fields):
        Order.objects.filter(pk=self.order.pk).update(**fields)

    def _reload(self):
        self.order.refresh_from_db()
        return self.order

    def test_repeat_paid_after_full_refund_keeps_refund(self):
        self._webhook(_paid_for(self.order))
        self._set(payment_status="refunded", status="cancelled")

        self._webhook(_paid_for(self.order))
        order = self._reload()
        self.assertEqual(order.payment_status, "refunded")
        self.assertEqual(order.status, "cancelled")
        self.assertNotIn(order.order_id, [o.order_id for o in pending_orders()])

    def test_repeat_paid_after_partial_refund_keeps_refund(self):
        self._webhook(_paid_for(self.order))
        self._set(payment_status="partially_refunded")

        self._webhook(_paid_for(self.order))
        self.assertEqual(self._reload().payment_status, "partially_refunded")

    def test_late_cancel_does_not_cancel_paid_order(self):
        self._webhook(_paid_for(self.order))
        balance = self.balance()

        self._webhook(_yk(status="canceled"), event="payment.canceled")
        order = self._reload()
        self.assertEqual(order.payment_status, "paid")
        self.assertEqual(order.status, "paid")
        self.assertEqual(self.balance(), balance, "списанные баллы не должны вернуться")

    def test_paid_after_cancel_does_not_revive_order(self):
        """Заказ отменён (например, сотрудником), а деньги всё же пришли: в сборку
        он не возвращается — это разбирает человек."""
        self._set(payment_status="canceled", status="cancelled")
        self._webhook(_paid_for(self.order))
        order = self._reload()
        self.assertEqual(order.payment_status, "canceled")
        self.assertEqual(order.status, "cancelled")
        self.assertNotIn(order.order_id, [o.order_id for o in pending_orders()])

    def test_repeat_paid_keeps_later_order_status(self):
        self._webhook(_paid_for(self.order))
        self._set(status="shipped")
        self._webhook(_paid_for(self.order))
        self.assertEqual(self._reload().status, "shipped")
