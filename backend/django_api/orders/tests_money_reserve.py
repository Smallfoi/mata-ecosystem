"""Деньги в копейках и резерв остатка на время оплаты (аудит B09, остатки).

Деньги: сумма заказа хранится в копейках (`Order.total_kop`) рядом со старым
float `total` (двойная запись, API не меняется); платёж, чек, возвраты и 1С
считают из копеек, рубли → копейки по ROUND_HALF_UP.

Резерв: пока заказ ждёт оплату (≤ 15 минут), его вещи держатся — вторая покупка
последней единицы получает отказ, в том числе одновременная. Остаток товара
(его ведёт 1С) не меняется.
"""
import importlib
import json
import os
import threading
import time
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.apps import apps as django_apps
from django.core.cache import cache
from django.db import connection
from django.test import Client, TransactionTestCase
from django.utils import timezone

from catalog.models import Product
from common.testutils import ApiTestCase
from integrations.onec_orders import mark_taken, order_to_json
from loyalty.models import add_txn
from orders import pricing
from orders.lifecycle import mark_canceled, mark_paid
from orders.models import Order
from orders.money import to_kop
from orders.payment import payment_mismatch
from orders.receipt import build_receipt

_YK_ENV = {
    "PAYMENT_PROVIDER": "yookassa",
    "YOOKASSA_SHOP_ID": "654321",
    "YOOKASSA_SECRET_KEY": "test_secret_key",
    "YOOKASSA_RETURN_URL": "https://example.test/orders",
    "PAYMENT_RECEIPT": "1",
}


def _product(pid, price=1000, **kw):
    fields = {"name": "Кроссовки BMAI 42р.", "display_name": "Кроссовки BMAI",
              "category_id": "wear", "price": price}
    fields.update(kw)
    return Product.objects.create(id=pid, **fields)


def _body(oid, pid, total, size="", qty=1, **kw):
    line = {"productId": pid, "productName": "x", "price": total, "quantity": qty}
    if size:
        line["size"] = size
    body = {"id": oid, "total": total, "status": "pending", "items": [line],
            "checkoutData": {"email": "b@example.test", "phone": "+79990000000"}}
    body.update(kw)
    return body


class KopecksTests(ApiTestCase):
    phone = "+79990009301"

    def test_half_up_not_float_rounding(self):
        # float 1.005 хранится как 1.00499…: round(x * 100) даёт 100, а надо 101.
        self.assertEqual(to_kop(1.005), 101)
        self.assertEqual(to_kop(0.285), 29)
        self.assertEqual(to_kop("2490"), 249000)
        self.assertEqual(to_kop(Decimal("10.10")), 1010)

    def test_order_writes_both_fields_api_unchanged(self):
        _product("m-tee", price=2490.5)
        r = self.api_post("/v1/orders", _body("SS-M1", "m-tee", 2490.5))
        self.assertEqual(r.status_code, 200, r.content)
        order = Order.objects.get(user_id=self.uid, order_id="SS-M1")
        self.assertEqual(order.total_kop, 249050)
        self.assertEqual(order.total, 2490.5)
        # Контракт клиентов прежний: total — число в рублях.
        self.assertEqual(r.json()["total"], 2490.5)

    def test_legacy_writers_keep_kopecks_in_sync(self):
        # Старый путь (админка, код до копеек) пишет только float — копейки
        # досчитываются в save(), в том числе при update_fields.
        order = Order.objects.create(user_id=self.uid, order_id="SS-M2", total=100.005)
        self.assertEqual(order.total_kop, 10001)
        order.total = 250
        order.save(update_fields=["total"])
        order.refresh_from_db()
        self.assertEqual(order.total_kop, 25000)

    def test_migration_backfills_from_float_half_up(self):
        order = Order.objects.create(user_id=self.uid, order_id="SS-M3", total=1.005)
        Order.objects.filter(pk=order.pk).update(total_kop=None)
        migration = importlib.import_module("orders.migrations.0009_order_total_kop")
        migration.fill(django_apps, None)
        order.refresh_from_db()
        self.assertEqual(order.total_kop, 101)
        self.assertEqual(order.total, 1.005)  # старое поле не тронуто

    def test_payment_amount_compared_in_kopecks(self):
        order = Order.objects.create(user_id=self.uid, order_id="SS-M4", total=1234.5,
                                     payment_id="pay_m4")
        info = {"paymentId": "pay_m4", "currency": "RUB", "amount": "1234.50",
                "reference": f"SS-M4-{order.pk}"}
        self.assertEqual(payment_mismatch(order, info), "")
        self.assertTrue(payment_mismatch(order, {**info, "amount": "1234.49"}))


class ReceiptMatchesPaymentTests(ApiTestCase):
    """Сумма строк чека = сумма платежа = сумма заказа до копейки."""

    phone = "+79990009302"

    def setUp(self):
        env = mock.patch.dict(os.environ, _YK_ENV)
        env.start()
        self.addCleanup(env.stop)
        super().setUp()

    def test_receipt_lines_sum_to_payment_amount(self):
        _product("m-odd", price=333.33)
        _product("m-cap", price=1999.99)
        add_txn(self.uid, 500, "admin", "на тест", "")
        items = [
            {"productId": "m-odd", "productName": "x", "price": 1, "quantity": 3},
            {"productId": "m-cap", "productName": "y", "price": 1, "quantity": 1},
        ]
        # Платная доставка — способ из админки (D-110), цену считает сервер.
        from orders.models import ShippingOption

        ShippingOption.objects.filter(code="courier").update(price=300)
        # 999.99 + 1999.99 + доставка 300.00 − 150 баллов = 3149.98
        body = {"id": "SS-R1", "total": 3149.98, "items": items, "deliveryCost": 299.995,
                "pointsRedeemed": 150,
                "checkoutData": {"email": "b@example.test", "phone": "+79990000000",
                                 "deliveryType": "courier"}}
        r = self.api_post("/v1/orders", body)
        self.assertEqual(r.status_code, 200, r.content)
        order = Order.objects.get(user_id=self.uid, order_id="SS-R1")
        self.assertEqual(order.total_kop, 314998)

        sent = {}

        def fake_http(method, url, payload=None, headers=None):
            sent.update(payload or {})
            return {"id": "pay_r1", "status": "pending",
                    "confirmation": {"confirmation_url": "https://yoomoney.ru/x"}}

        with mock.patch("orders.payment._http", side_effect=fake_http):
            r = self.api_post("/v1/orders/SS-R1/pay", {})
        self.assertEqual(r.status_code, 200, r.content)
        paid = to_kop(sent["amount"]["value"])
        lines = sum(to_kop(it["amount"]["value"]) for it in sent["receipt"]["items"])
        self.assertEqual(paid, order.total_kop)
        self.assertEqual(lines, paid)
        # Чек, собранный отдельно (возвраты считают по нему же), совпадает.
        again = build_receipt(order.payload, Decimal(order.total_kop) / 100)
        self.assertEqual(sum(to_kop(i["amount"]["value"]) for i in again["items"]), paid)
        # 1С получает ту же сумму.
        self.assertEqual(to_kop(order_to_json(order)["total"]), paid)


class ReserveTests(ApiTestCase):
    """Последняя вещь: пока первый покупатель оплачивает, второй её не оформит."""

    phone = "+79990009303"

    def setUp(self):
        super().setUp()
        self.other = self.new_user("+79990009304")
        _product("m-last", price=5000, stock_count=1)

    def _first(self, oid="SS-A1"):
        r = self.api_post("/v1/orders", _body(oid, "m-last", 5000))
        self.assertEqual(r.status_code, 200, r.content)
        return Order.objects.get(user_id=self.uid, order_id=oid)

    def _second(self, oid="SS-B1"):
        return self.api_post("/v1/orders", _body(oid, "m-last", 5000), token=self.other)

    def test_second_buyer_refused_while_first_pays(self):
        self._first()
        r = self._second()
        self.assertEqual(r.status_code, 409, r.content)
        self.assertEqual(r.json()["productId"], "m-last")
        self.assertIn("другой покупатель", r.json()["detail"])
        self.assertFalse(Order.objects.filter(order_id="SS-B1").exists())

    def test_stock_itself_not_written(self):
        before = Product.objects.values("stock_count", "stock_by_size", "in_stock").get(pk="m-last")
        self._first()
        after = Product.objects.values("stock_count", "stock_by_size", "in_stock").get(pk="m-last")
        self.assertEqual(after, before)  # остатки ведёт 1С — резерв отдельно

    def test_own_order_retry_not_blocked_by_own_reserve(self):
        self._first()
        r = self.api_post("/v1/orders", _body("SS-A1", "m-last", 5000))
        self.assertEqual(r.status_code, 200, r.content)

    def test_released_after_cancel(self):
        order = self._first()
        mark_canceled(order)
        self.assertEqual(self._second().status_code, 200)

    def _paid(self):
        order = self._first()
        Order.objects.filter(pk=order.pk).update(payment_id="pay_a1")
        order.refresh_from_db()
        mark_paid(order)
        order.refresh_from_db()
        self.assertEqual(order.payment_status, "paid")
        return order

    def test_paid_not_taken_by_1c_still_holds(self):
        # Вещь продана, а в остатках 1С ещё числится — второму не продаём.
        self._paid()
        r = self._second()
        self.assertEqual(r.status_code, 409, r.content)

    def test_paid_hold_does_not_expire_by_time(self):
        order = self._paid()
        Order.objects.filter(pk=order.pk).update(
            created_at=timezone.now() - timedelta(hours=5))
        self.assertEqual(self._second().status_code, 409)

    def test_released_after_1c_took_order(self):
        order = self._paid()
        mark_taken([order.order_id])
        self.assertEqual(self._second().status_code, 200)

    def test_released_after_refund(self):
        order = self._paid()
        Order.objects.filter(pk=order.pk).update(payment_status="refunded",
                                                 status="cancelled")
        self.assertEqual(self._second().status_code, 200)

    def test_released_after_partial_refund(self):
        order = self._paid()
        Order.objects.filter(pk=order.pk).update(payment_status="partially_refunded")
        self.assertEqual(self._second().status_code, 200)

    def test_released_when_paid_order_cancelled(self):
        order = self._paid()
        Order.objects.filter(pk=order.pk).update(status="cancelled")
        self.assertEqual(self._second().status_code, 200)

    def test_released_after_hold_expires(self):
        order = self._first()
        Order.objects.filter(pk=order.pk).update(
            created_at=timezone.now() - timedelta(minutes=16))
        self.assertEqual(self._second().status_code, 200)

    def test_reserve_is_per_size(self):
        _product("m-sized", price=5000, sizes=["41", "42"],
                 stock_by_size={"41": 1, "42": 1}, stock_count=2)
        r = self.api_post("/v1/orders", _body("SS-S1", "m-sized", 5000, size="42"))
        self.assertEqual(r.status_code, 200, r.content)
        busy = self.api_post("/v1/orders", _body("SS-S2", "m-sized", 5000, size="42"),
                             token=self.other)
        self.assertEqual(busy.status_code, 409, busy.content)
        free = self.api_post("/v1/orders", _body("SS-S3", "m-sized", 5000, size="41"),
                             token=self.other)
        self.assertEqual(free.status_code, 200, free.content)

    def test_untracked_stock_not_limited(self):
        # Остаток не ведётся (1С не прислала) — резерв не ограничивает, как и витрина.
        _product("m-free", price=100)
        for i, token in enumerate((None, self.other)):
            r = self.api_post("/v1/orders", _body(f"SS-U{i}", "m-free", 100), token=token)
            self.assertEqual(r.status_code, 200, r.content)


class ConcurrentLastUnitTests(TransactionTestCase):
    """Две одновременные покупки последней единицы — проходит ровно одна (Postgres)."""

    def _token(self, phone):
        r = Client().post("/v1/auth/phone/verify",
                          data=json.dumps({"phone": phone, "code": "1234"}),
                          content_type="application/json")
        return r.json()["token"]

    def test_only_one_of_two_parallel_orders_passes(self):
        if connection.vendor != "postgresql":
            self.skipTest("нужны строковые блокировки Postgres")
        cache.clear()
        _product("m-race", price=5000, stock_count=1)
        tokens = [self._token("+79990009305"), self._token("+79990009306")]
        barrier = threading.Barrier(2)
        codes = []
        real = pricing.reserved_units

        def slow_reserved(*args, **kwargs):
            # Окно гонки: резерв посчитан, заказ ещё не записан. Без блокировки
            # товара оба потока видят «свободно» и оба оформляют.
            out = real(*args, **kwargs)
            time.sleep(0.5)
            return out

        def buy(i):
            try:
                barrier.wait(timeout=10)
                r = Client().post(
                    "/v1/orders", data=json.dumps(_body(f"SS-T{i}", "m-race", 5000)),
                    content_type="application/json",
                    HTTP_AUTHORIZATION=f"Bearer {tokens[i]}")
                codes.append(r.status_code)
            finally:
                connection.close()

        with mock.patch("orders.pricing.reserved_units", side_effect=slow_reserved):
            threads = [threading.Thread(target=buy, args=(i,)) for i in range(2)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=30)
        self.assertEqual(sorted(codes), [200, 409], codes)
        self.assertEqual(Order.objects.filter(order_id__startswith="SS-T").count(), 1)
        self.assertEqual(Product.objects.get(pk="m-race").stock_count, 1)

        # Первый не оплатил и заказ отменили — единица снова продаётся.
        mark_canceled(Order.objects.get(order_id__startswith="SS-T"))
        r = Client().post("/v1/orders", data=json.dumps(_body("SS-T9", "m-race", 5000)),
                          content_type="application/json",
                          HTTP_AUTHORIZATION=f"Bearer {self._token('+79990009307')}")
        self.assertEqual(r.status_code, 200, r.content)
