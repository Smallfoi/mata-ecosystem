"""Видимость того, что реально присылает 1С.

Раньше любое поле мимо обмена отбрасывалось молча: 1С считает, что присылает размер
и цвет, а у нас в карточке пусто — и спор упирается в слово против слова. Теперь
приём возвращает и пишет в журнал пример позиции и имена полей, которых нет в обмене.
"""
from django.test import TestCase, override_settings

from integrations.models import OneCExchange

TOKEN = "test-1c-token"
CATALOG = "/v1/integrations/1c/catalog"
PRICES = "/v1/integrations/1c/prices"
ORDERS = "/v1/integrations/1c/orders"


@override_settings(INTEGRATION_1C_TOKEN=TOKEN)
class PayloadVisibilityTests(TestCase):
    def _post(self, url, payload):
        return self.client.post(url, payload, content_type="application/json",
                                HTTP_AUTHORIZATION=f"Bearer {TOKEN}")

    def test_fields_we_do_not_read_are_named(self):
        r = self._post(CATALOG, {"products": [{
            "id": "SS-1", "name": "Кроссовки", "categoryId": "shoes",
            "size": "XL", "color": "Синий", "Номенклатура": "что-то своё",
        }]})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["unknownKeys"], ["color", "size", "Номенклатура"])
        row = OneCExchange.objects.get(operation="catalog")
        self.assertEqual(row.unknown_keys, ["color", "size", "Номенклатура"])

    def test_sample_keeps_the_richest_position(self):
        """Бедная строка ничего не объясняет — в пример идёт самая полная."""
        self._post(CATALOG, {"products": [
            {"id": "SS-1", "name": "Простой"},
            {"id": "SS-2", "name": "Полный", "categoryId": "shoes", "price": 100,
             "size": "42", "color": "Чёрный"},
        ]})
        sample = OneCExchange.objects.get(operation="catalog").sample
        self.assertEqual(sample["id"], "SS-2")
        self.assertEqual(sample["size"], "42")

    def test_long_values_are_trimmed(self):
        self._post(CATALOG, {"products": [
            {"id": "SS-3", "name": "Товар", "description": "о" * 900}]})
        sample = OneCExchange.objects.get(operation="catalog").sample
        self.assertEqual(len(sample["description"]), 200)

    def test_prices_stream_is_visible_too(self):
        self._post(CATALOG, {"products": [{"id": "SS-4", "name": "Товар"}]})
        r = self._post(PRICES, {"prices": [{"id": "SS-4", "price": 100, "Остаток": 3}]})
        self.assertEqual(r.json()["unknownKeys"], ["Остаток"])
        row = OneCExchange.objects.filter(operation="prices").first()
        self.assertEqual(row.sample["id"], "SS-4")

    def test_known_fields_are_not_reported_as_unknown(self):
        r = self._post(CATALOG, {"products": [{
            "id": "SS-5", "article": "A1", "name": "Товар", "categoryId": "c", "brand": "МАТА",
            "price": 10, "oldPrice": 20, "description": "текст", "sizes": ["42"],
            "colors": ["Чёрный"], "images": ["https://host/1.jpg"], "active": True,
            "updatedAt": "2026-09-18T10:00:00Z", "weightG": 850, "lengthCm": 33,
            "widthCm": 22, "heightCm": 12,
        }]})
        self.assertEqual(r.json()["unknownKeys"], [])

    def test_orders_stream_keeps_no_sample(self):
        """В заказах данные покупателя — пример позиции не храним."""
        self.client.get(ORDERS, HTTP_AUTHORIZATION=f"Bearer {TOKEN}")
        row = OneCExchange.objects.filter(operation="orders").first()
        self.assertIsNotNone(row)
        self.assertEqual(row.sample, {})
        self.assertEqual(row.unknown_keys, [])
