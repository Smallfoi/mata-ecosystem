"""Уменьшенные копии фото сайта (этап 6 оптимизации, 21.11.2026): делаются для
широких фото, отдаются через imageSrcset, устаревают при замене фото."""
import io
import shutil
import tempfile

from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from PIL import Image

from catalog.models import SiteContent
from catalog.site_variants import make_all, make_variants, srcset

_MEDIA = tempfile.mkdtemp()


def _webp(width, height=None):
    buf = io.BytesIO()
    Image.new("RGB", (width, height or width // 2), (200, 30, 30)).save(buf, format="WEBP")
    return ContentFile(buf.getvalue(), name="hero_web.webp")


@override_settings(MEDIA_ROOT=_MEDIA)
class SiteVariantsTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_MEDIA, ignore_errors=True)

    def _sc(self, width):
        sc = SiteContent(key="hero.img")
        sc.image.save("hero_web.webp", _webp(width), save=True)
        return sc

    def test_wide_photo_gets_two_copies_and_srcset(self):
        sc = self._sc(2560)
        self.assertTrue(make_variants(sc))
        sc.refresh_from_db()
        self.assertEqual(sc.image_variants["width"], 2560)
        for w in (640, 1280):
            with Image.open(sc.image.storage.open(sc.image_variants[str(w)])) as im:
                self.assertEqual(im.width, w)
        data = sc.to_json()
        self.assertIn("640w", data["imageSrcset"])
        self.assertIn("1280w", data["imageSrcset"])
        self.assertIn("2560w", data["imageSrcset"])
        self.assertFalse(make_variants(sc))  # повторно — ничего не делает

    def test_narrow_photo_needs_only_smaller_copies(self):
        sc = self._sc(900)
        make_variants(sc)
        sc.refresh_from_db()
        self.assertIn("640", sc.image_variants)
        self.assertNotIn("1280", sc.image_variants)

    def test_replaced_photo_drops_old_copies_until_remade(self):
        sc = self._sc(2000)
        make_variants(sc)
        sc.image.save("new_web.webp", _webp(2000), save=True)
        sc.refresh_from_db()
        self.assertEqual(srcset(sc), "")
        self.assertNotIn("imageSrcset", sc.to_json())
        self.assertEqual(make_all(), 1)
        sc.refresh_from_db()
        self.assertIn("1280w", srcset(sc))

    def test_api_returns_srcset(self):
        sc = self._sc(2560)
        make_variants(sc)
        r = self.client.get("/v1/site/content").json()
        self.assertIn("imageSrcset", r["hero.img"])
