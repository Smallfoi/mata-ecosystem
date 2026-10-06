"""Способы доставки и итог заказа считает сервер (D-110)."""
from catalog.models import Product
from common.testutils import ApiTestCase
from orders.models import Order, ShippingOption


def _product(pid, price):
    Product.objects.create(id=pid, name=pid, price=price, in_stock=True, stock_count=10,
                           is_published=True, is_active_1c=True)


class ShippingOptionsTests(ApiTestCase):
    phone = "+79990011001"

    def setUp(self):
        super().setUp()
        _product("ship-a", 1000)
        self.courier = ShippingOption.objects.get(code="courier")

    def _order(self, oid, total, delivery_type="courier", client_delivery=0):
        return self.api_post("/v1/orders", {
            "id": oid, "total": total, "deliveryCost": client_delivery,
            "items": [{"productId": "ship-a", "productName": "x", "price": 1000,
                       "quantity": 1}],
            "checkoutData": {"deliveryType": delivery_type},
        })

    def test_seeded_options_are_free_like_before(self):
        r = self.client.get("/v1/shipping-options")
        self.assertEqual(r.status_code, 200)
        codes = {o["code"]: o["price"] for o in r.json()["options"]}
        self.assertEqual(codes, {"courier": 0.0, "pickup": 0.0})

    def test_free_from_threshold_in_quote(self):
        self.courier.price = 300
        self.courier.free_from = 5000
        self.courier.save()
        opts = {o["code"]: o for o in
                self.client.get("/v1/shipping-options?goods=1000").json()["options"]}
        self.assertEqual(opts["courier"]["cost"], 300.0)
        opts = {o["code"]: o for o in
                self.client.get("/v1/shipping-options?goods=5000").json()["options"]}
        self.assertEqual(opts["courier"]["cost"], 0.0)

    def test_inactive_option_hidden_and_refused(self):
        self.courier.is_active = False
        self.courier.save()
        codes = [o["code"] for o in self.client.get("/v1/shipping-options").json()["options"]]
        self.assertNotIn("courier", codes)
        self.assertEqual(self._order("SS-SH1", 1000).status_code, 409)

    def test_unknown_option_refused(self):
        self.assertEqual(self._order("SS-SH2", 1000, delivery_type="drone").status_code, 400)

    def test_client_delivery_cost_is_ignored(self):
        """Клиент прислал доставку 500 ₽ — в заказ и чек идёт цена способа (0 ₽)."""
        r = self._order("SS-SH3", 1500, client_delivery=500)
        self.assertEqual(r.status_code, 200, r.content)
        order = Order.objects.get(user_id=self.uid, order_id="SS-SH3")
        self.assertEqual(order.payload["deliveryCost"], 0.0)
        self.assertEqual(order.total_kop, 100000)  # списываем серверный итог
        self.assertEqual(order.payload["deliveryOption"]["code"], "courier")

    def test_paid_delivery_not_shown_to_customer_is_refused(self):
        """Доставка стала платной, а клиент показал сумму без неё — не списываем больше."""
        self.courier.price = 300
        self.courier.save()
        r = self._order("SS-SH4", 1000)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["expectedTotal"], 1300.0)
        self.assertFalse(Order.objects.filter(order_id="SS-SH4").exists())

    def test_paid_delivery_goes_into_order(self):
        self.courier.price = 300
        self.courier.save()
        r = self._order("SS-SH5", 1300)
        self.assertEqual(r.status_code, 200, r.content)
        order = Order.objects.get(user_id=self.uid, order_id="SS-SH5")
        self.assertEqual(order.total_kop, 130000)
        self.assertEqual(order.payload["deliveryCost"], 300.0)
