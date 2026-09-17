"""Список товаров в админке: остаток из 1С на виду, служебный ID убран."""
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import TestCase

from catalog.admin import ProductAdmin
from catalog.models import Product
from common.testutils import login_admin


class ProductListTests(TestCase):
    def setUp(self):
        get_user_model().objects.create_superuser("owner_s", "o@t.dev", "OwnerPass!2026")
        login_admin(self.client, "owner_s", "OwnerPass!2026")
        self.product = Product.objects.create(
            id="p-stock", name="Кроссовки", category_id="shoes", price=1000,
            stock_count=10, stock_by_size={"42": 7, "40": 3, "41": 0},
        )

    def _stock_html(self):
        return str(ProductAdmin(Product, admin.site).stock(self.product))

    def test_stock_column_instead_of_id(self):
        r = self.client.get("/admin/catalog/product/")
        self.assertEqual(r.status_code, 200)
        columns = r.context["cl"].list_display
        self.assertIn("stock", columns)
        self.assertNotIn("id", columns)

    def test_total_and_sizes_in_order(self):
        html = self._stock_html()
        self.assertIn("10 шт", html)
        self.assertIn("40: 3 · 41: 0 · 42: 7", html)

    def test_clothing_sizes_follow_size_order(self):
        """По алфавиту вышло бы «L, M, S, XL» — так размеры никто не читает."""
        self.product.stock_by_size = {"L": 1, "S": 2, "XL": 0, "M": 5}
        self.assertIn("S: 2 · M: 5 · L: 1 · XL: 0", self._stock_html())

    def test_zero_stock_is_highlighted(self):
        self.product.stock_count, self.product.stock_by_size = 0, {}
        self.assertIn("#dc2626", self._stock_html())

    def test_no_stock_from_1c_is_a_dash(self):
        self.product.stock_count = None
        html = self._stock_html()
        self.assertIn("—", html)
        self.assertIn("1С ещё не присылала остаток", html)

    def test_search_by_id_still_works(self):
        """Столбец ID убрали, но найти товар по нему можно."""
        r = self.client.get("/admin/catalog/product/?q=p-stock")
        self.assertContains(r, "Кроссовки")
