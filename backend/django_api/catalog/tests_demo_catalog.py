"""Демо-товары сняты с витрины и не возвращаются (17.11.2026)."""
from importlib import import_module
from io import StringIO

from django.apps import apps
from django.core.management import call_command
from django.test import TestCase

from catalog.models import Banner, Product

forward = import_module("catalog.migrations.0025_unpublish_demo_catalog").forward


class UnpublishDemoTests(TestCase):
    def test_only_seed_products_are_unpublished(self):
        Product.objects.create(id="3", name="Кроссовки Air Runner X1", brand="RunTech",
                               category_id="shoes", price=12990)
        # id совпал с сидом, но это товар из 1С — не трогаем.
        Product.objects.create(id="5", name="Ветровка Shield Pro", external_id="guid-1",
                               category_id="c", price=1)
        # id и название из сида, но есть артикул — тоже не демо.
        Product.objects.create(id="9", name="Кроссовки Cloud Foam", article="X1",
                               category_id="c", price=1)
        Product.objects.create(id="XRMM002-4", name="Кроссовки BMAI", article="XRMM002-4",
                               category_id="c", price=1)

        forward(apps, None)

        published = dict(Product.objects.values_list("pk", "is_published"))
        self.assertEqual(published, {"3": False, "5": True, "9": True, "XRMM002-4": True})

    def test_demo_product_is_gone_from_the_storefront(self):
        Product.objects.create(id="1", name="Беговая футболка Pro Dry", category_id="tshirts", price=2990)
        Product.objects.create(id="A1", name="Настоящий", article="A1", category_id="tshirts", price=1)
        forward(apps, None)
        ids = [p["id"] for p in self.client.get("/v1/products").json()]
        self.assertEqual(ids, ["A1"])


class SeedGuardTests(TestCase):
    def test_seed_refuses_once_the_1c_catalogue_is_live(self):
        Product.objects.create(id="A1", name="Настоящий", external_id="guid-1", category_id="c", price=1)
        Banner.objects.create(title="Настоящий баннер")
        call_command("seed_catalog", stdout=StringIO())
        self.assertFalse(Product.objects.filter(pk="1").exists())
        self.assertEqual(list(Banner.objects.values_list("title", flat=True)), ["Настоящий баннер"])

    def test_seed_still_fills_an_empty_dev_database(self):
        call_command("seed_catalog", stdout=StringIO())
        self.assertEqual(Product.objects.count(), 16)
