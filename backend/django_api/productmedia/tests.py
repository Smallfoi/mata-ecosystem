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


import tempfile  # noqa: E402

from django.test import override_settings  # noqa: E402

from catalog import photos as photolib  # noqa: E402
from catalog.models import ProductPhoto  # noqa: E402
from productmedia import service  # noqa: E402
from productmedia.models import PhotoBatch, PhotoJob  # noqa: E402


def _png_bytes(color=(10, 20, 30), size=(8, 8)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class PhotoPipelineServiceTests(TestCase):
    """Оркестрация: приём партии по артикулам → ИИ (мок) → webp → карточка."""

    @classmethod
    def setUpTestData(cls):
        # model_key в бою строит импорт/rebuild_display_name; в тесте задаём явно,
        # чтобы shop_model_key был непустым (по нему витрина группирует снимки).
        Product.objects.create(id="pp1", name="Худи", category_id="c", price=2000,
                               article="HD-1", colors=["Чёрный"], model_key="HOODIE")

    def _batch(self, track="catalog"):
        return PhotoBatch.objects.create(track=track)

    def test_intake_matches_pending_and_skips_unknown(self):
        batch = self._batch()
        jobs = service.intake(batch, [
            {"article": "hd-1", "content": _png_bytes(), "filename": "a.png"},
            {"article": "НЕТ", "content": _png_bytes(), "filename": "b.png"},
        ])
        self.assertEqual(len(jobs), 2)
        matched = next(j for j in jobs if j.product_id == "pp1")
        self.assertEqual(matched.status, PhotoJob.STATUS_PENDING)
        self.assertTrue(matched.source.name)                 # исходник сохранён
        skipped = next(j for j in jobs if j.product_id is None)
        self.assertEqual(skipped.status, PhotoJob.STATUS_SKIPPED)

    @mock.patch("productmedia.processing.process")
    def test_run_job_attaches_photo_to_showcase(self, m_proc):
        m_proc.return_value = _png_bytes((200, 50, 50), (1200, 1200))
        batch = self._batch()
        job = service.intake(batch, [
            {"article": "HD-1", "content": _png_bytes(), "filename": "a.png"}])[0]
        service.run_job(job)
        job.refresh_from_db()
        self.assertEqual(job.status, PhotoJob.STATUS_DONE)
        self.assertTrue(job.master.name)                     # мастер сохранён на задании
        self.assertIsNotNone(job.attached_at)
        photos = ProductPhoto.objects.filter(
            model_key=job.product.shop_model_key, color="Чёрный")
        self.assertEqual(photos.count(), 1)                  # снимок в галерее витрины
        self.assertTrue(photos.first().image.name.endswith(".webp"))
        self.assertTrue(photos.first().thumb.name)           # миниатюра сделана хранилищем

    @mock.patch("productmedia.processing.process")
    def test_main_job_becomes_cover(self, m_proc):
        m_proc.return_value = _png_bytes((0, 150, 0), (1000, 1000))
        p = Product.objects.get(id="pp1")
        pre = photolib.attach(p.shop_model_key, color="Чёрный",
                              data=_png_bytes(), first=False)
        batch = self._batch()
        job = service.intake(batch, [
            {"article": "HD-1", "content": _png_bytes(),
             "filename": "a.png", "attach_as": "main"}])[0]
        service.run_job(job)
        self.assertEqual(
            ProductPhoto.objects.filter(model_key=p.shop_model_key).count(), 2)
        cover = ProductPhoto.objects.get(
            model_key=p.shop_model_key, color="Чёрный", order=0)
        self.assertNotEqual(cover.id, pre.id)                # обложкой стал main-снимок

    @mock.patch.dict("os.environ", {}, clear=False)
    def test_run_job_failed_without_key_keeps_showcase(self):
        import os
        os.environ.pop("OPENAI_API_KEY", None)               # провайдер выключен
        batch = self._batch()
        job = service.intake(batch, [
            {"article": "HD-1", "content": _png_bytes(), "filename": "a.png"}])[0]
        service.run_job(job)
        job.refresh_from_db()
        self.assertEqual(job.status, PhotoJob.STATUS_FAILED)
        self.assertTrue(job.error)
        self.assertEqual(ProductPhoto.objects.count(), 0)    # в галерею ничего не попало

    @mock.patch("productmedia.processing.process")
    def test_run_job_failed_when_color_full(self, m_proc):
        m_proc.return_value = _png_bytes((9, 9, 9), (800, 800))
        p = Product.objects.get(id="pp1")
        for _ in range(ProductPhoto.MAX_PER_COLOR):          # цвет уже заполнен (6)
            photolib.attach(p.shop_model_key, color="Чёрный", data=_png_bytes())
        batch = self._batch()
        job = service.intake(batch, [
            {"article": "HD-1", "content": _png_bytes(), "filename": "a.png"}])[0]
        service.run_job(job)
        job.refresh_from_db()
        self.assertEqual(job.status, PhotoJob.STATUS_FAILED)
        self.assertIn("6", job.error)                        # понятная ошибка про лимит
        self.assertEqual(
            ProductPhoto.objects.filter(
                model_key=p.shop_model_key, color="Чёрный").count(),
            ProductPhoto.MAX_PER_COLOR)                       # седьмой не добавлен

    @mock.patch("productmedia.processing.process")
    def test_run_batch_counts_done(self, m_proc):
        m_proc.return_value = _png_bytes((5, 5, 5), (900, 900))
        batch = self._batch()
        service.intake(batch, [
            {"article": "HD-1", "content": _png_bytes(), "filename": "a.png"},
            {"article": "НЕТ", "content": _png_bytes(), "filename": "b.png"},
        ])
        summary = service.run_batch(batch)
        self.assertEqual(summary["done"], 1)                 # только сопоставленный прогнан
        self.assertEqual(summary["failed"], 0)
        # несопоставленный уже помечен skipped на приёме — в очередь run_batch не попадает
        self.assertEqual(batch.jobs.filter(status=PhotoJob.STATUS_SKIPPED).count(), 1)

    @mock.patch("productmedia.processing.process")
    def test_run_job_preview_skips_attach(self, m_proc):
        # attach=False (предпросмотр): мастер/webp на задании есть, витрину не трогаем.
        m_proc.return_value = _png_bytes((7, 7, 7), (1100, 1100))
        batch = self._batch()
        job = service.intake(batch, [
            {"article": "HD-1", "content": _png_bytes(), "filename": "a.png"}])[0]
        service.run_job(job, attach=False)
        job.refresh_from_db()
        self.assertEqual(job.status, PhotoJob.STATUS_DONE)
        self.assertTrue(job.master.name)
        self.assertTrue(job.webp.name.endswith(".webp"))
        self.assertIsNone(job.attached_at)
        self.assertEqual(ProductPhoto.objects.count(), 0)    # в галерею ничего не выложено


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class PhotoTestCommandTests(TestCase):
    """Команда photo_test: предпросмотр не трогает витрину, --apply выкладывает."""

    def setUp(self):
        from django.core.files.base import ContentFile
        self.p = Product.objects.create(id="cmd1", name="Кроссовки", category_id="c",
                                        price=5000, article="RUN-9",
                                        colors=["Белый"], model_key="RUNNER")
        self.p.image.save("cur.png", ContentFile(_png_bytes((1, 2, 3), (600, 600))), save=True)

    @mock.patch("productmedia.processing.process")
    def test_preview_does_not_touch_showcase(self, m_proc):
        from django.core.management import call_command
        m_proc.return_value = _png_bytes((10, 10, 10), (1000, 1000))
        call_command("photo_test", "--article", "RUN-9", "--from-product")
        self.assertEqual(ProductPhoto.objects.count(), 0)    # предпросмотр — витрина чиста
        self.assertEqual(PhotoJob.objects.filter(status=PhotoJob.STATUS_DONE).count(), 1)

    @mock.patch("productmedia.processing.process")
    def test_apply_attaches_to_showcase(self, m_proc):
        from django.core.management import call_command
        m_proc.return_value = _png_bytes((20, 20, 20), (1000, 1000))
        call_command("photo_test", "--article", "RUN-9", "--from-product", "--apply")
        self.assertEqual(
            ProductPhoto.objects.filter(model_key="RUNNER", color="Белый").count(), 1)
