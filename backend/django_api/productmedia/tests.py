"""Фотопайплайн товаров: привязка папок по артикулу + генерация webp из мастера."""
import io

from django.test import TestCase
from PIL import Image

from catalog.models import Product
from productmedia.images import make_webp
from productmedia.matching import match_folders_to_products


class ArticleMatchTests(TestCase):
    """Вариант А: папка = артикул. Совпадение — по нормализованному артикулу."""

    @classmethod
    def setUpTestData(cls):
        Product.objects.create(id="p1", name="Лонгслив", category_id="c",
                               price=1000, article="ART-100")
        Product.objects.create(id="p2", name="Шорты", category_id="c",
                               price=800, article="ART-200")

    def test_matches_case_and_space_insensitive(self):
        r = match_folders_to_products([" art-100 ", "ART-200"])
        ids = sorted(m["productId"] for m in r["matched"])
        self.assertEqual(ids, ["p1", "p2"])
        self.assertEqual(r["unmatched"], [])

    def test_unmatched_folder_reported_not_dropped(self):
        r = match_folders_to_products(["ART-100", "НЕТ-ТАКОГО"])
        self.assertEqual(len(r["matched"]), 1)
        self.assertEqual(r["unmatched"], [{"folder": "НЕТ-ТАКОГО"}])

    def test_blank_and_duplicate_folders_ignored(self):
        r = match_folders_to_products(["", "  ", "ART-100", "ART-100"])
        self.assertEqual(len(r["matched"]), 1)  # дубль не задваивается


class WebpTests(TestCase):
    def test_master_becomes_smaller_webp(self):
        buf = io.BytesIO()
        Image.new("RGB", (3000, 3000), (120, 130, 40)).save(buf, "PNG")
        webp = make_webp(buf.getvalue(), max_px=1600)
        out = Image.open(io.BytesIO(webp))
        self.assertEqual(out.format, "WEBP")
        self.assertLessEqual(max(out.size), 1600)
        self.assertLess(len(webp), len(buf.getvalue()))  # легче мастера
