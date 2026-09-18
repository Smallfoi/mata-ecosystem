"""Размеры, цвета и фото из 1С: пустое остаётся пустым, заполненное приходит чистым.

1С заводит эти поля у каждой позиции и заполняет их постепенно. Пока карточка не
заполнена, приходит список с пустым значением — на витрине это была бы пустая
«плашка» размера.
"""
from django.test import TestCase, override_settings

from catalog.models import Product

TOKEN = "test-1c-token"
CATALOG = "/v1/integrations/1c/catalog"


@override_settings(INTEGRATION_1C_TOKEN=TOKEN)
class ListFieldsTests(TestCase):
    def _post(self, item):
        return self.client.post(CATALOG, {"products": [item]}, content_type="application/json",
                                HTTP_AUTHORIZATION=f"Bearer {TOKEN}")

    def _product(self, **fields):
        self._post({"id": "SS-L", "name": "Товар", "categoryId": "c", **fields})
        return Product.objects.get(external_id="SS-L")

    def test_empty_values_do_not_become_sizes(self):
        p = self._product(sizes=[None], colors=[None])
        self.assertEqual(p.sizes, [])
        self.assertEqual(p.colors, [])

    def test_filled_values_arrive_clean(self):
        p = self._product(sizes=[" XL ", "XL", "", None, "L"], colors=["Синий", "не указан"])
        self.assertEqual(p.sizes, ["XL", "L"])          # без повторов, пробелов и пустот
        self.assertEqual(p.colors, ["Синий"])

    def test_photos_are_cleaned_the_same_way(self):
        p = self._product(images=[None, "https://host/1.jpg", "https://host/1.jpg"])
        self.assertEqual(p.image_urls, ["https://host/1.jpg"])

    def test_raw_payload_is_kept_as_it_came(self):
        """В from_1c держим то, что прислали: по нему видно, что 1С поле шлёт."""
        p = self._product(sizes=[None])
        self.assertEqual(p.from_1c["sizes"], [None])

    def test_single_value_instead_of_list_is_accepted(self):
        """Если 1С пришлёт размер строкой, а не списком, карточка не должна ломаться."""
        p = self._product(sizes="XL")
        self.assertEqual(p.sizes, ["XL"])
