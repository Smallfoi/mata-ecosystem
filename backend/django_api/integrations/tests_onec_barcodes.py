"""Штрихкоды из 1С (D-121).

В 1С каждый размер и цвет — отдельная позиция, штрихкоды висят на ней массивом
`barcodes`. Мы их храним, показываем в админке, ищем по ним и отдаём обратно в
строках заказа — по штрихкоду склад находит вещь сканером.
"""
from django.test import TestCase, override_settings

from catalog.models import Category, Product, ProductBarcode
from orders.models import Order

TOKEN = "test-1c-token"
CATALOG = "/v1/integrations/1c/catalog"
PULL = "/v1/integrations/1c/orders"


def _item(pid, barcodes=None, **extra):
    raw = {"id": pid, "article": f"ART-{pid}", "name": f"Кроссовки {pid}",
           "categoryId": "shoes", "active": True, **extra}
    if barcodes is not None:
        raw["barcodes"] = barcodes
    return raw


@override_settings(INTEGRATION_1C_TOKEN=TOKEN)
class OneCBarcodeImportTests(TestCase):
    def setUp(self):
        Category.objects.create(id="shoes", name="Обувь")

    def _send(self, *items):
        r = self.client.post(CATALOG, {"products": list(items)},
                             content_type="application/json",
                             HTTP_AUTHORIZATION=f"Bearer {TOKEN}")
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()

    def _codes(self, ext):
        p = Product.objects.get(external_id=ext)
        return sorted(p.barcodes.values_list("barcode", flat=True))

    def test_array_of_strings_is_saved(self):
        body = self._send(_item("G1", ["4601234567890", "2000000000017"]))
        self.assertEqual(self._codes("G1"), ["2000000000017", "4601234567890"])
        self.assertEqual(body["barcodes"], {"added": 2, "moved": 0, "removed": 0})
        self.assertEqual(body["errors"], [])
        self.assertNotIn("barcodes", body["unknownKeys"])

    def test_objects_with_barcode_key_are_understood(self):
        self._send(_item("G1", [{"barcode": "4601234567890"}, {"barcode": " 46012 "}]))
        self.assertEqual(self._codes("G1"), ["46012", "4601234567890"])

    def test_empties_and_repeats_dropped(self):
        self._send(_item("G1", [None, "", "  ", "4601234567890", "4601234567890"]))
        self.assertEqual(self._codes("G1"), ["4601234567890"])

    def test_bad_barcode_reported_rest_accepted(self):
        body = self._send(_item("G1", ["4601234567890", "46 01", "9" * 65]))
        self.assertEqual(self._codes("G1"), ["4601234567890"])
        self.assertEqual(len(body["errors"]), 2)
        self.assertTrue(all("штрихкод" in e for e in body["errors"]))

    def test_new_list_replaces_old(self):
        self._send(_item("G1", ["111", "222"]))
        body = self._send(_item("G1", ["222", "333"]))
        self.assertEqual(self._codes("G1"), ["222", "333"])
        self.assertEqual(body["barcodes"], {"added": 1, "moved": 0, "removed": 1})

    def test_missing_field_keeps_barcodes(self):
        self._send(_item("G1", ["111"]))
        self._send(_item("G1"))  # поля нет — не трогаем
        self.assertEqual(self._codes("G1"), ["111"])

    def test_empty_array_clears(self):
        self._send(_item("G1", ["111"]))
        self._send(_item("G1", []))
        self.assertEqual(self._codes("G1"), [])

    def test_barcode_moves_to_another_position(self):
        self._send(_item("G1", ["111"]))
        body = self._send(_item("G2", ["111"]))
        self.assertEqual(self._codes("G1"), [])
        self.assertEqual(self._codes("G2"), ["111"])
        self.assertEqual(body["barcodes"]["moved"], 1)

    def test_swap_between_positions_in_one_batch(self):
        self._send(_item("G1", ["111"]), _item("G2", ["222"]))
        self._send(_item("G1", ["222"]), _item("G2", ["111"]))
        self.assertEqual(self._codes("G1"), ["222"])
        self.assertEqual(self._codes("G2"), ["111"])

    def test_same_barcode_on_two_positions_in_batch_is_refused(self):
        self._send(_item("G1", ["111"]))
        body = self._send(_item("G1", ["111"]), _item("G2", ["111", "222"]))
        self.assertTrue(any("111" in e and "нескольких" in e for e in body["errors"]))
        self.assertEqual(self._codes("G1"), ["111"])  # у прежней позиции остался
        self.assertEqual(self._codes("G2"), ["222"])

    def test_one_barcode_one_position_in_database(self):
        self._send(_item("G1", ["111"]))
        self.assertEqual(ProductBarcode.objects.filter(barcode="111").count(), 1)


@override_settings(INTEGRATION_1C_TOKEN=TOKEN)
class OneCBarcodeInOrderTests(TestCase):
    def test_order_line_carries_position_barcodes(self):
        p = Product.objects.create(id="p1", name="Кроссовки", category_id="shoes",
                                   price=11990, article="AR-X1", external_id="GUID-1")
        ProductBarcode.objects.create(product=p, barcode="4601234567890")
        Order.objects.create(
            user_id="u1", order_id="МАТА-12345678", total=11990, status="paid",
            payment_status="paid", payment_id="yk-1",
            payload={"items": [{"productId": "p1", "productName": "Кроссовки",
                                "quantity": 1, "price": 11990},
                               {"productId": "gone", "productName": "Удалённый",
                                "quantity": 1, "price": 100}],
                     "checkoutData": {"phone": "+79148278470"}})
        orders = self.client.get(PULL, HTTP_AUTHORIZATION=f"Bearer {TOKEN}").json()["orders"]
        items = orders[0]["items"]
        self.assertEqual(items[0]["barcodes"], ["4601234567890"])
        self.assertEqual(items[1]["barcodes"], [])
