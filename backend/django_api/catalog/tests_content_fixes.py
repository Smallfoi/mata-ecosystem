from django.test import TestCase

from catalog.content_fixes import (
    apply_copy_fixes,
    load_pairs,
    unpublish_demo_banners,
)
from catalog.models import Banner, Product


class DemoBannersTests(TestCase):
    def test_only_demo_banners_on_stock_photos_are_unpublished(self):
        demo = Banner.objects.create(id=55, title="Весна 2025",
                                     image_url="assets/images/products/a.jpg")
        owned = Banner.objects.create(id=56, title="Своё фото",
                                      image_url="https://cdn/x.jpg")
        other = Banner.objects.create(id=90, title="Новый",
                                      image_url="assets/images/products/b.jpg")
        self.assertEqual(unpublish_demo_banners(Banner), 1)
        demo.refresh_from_db(); owned.refresh_from_db(); other.refresh_from_db()
        self.assertFalse(demo.is_published)
        self.assertTrue(owned.is_published)
        self.assertTrue(other.is_published)
        self.assertEqual(unpublish_demo_banners(Banner), 0)  # повторно — ничего


class CopyFixesTests(TestCase):
    PAIRS = [{"old": "ежедневных перемещений", "new": "повседневной носки"}]

    def _product(self, **kw):
        n = Product.objects.count()
        return Product.objects.create(id=f"p{n}", name=f"P{n}", price=1, category_id="c", **kw)

    def test_replaces_fragment_and_marks_override(self):
        p = self._product(description="Модель для ежедневных перемещений, долгой ходьбы.")
        q = self._product(description="Другой текст.")
        self.assertEqual(apply_copy_fixes(Product, self.PAIRS), 1)
        p.refresh_from_db(); q.refresh_from_db()
        self.assertEqual(p.description, "Модель для повседневной носки, долгой ходьбы.")
        self.assertIn("description", p.overrides)
        self.assertEqual(q.description, "Другой текст.")
        self.assertNotIn("description", q.overrides or [])
        self.assertEqual(apply_copy_fixes(Product, self.PAIRS), 0)  # идемпотентно

    def test_shipped_pairs_are_valid(self):
        pairs = load_pairs("copy_2026_11_26.json")
        self.assertGreater(len(pairs), 50)
        olds = [x["old"] for x in pairs]
        self.assertEqual(len(olds), len(set(olds)))
        for x in pairs:
            self.assertTrue(x["old"].strip() and x["new"].strip())
            self.assertNotEqual(x["old"], x["new"])
            # new не содержит old — иначе повторный прогон правил бы снова
            self.assertNotIn(x["old"], x["new"])
