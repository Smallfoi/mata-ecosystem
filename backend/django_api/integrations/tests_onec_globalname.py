"""Общее название модели из 1С (`globalname`).

В `name` у 1С лежит конкретная позиция — «BMAI PURE 2.0 черный 36р.». Общее
название одно на все размеры и цвета, и раньше мы его просто теряли: поле
приходило в пачке, но в журнале значилось как непрочитанное.
"""
from django.test import TestCase, override_settings

from catalog.models import Product

TOKEN = "test-1c-token"
CATALOG = "/v1/integrations/1c/catalog"


@override_settings(INTEGRATION_1C_TOKEN=TOKEN)
class GlobalNameTests(TestCase):
    def _send(self, **fields):
        self.client.post(CATALOG, {"products": [
            {"id": "SS-G", "name": "BMAI PURE 2.0 черный 36р.", "categoryId": "c", **fields},
        ]}, content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {TOKEN}")
        return Product.objects.get(external_id="SS-G")

    def test_lowercase_key_is_read(self):
        """1С шлёт ключ строчными буквами — читаем как есть."""
        self.assertEqual(self._send(globalname="BMAI PURE 2.0").global_name, "BMAI PURE 2.0")

    def test_camel_case_key_is_read(self):
        """В договорённости было camelCase — принимаем оба написания."""
        self.assertEqual(self._send(globalName="BMAI PURE 2.0").global_name, "BMAI PURE 2.0")

    def test_empty_value_does_not_break_exchange(self):
        """У незаполненных карточек приходит null — карточка обязана сохраниться."""
        p = self._send(globalname=None, description=None)
        self.assertEqual(p.global_name, "")
        self.assertEqual(p.description, "")

    def test_field_is_no_longer_unknown_in_log(self):
        from integrations.onec import CATALOG_KEYS
        self.assertIn("globalname", CATALOG_KEYS)
