"""Вес и габариты посылки (D-79): товар → категория → родитель → общий запас."""
from django.test import TestCase

from catalog.models import Category, Product
from catalog.parcel import FALLBACK, parcel_for


class ParcelTests(TestCase):
    def setUp(self):
        Category.objects.create(id="wear", name="Одежда", default_weight_g=400,
                                default_length_cm=30, default_width_cm=20, default_height_cm=5)
        Category.objects.create(id="tees", name="Футболки", parent_id="wear")

    def _product(self, **kw):
        return Product.objects.create(id=kw.pop("id", "p1"), name="Товар",
                                      category_id=kw.pop("category_id", "tees"), price=1000, **kw)

    def test_own_weight_and_size_win(self):
        p = self._product(weight_g=850, length_cm=33, width_cm=22, height_cm=12)
        self.assertEqual(parcel_for(p), {"weight_g": 850, "length_cm": 33, "width_cm": 22,
                                         "height_cm": 12, "source": "product"})

    def test_empty_category_falls_back_to_parent(self):
        """У «Футболок» типовой посылки нет — берём «Одежду»."""
        parcel = parcel_for(self._product())
        self.assertEqual(parcel["weight_g"], 400)
        self.assertEqual(parcel["source"], "category")

    def test_known_weight_is_kept_while_size_comes_from_category(self):
        """Склад знает вес, но не коробку: известное не затираем типовым."""
        parcel = parcel_for(self._product(weight_g=250))
        self.assertEqual(parcel["weight_g"], 250)
        self.assertEqual(parcel["height_cm"], 5)

    def test_unknown_category_uses_fallback(self):
        parcel = parcel_for(self._product(category_id="nowhere"))
        self.assertEqual(parcel["source"], "fallback")
        self.assertEqual(parcel["weight_g"], FALLBACK["weight_g"])

    def test_category_loop_does_not_hang(self):
        """Категории, ссылающиеся друг на друга, не должны вешать расчёт."""
        Category.objects.create(id="a", name="A", parent_id="b")
        Category.objects.create(id="b", name="B", parent_id="a")
        self.assertEqual(parcel_for(self._product(category_id="a"))["source"], "fallback")
