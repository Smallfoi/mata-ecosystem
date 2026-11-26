"""Публичные правила начисления за покупку: /v1/loyalty/rules (аудит сайта 26.11.2026)."""
from django.test import TestCase

from catalog.models import Category
from loyalty import config


class RulesTests(TestCase):
    def test_disabled_program_says_so(self):
        config.set_value("LOYALTY_V1_ENABLED", False, by="test")
        resp = self.client.get("/v1/loyalty/rules")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"enabled": False})

    def test_rates_and_exclusions_without_token(self):
        config.set_value("LOYALTY_V1_ENABLED", True, by="test")
        Category.objects.create(id="sis", name="SIS")
        Category.objects.create(id="sis-gel", name="Гели", parent_id="sis")
        config.set_value("NO_ACCRUAL_CATEGORIES_1C", ["sis"], by="test")
        config.set_value("NO_ACCRUAL_BRANDS", ["Rock Bros"], by="test")
        config.set_value("NO_ACCRUAL_PRODUCTS", ["p9"], by="test")
        data = self.client.get("/v1/loyalty/rules").json()
        self.assertTrue(data["enabled"])
        self.assertEqual([lv["key"] for lv in data["levels"]], list(config.LEVELS))
        self.assertEqual(data["levels"][0]["purchaseRate"],
                         float(config.by_level("RATE_PURCHASE", 0)))
        # Категория — вместе с подкатегориями, бренд — в нижнем регистре.
        self.assertEqual(data["noAccrual"]["categories"], ["sis", "sis-gel"])
        self.assertEqual(data["noAccrual"]["brands"], ["rock bros"])
        self.assertEqual(data["noAccrual"]["products"], ["p9"])
