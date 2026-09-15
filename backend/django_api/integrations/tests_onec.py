"""Обмен с 1С (D-62): приём каталога, цен и правило «переопределённое не трогаем»."""
from django.test import TestCase, override_settings
from django.urls import reverse

from catalog.models import Product

TOKEN = "test-1c-token"
CATALOG = "/v1/integrations/1c/catalog"
PRICES = "/v1/integrations/1c/prices"


@override_settings(INTEGRATION_1C_TOKEN=TOKEN)
class OneCImportTests(TestCase):
    def _post(self, url, payload, token=TOKEN):
        headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"} if token else {}
        return self.client.post(url, payload, content_type="application/json", **headers)

    def test_token_required(self):
        """Без токена номенклатуру не принимаем."""
        r = self.client.post(CATALOG, {"products": []}, content_type="application/json")
        self.assertEqual(r.status_code, 401)

    def test_wrong_token_rejected(self):
        r = self._post(CATALOG, {"products": []}, token="nope")
        self.assertEqual(r.status_code, 401)

    def test_creates_product(self):
        r = self._post(CATALOG, {"products": [{
            "id": "SS-0042", "article": "AR-X1", "name": "Кроссовки Air Runner X1",
            "categoryId": "shoes", "brand": "МАТА", "sizes": ["40", "41"],
            "description": "Из 1С", "active": True,
        }]})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["created"], 1)
        p = Product.objects.get(external_id="SS-0042")
        self.assertEqual(p.name, "Кроссовки Air Runner X1")
        self.assertEqual(p.sizes, ["40", "41"])
        self.assertEqual(p.article, "AR-X1")

    def test_repeat_import_updates_not_duplicates(self):
        """Повторная выгрузка не плодит дубли — ключ обмена неизменный."""
        item = {"id": "SS-1", "article": "A1", "name": "Товар", "categoryId": "c"}
        self._post(CATALOG, {"products": [item]})
        self._post(CATALOG, {"products": [dict(item, name="Товар 2")]})
        self.assertEqual(Product.objects.filter(external_id="SS-1").count(), 1)
        self.assertEqual(Product.objects.get(external_id="SS-1").name, "Товар 2")

    def test_owner_override_is_kept(self):
        """Главное правило: поле, которое владелец правил в Конструкторе, импорт не затирает."""
        self._post(CATALOG, {"products": [
            {"id": "SS-2", "name": "Товар", "categoryId": "c", "description": "Из 1С"}]})
        p = Product.objects.get(external_id="SS-2")
        p.description = "Моё описание"
        p.set_override("description")
        p.save()

        r = self._post(CATALOG, {"products": [
            {"id": "SS-2", "name": "Товар", "categoryId": "c", "description": "Новое из 1С"}]})
        p.refresh_from_db()
        self.assertEqual(p.description, "Моё описание")          # витрина показывает владельца
        self.assertEqual(p.from_1c["description"], "Новое из 1С")  # но 1С сохранили
        self.assertIn("description", r.json()["keptByOwner"])
        self.assertIn("description", p.onec_diff())                # расхождение видно

    def test_prices_and_stock(self):
        self._post(CATALOG, {"products": [{"id": "SS-3", "name": "Т", "categoryId": "c"}]})
        r = self._post(PRICES, {"prices": [{"id": "SS-3", "price": 11990, "oldPrice": 13990,
                                            "variants": [{"size": "40", "stock": 3},
                                                         {"size": "41", "stock": 0}]}]})
        self.assertEqual(r.status_code, 200)
        p = Product.objects.get(external_id="SS-3")
        self.assertEqual(p.price, 11990)
        self.assertEqual(p.stock_count, 3)
        self.assertTrue(p.in_stock)

    def test_price_override_kept_but_stock_always_from_1c(self):
        """Цену владелец удержит, а остаток — всегда из 1С (иначе продадим то, чего нет)."""
        self._post(CATALOG, {"products": [{"id": "SS-4", "name": "Т", "categoryId": "c"}]})
        p = Product.objects.get(external_id="SS-4")
        p.price = 9990
        p.set_override("price")
        p.save()

        self._post(PRICES, {"prices": [{"id": "SS-4", "price": 12990, "stock": 0}]})
        p.refresh_from_db()
        self.assertEqual(p.price, 9990)            # своя цена осталась
        self.assertEqual(p.stock_count, 0)         # остаток принят
        self.assertFalse(p.in_stock)

    def test_inactive_hidden_from_storefront(self):
        """active=false в 1С убирает товар с витрины, не трогая публикацию владельца."""
        self._post(CATALOG, {"products": [
            {"id": "SS-5", "name": "Снят", "categoryId": "c", "active": False}]})
        p = Product.objects.get(external_id="SS-5")
        self.assertFalse(p.is_active_1c)
        self.assertTrue(p.is_published)            # решение владельца не тронуто
        ids = [x["id"] for x in self.client.get("/v1/products").json()]
        self.assertNotIn(p.id, ids)

    def test_status_endpoint(self):
        r = self.client.get("/v1/integrations/1c/status")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["enabled"])


@override_settings(INTEGRATION_1C_TOKEN=TOKEN)
class OneCParcelTests(TestCase):
    """Вес и габариты из 1С (D-79): граммы и сантиметры для расчёта доставки."""

    def _post(self, products):
        return self.client.post(CATALOG, {"products": products}, content_type="application/json",
                                HTTP_AUTHORIZATION=f"Bearer {TOKEN}")

    def _item(self, **kw):
        return {"id": "SS-W", "article": "W1", "name": "Кроссовки", "categoryId": "shoes", **kw}

    def test_weight_and_size_are_imported(self):
        r = self._post([self._item(weightG=850, lengthCm=33, widthCm=22, heightCm=12.4)])
        self.assertEqual(r.status_code, 200)
        p = Product.objects.get(external_id="SS-W")
        self.assertEqual((p.weight_g, p.length_cm, p.width_cm, p.height_cm), (850, 33, 22, 12))

    def test_missing_fields_keep_manual_values(self):
        """1С не прислала вес — ручной ввод из админки остаётся."""
        self._post([self._item()])
        Product.objects.filter(external_id="SS-W").update(weight_g=700)
        self._post([self._item(name="Кроссовки 2")])
        self.assertEqual(Product.objects.get(external_id="SS-W").weight_g, 700)

    def test_garbage_is_reported_and_not_written(self):
        self._post([self._item(weightG=500)])
        r = self._post([self._item(weightG="тяжёлые", lengthCm=0)])
        errors = r.json()["errors"]
        self.assertTrue(any("weightG не число" in e for e in errors))
        self.assertTrue(any("lengthCm должен быть больше нуля" in e for e in errors))
        p = Product.objects.get(external_id="SS-W")
        self.assertEqual(p.weight_g, 500)
        self.assertIsNone(p.length_cm)

