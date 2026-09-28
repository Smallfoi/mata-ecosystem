"""Серверная нормализация корзины (аудит B09, F03).

Строки заказа сервер собирает сам по каталогу: товар существует и продаётся,
размер и цвет есть у позиции, количество целое и в пределах остатка, цена —
из каталога. Клиентская цена и название в чек и в 1С не попадают.

Совместимость: сайт шлёт позиции без размера и цвета, Store — с ними; позиции
без размеров в каталоге (1С не заполнила строку) принимаются с любым размером
клиента — как раньше; товар не из каталога при выключенной оплате не блокирует
заказ (dev и старые сборки с демо-каталогом).
"""
import os
from unittest import mock

from django.db import connection
from django.test.utils import CaptureQueriesContext

from catalog.models import Product
from common.testutils import ApiTestCase
from integrations.onec_orders import order_to_json
from loyalty.models import add_txn
from orders.models import Order
from orders.receipt import build_receipt

_YK_ENV = {
    "PAYMENT_PROVIDER": "yookassa",
    "YOOKASSA_SHOP_ID": "654321",
    "YOOKASSA_SECRET_KEY": "test_secret_key",
    "YOOKASSA_RETURN_URL": "https://example.test/orders",
}


def _product(pid, price=1000, **kw):
    fields = {"name": "Кроссовки BMAI 42р.", "display_name": "Кроссовки BMAI",
              "category_id": "wear", "price": price}
    fields.update(kw)
    return Product.objects.create(id=pid, **fields)


class _CartCase(ApiTestCase):
    def _post(self, oid, items, total, **kw):
        body = {"id": oid, "total": total, "status": "pending", "items": items,
                "checkoutData": {"email": "b@example.test", "phone": "+79990000000"}}
        body.update(kw)
        return self.api_post("/v1/orders", body)

    def _order(self, oid):
        return Order.objects.get(user_id=self.uid, order_id=oid)


class InvalidPositionTests(_CartCase):
    """Некорректная позиция — понятный отказ, заказ не создаётся."""

    phone = "+79990009101"

    def setUp(self):
        super().setUp()
        _product("c-shoe", sizes=["41", "42"], colors=["ЧЕРНЫЙ"],
                 stock_by_size={"41": 0, "42": 2}, stock_count=2)

    def _line(self, **kw):
        line = {"productId": "c-shoe", "productName": "Кроссовки", "price": 1000,
                "size": "42", "color": "ЧЕРНЫЙ", "quantity": 1}
        line.update(kw)
        return line

    def _refused(self, r, status, oid):
        self.assertEqual(r.status_code, status, r.content)
        self.assertTrue(r.json().get("detail"))
        self.assertFalse(Order.objects.filter(order_id=oid).exists())

    def test_unpublished_product_refused(self):
        Product.objects.filter(pk="c-shoe").update(is_published=False)
        r = self._post("SS-C1", [self._line()], 1000)
        self._refused(r, 409, "SS-C1")
        self.assertEqual(r.json()["productId"], "c-shoe")
        self.assertEqual(r.json()["itemIndex"], 0)

    def test_withdrawn_in_1c_refused(self):
        Product.objects.filter(pk="c-shoe").update(is_active_1c=False)
        self._refused(self._post("SS-C2", [self._line()], 1000), 409, "SS-C2")

    def test_out_of_stock_size_refused(self):
        self._refused(self._post("SS-C3", [self._line(size="41")], 1000), 409, "SS-C3")

    def test_out_of_stock_product_refused(self):
        Product.objects.filter(pk="c-shoe").update(in_stock=False)
        self._refused(self._post("SS-C4", [self._line()], 1000), 409, "SS-C4")

    def test_more_than_left_refused(self):
        self._refused(self._post("SS-C5", [self._line(quantity=3)], 3000), 409, "SS-C5")

    def test_same_size_in_two_lines_counts_together(self):
        r = self._post("SS-C6", [self._line(), self._line(quantity=2)], 3000)
        self._refused(r, 409, "SS-C6")

    def test_unknown_size_refused(self):
        self._refused(self._post("SS-C7", [self._line(size="45")], 1000), 409, "SS-C7")

    def test_unknown_color_refused(self):
        self._refused(self._post("SS-C8", [self._line(color="РОЗОВЫЙ")], 1000), 409, "SS-C8")

    def test_bad_quantities_refused(self):
        for i, qty in enumerate((0, -1, 1.5, "два", True, 10_000)):
            oid = f"SS-C9{i}"
            self._refused(self._post(oid, [self._line(quantity=qty)], 1000), 400, oid)

    def test_too_many_units_refused(self):
        Product.objects.filter(pk="c-shoe").update(stock_by_size={}, stock_count=None)
        items = [self._line(quantity=50), self._line(quantity=50)]
        self._refused(self._post("SS-C10", items, 100_000), 400, "SS-C10")

    def test_line_is_not_an_object_refused(self):
        self._refused(self._post("SS-C11", ["c-shoe"], 1000), 400, "SS-C11")

    def test_bad_total_refused(self):
        self._refused(self._post("SS-C12", [self._line()], "много"), 400, "SS-C12")

    @mock.patch.dict(os.environ, _YK_ENV)
    def test_unknown_product_with_payment_refused(self):
        r = self._post("SS-C13", [self._line(productId="нет-такого")], 1000)
        self._refused(r, 400, "SS-C13")

    def test_refusal_returns_redeemed_points(self):
        add_txn(self.uid, 1000, "runnerRun", "Баллы за бег",
                available_at=None)  # созревшие (правило 3 дней)
        r = self._post("SS-C14", [self._line(size="41")], 900, pointsRedeemed=100)
        self._refused(r, 409, "SS-C14")
        self.assertEqual(self.balance(), 1000)


class ServerPricesTests(_CartCase):
    """Цена и название строки — из каталога: заказ, чек и 1С согласованы."""

    phone = "+79990009102"

    def setUp(self):
        super().setUp()
        _product("c-tee", price=2490, display_name="Футболка МАТА")

    def test_client_price_and_name_replaced_by_catalog(self):
        items = [{"productId": "c-tee", "productName": "Бесплатно", "price": 1,
                  "quantity": 2}]
        r = self._post("SS-P1", items, 4980, subtotal=2)
        self.assertEqual(r.status_code, 200, r.content)
        line = self._order("SS-P1").payload["items"][0]
        self.assertEqual(line["price"], 2490.0)
        self.assertEqual(line["productName"], "Футболка МАТА")
        self.assertEqual(line["quantity"], 2)
        self.assertEqual(self._order("SS-P1").payload["subtotal"], 4980.0)
        # Ответ — тот же контракт, что читает Store (Order.fromJson).
        self.assertEqual(r.json()["items"][0]["price"], 2490.0)

    @mock.patch.dict(os.environ, {"PAYMENT_RECEIPT": "1"})
    def test_receipt_uses_catalog_prices(self):
        items = [{"productId": "c-tee", "productName": "Бесплатно", "price": 1,
                  "quantity": 1}]
        self._post("SS-P2", items, 2490)
        order = self._order("SS-P2")
        receipt = build_receipt(order.payload, order.total)
        self.assertEqual(receipt["items"][0]["description"], "Футболка МАТА")
        self.assertEqual(receipt["items"][0]["amount"]["value"], "2490.00")

    def test_onec_export_uses_catalog_prices(self):
        items = [{"productId": "c-tee", "productName": "Бесплатно", "price": 1,
                  "quantity": 1}]
        self._post("SS-P3", items, 2490)
        line = order_to_json(self._order("SS-P3"))["items"][0]
        self.assertEqual(line["price"], 2490.0)
        self.assertEqual(line["name"], "Футболка МАТА")

    def test_stale_higher_client_price_still_accepted(self):
        """Корзина со старой (более высокой) ценой: переплату клиент видит сам,
        заказ не отбиваем — как и раньше (минимум, а не равенство)."""
        items = [{"productId": "c-tee", "productName": "Футболка", "price": 2990,
                  "quantity": 1}]
        r = self._post("SS-P4", items, 2990)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self._order("SS-P4").payload["items"][0]["price"], 2490.0)

    def test_understated_total_still_refused(self):
        items = [{"productId": "c-tee", "price": 1, "quantity": 1}]
        self.assertEqual(self._post("SS-P5", items, 1).status_code, 400)


class ClientCompatibilityTests(_CartCase):
    """Текущие форматы Store и сайта проходят без изменений на клиентах."""

    phone = "+79990009103"

    def setUp(self):
        super().setUp()
        _product("v-42", price=4490, sizes=["42"], colors=["ЧЕРНЫЙ"],
                 stock_by_size={"42": 3}, stock_count=3)
        _product("legacy", price=1500)  # позиция без размеров/цветов/остатков

    def test_store_payload(self):
        """mata_store OrderItem.toJson: productId позиции, размер/цвет из карточки."""
        items = [{"productId": "v-42", "productName": "Кроссовки BMAI",
                  "productBrand": "BMAI", "imageUrl": "https://x/1.jpg",
                  "price": 4490.0, "size": "42", "color": "ЧЕРНЫЙ", "quantity": 1}]
        r = self._post("SS-S1", items, 4790, subtotal=4490.0, deliveryCost=300.0,
                       pointsRedeemed=0, createdAt="2026-09-28T10:00:00")
        self.assertEqual(r.status_code, 200, r.content)
        line = r.json()["items"][0]
        for key in ("productBrand", "imageUrl", "size", "color"):
            self.assertEqual(line[key], items[0][key])
        self.assertIsInstance(line["quantity"], int)

    def test_site_payload_without_size_and_color(self):
        """Сайт: productId позиции, имя «модель · цвет · размер», без size/color."""
        items = [{"productId": "v-42", "productName": "Кроссовки · ЧЕРНЫЙ · 42",
                  "price": 4490, "quantity": 2}]
        r = self._post("МАТА-100001", items, 8980, subtotal=8980, deliveryCost=0)
        self.assertEqual(r.status_code, 200, r.content)

    def test_size_on_position_without_sizes_in_catalog(self):
        """1С не заполнила строку размеров — размер клиента не проверить, не отбиваем."""
        items = [{"productId": "legacy", "price": 1500, "size": "42",
                  "color": "black", "quantity": 1}]
        self.assertEqual(self._post("SS-S3", items, 1500).status_code, 200)

    def test_size_spelling_is_tolerant(self):
        items = [{"productId": "v-42", "price": 4490, "size": " 42 ",
                  "color": "черный", "quantity": 1}]
        self.assertEqual(self._post("SS-S4", items, 4490).status_code, 200)

    def test_quantity_as_string_or_missing(self):
        items = [{"productId": "legacy", "price": 1500, "quantity": "2"},
                 {"productId": "legacy", "price": 1500}]
        r = self._post("SS-S5", items, 4500)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual([i["quantity"] for i in r.json()["items"]], [2, 1])

    def test_unknown_product_without_payment_not_blocked(self):
        items = [{"productId": "нет-такого", "productName": "Демо", "price": 100,
                  "quantity": 1}]
        r = self._post("SS-S6", items, 100)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["items"][0]["price"], 100)

    @mock.patch.dict(os.environ, _YK_ENV)
    def test_repeat_in_payment_with_client_price_is_idempotent(self):
        """Ретрай из офлайн-очереди шлёт клиентскую цену, а в заказе серверная —
        это тот же заказ, не 409."""
        items = [{"productId": "legacy", "price": 1400, "quantity": 1}]
        self.assertEqual(self._post("SS-S7", items, 1500).status_code, 200)
        Order.objects.filter(user_id=self.uid, order_id="SS-S7").update(payment_id="pay_x")
        r = self._post("SS-S7", items, 1500)
        self.assertEqual(r.status_code, 200, r.content)


class RepeatPointsTests(_CartCase):
    """Повтор заказа до оплаты с другим pointsRedeemed не расходится с реестром."""

    phone = "+79990009104"

    def setUp(self):
        super().setUp()
        _product("pt-1", price=1000)
        add_txn(self.uid, 1000, "runnerRun", "Баллы за бег",
                available_at=None)  # созревшие (правило 3 дней)
        self.items = [{"productId": "pt-1", "price": 1000, "quantity": 1}]

    def test_changed_points_on_repeat_refused(self):
        self.assertEqual(self._post("SS-R1", self.items, 900, pointsRedeemed=100).status_code, 200)
        r = self._post("SS-R1", self.items, 700, pointsRedeemed=300)
        self.assertEqual(r.status_code, 409, r.content)
        order = self._order("SS-R1")
        self.assertEqual(order.points_redeemed, 100)
        self.assertEqual(order.payload["pointsRedeemed"], 100)
        self.assertEqual(self.balance(), 900)

    def test_points_added_on_repeat_refused(self):
        self.assertEqual(self._post("SS-R2", self.items, 1000).status_code, 200)
        r = self._post("SS-R2", self.items, 900, pointsRedeemed=100)
        self.assertEqual(r.status_code, 409, r.content)
        self.assertEqual(self._order("SS-R2").points_redeemed, 0)
        self.assertEqual(self.balance(), 1000)

    def test_same_points_on_repeat_accepted(self):
        self._post("SS-R3", self.items, 900, pointsRedeemed=100)
        r = self._post("SS-R3", self.items, 900, pointsRedeemed=100)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self.balance(), 900)


class QueryCountTests(_CartCase):
    """F03: сверка с каталогом — одна выборка, а не запрос на каждую позицию."""

    phone = "+79990009105"

    def setUp(self):
        super().setUp()
        for i in range(12):
            _product(f"q-{i}", price=100)

    def _count(self, oid, n):
        items = [{"productId": f"q-{i}", "price": 100, "quantity": 1} for i in range(n)]
        with CaptureQueriesContext(connection) as ctx:
            r = self._post(oid, items, 100 * n)
        self.assertEqual(r.status_code, 200, r.content)
        return len(ctx.captured_queries)

    def test_queries_do_not_grow_with_lines(self):
        self._count("SS-Q0", 1)  # прогрев: разовые запросы первого заказа
        self.assertEqual(self._count("SS-Q1", 1), self._count("SS-Q2", 12))

    def test_minimum_total_single_query(self):
        from orders.pricing import minimum_total

        items = [{"productId": f"q-{i}", "quantity": 1} for i in range(12)]
        with CaptureQueriesContext(connection) as ctx:
            self.assertEqual(minimum_total(items, self.uid, "SS-Q3"), 1200)
        self.assertLessEqual(len(ctx.captured_queries), 2)
