"""Фотопайплайн товаров: привязка папок по артикулу + webp + провайдер (на моках)."""
import base64
import io
from unittest import mock

from django.test import TestCase
from PIL import Image

from catalog.models import Product
from productmedia import processing, providers
from productmedia.images import make_webp
from productmedia.matching import match_folders_to_products


def _png_b64():
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (10, 20, 30)).save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


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


class ProviderTests(TestCase):
    """GPT-провайдер: без реального ключа/сети — сетевой вызов замокан."""

    @mock.patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}, clear=False)
    @mock.patch("productmedia.providers._post_multipart")
    def test_catalog_track_calls_edits_with_high_fidelity(self, m_post):
        m_post.return_value = {"data": [{"b64_json": _png_b64()}]}
        out = processing.process(b"raw-source", track="catalog")
        self.assertTrue(out.startswith(b"\x89PNG"))  # вернулся PNG-мастер
        path, ctype, body = m_post.call_args.args
        self.assertEqual(path, "/images/edits")
        self.assertIn(b"gpt-image-1", body)
        self.assertIn(b"input_fidelity", body)   # каталог бережёт товар точнее
        self.assertIn(b"1024x1536", body)

    @mock.patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}, clear=False)
    @mock.patch("productmedia.providers._post_multipart")
    def test_model_track_no_high_fidelity(self, m_post):
        m_post.return_value = {"data": [{"b64_json": _png_b64()}]}
        processing.process(b"raw-source", track="model")
        _, _, body = m_post.call_args.args
        self.assertNotIn(b"input_fidelity", body)  # маркетинг — генерация свободнее

    def test_disabled_without_key(self):
        with mock.patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("OPENAI_API_KEY", None)
            self.assertFalse(providers.openai_enabled())
            with self.assertRaises(providers.ImageProviderError):
                processing.process(b"x", track="catalog")

    def test_unknown_track_rejected(self):
        with self.assertRaises(providers.ImageProviderError):
            processing.process(b"x", track="nope")

    def test_base_url_default_and_proxy_override(self):
        import os
        os.environ.pop("OPENAI_BASE_URL", None)
        self.assertEqual(providers.base_url(), "https://api.openai.com/v1")
        with mock.patch.dict("os.environ", {"OPENAI_BASE_URL": "https://relay.example/v1/"}):
            self.assertEqual(providers.base_url(), "https://relay.example/v1")
