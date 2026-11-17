"""Миграция 0024: ключи STAW, фото и продажи переезжают на код модели (D-131)."""
from importlib import import_module

from django.apps import apps
from django.test import TestCase

from analytics.models import SaleLine
from catalog.models import Product, ProductPhoto
from django.utils import timezone

forward = import_module("catalog.migrations.0024_staw_model_keys").forward


class StawMigrationTests(TestCase):
    def test_keys_photos_and_sales_move_to_the_model(self):
        Product.objects.create(id="s1", name="Футболка женская STAW", article="26SADT0031850",
                               model_key="26SADT0031850", category_id="c", price=1)
        Product.objects.create(id="s2", name="Ручная", article="26SADT0031034",
                               model_key="26SADT0031034", model_key_override="СВОЯ", category_id="c", price=1)
        Product.objects.create(id="b1", name="BMAI", article="XRMM002-4", model_key="XRMM002",
                               category_id="c", price=1)
        ProductPhoto.objects.create(model_key="26SADT0031850", color="Розовый", order=0)
        ProductPhoto.objects.create(model_key="XRMM002", color="Белый", order=0)
        SaleLine.objects.create(order_pk=1, line=1, sold_at=timezone.now(), model_key="26SADT0031850")

        forward(apps, None)

        self.assertEqual(Product.objects.get(pk="s1").model_key, "26SADT003")
        self.assertEqual(Product.objects.get(pk="s2").shop_model_key, "СВОЯ", "ручная склейка сильнее")
        self.assertEqual(Product.objects.get(pk="b1").model_key, "XRMM002")
        self.assertEqual(sorted(ProductPhoto.objects.values_list("model_key", flat=True)),
                         ["26SADT003", "XRMM002"])
        self.assertEqual(SaleLine.objects.get().model_key, "26SADT003")
