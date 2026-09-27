"""Фотопайплайн: атомарный захват заданий (аудит F04), приватное хранилище рабочих
файлов, проверка загрузок по содержимому (D07)."""
import io
import tempfile
import threading
from datetime import timedelta
from unittest import mock

from django.core.management import call_command
from django.db import connection
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from PIL import Image

from catalog.models import Product
from productmedia import service
from productmedia.models import PhotoBatch, PhotoDetail, PhotoJob


def _png(color=(10, 20, 30), size=(8, 8)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def _job(status=PhotoJob.STATUS_PENDING):
    product = Product.objects.get(pk="hj1")
    batch = PhotoBatch.objects.create()
    job = service.intake(batch, [{"article": "HJ-1", "content": _png(), "filename": "a.png"}])[0]
    assert job.product_id == product.pk
    if status != PhotoJob.STATUS_PENDING:
        PhotoJob.objects.filter(pk=job.pk).update(status=status)
        job.refresh_from_db()
    return job


def _make_product():
    Product.objects.get_or_create(
        pk="hj1", defaults=dict(name="Худи", category_id="c", price=2000, article="HJ-1",
                                colors=["Чёрный"], model_key="HJ"))


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class ClaimTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        _make_product()

    def test_second_claim_fails(self):
        job = _job()
        other = PhotoJob.objects.get(pk=job.pk)          # второй обработчик, та же строка
        self.assertTrue(service.claim(job))
        self.assertFalse(service.claim(other))
        self.assertEqual(other.status, PhotoJob.STATUS_PROCESSING)

    @mock.patch("productmedia.processing.process")
    def test_generate_skips_job_taken_by_other_worker(self, m_proc):
        """Устаревшая копия задания (status=pending в памяти) не запускает вторую генерацию."""
        m_proc.return_value = _png((1, 2, 3), (64, 64))
        job = _job()
        stale_copy = PhotoJob.objects.get(pk=job.pk)
        self.assertTrue(service.claim(job))               # первый обработчик уже работает
        service.generate(stale_copy)
        m_proc.assert_not_called()
        self.assertEqual(PhotoJob.objects.get(pk=job.pk).status, PhotoJob.STATUS_PROCESSING)

    @mock.patch("productmedia.processing.process")
    def test_queued_task_does_not_regenerate_finished_job(self, m_proc):
        """Повторная доставка задачи после готового результата — без второго запроса к ИИ."""
        m_proc.return_value = _png((1, 2, 3), (64, 64))
        job = _job()
        service.generate(job)
        self.assertEqual(job.status, PhotoJob.STATUS_REVIEW)
        from productmedia import tasks
        tasks.regenerate_job(job.pk)
        self.assertEqual(m_proc.call_count, 1)

    @mock.patch("productmedia.processing.process")
    def test_manual_run_from_any_status(self, m_proc):
        m_proc.return_value = _png((1, 2, 3), (64, 64))
        job = _job(PhotoJob.STATUS_FAILED)
        service.generate(job, from_statuses=service.CLAIM_MANUAL)
        self.assertEqual(job.status, PhotoJob.STATUS_REVIEW)

    def test_stale_processing_can_be_reclaimed(self):
        job = _job(PhotoJob.STATUS_PROCESSING)
        self.assertFalse(service.claim(PhotoJob.objects.get(pk=job.pk)))   # свежее — занято
        PhotoJob.objects.filter(pk=job.pk).update(
            updated_at=timezone.now() - service.STALE_PROCESSING - timedelta(minutes=1))
        self.assertTrue(service.claim(PhotoJob.objects.get(pk=job.pk)))

    def test_recover_stuck(self):
        fresh = _job(PhotoJob.STATUS_PROCESSING)
        stuck = _job(PhotoJob.STATUS_PROCESSING)
        PhotoJob.objects.filter(pk=stuck.pk).update(
            updated_at=timezone.now() - service.STALE_PROCESSING - timedelta(minutes=1))
        from productmedia import tasks
        self.assertEqual(tasks.recover_stuck_jobs(), {"recovered": 1})
        stuck.refresh_from_db()
        fresh.refresh_from_db()
        self.assertEqual(stuck.status, PhotoJob.STATUS_FAILED)
        self.assertIn("Повторить", stuck.error)
        self.assertEqual(fresh.status, PhotoJob.STATUS_PROCESSING)

    def test_recover_task_in_beat_schedule(self):
        from django.conf import settings
        tasks = {v["task"] for v in settings.CELERY_BEAT_SCHEDULE.values()}
        self.assertIn("productmedia.recover_stuck_jobs", tasks)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class ConcurrentClaimTests(TransactionTestCase):
    """Два обработчика одновременно берут одно задание — ИИ вызывается один раз."""

    def test_two_workers_one_generation(self):
        _make_product()
        job = _job()
        inside = threading.Event()
        release = threading.Event()
        calls = []

        def slow_process(*a, **kw):
            calls.append(1)
            inside.set()
            release.wait(10)
            return _png((1, 2, 3), (64, 64))

        def worker():
            try:
                service.generate(PhotoJob.objects.get(pk=job.pk))
            finally:
                connection.close()

        with mock.patch("productmedia.processing.process", side_effect=slow_process):
            a = threading.Thread(target=worker)
            a.start()
            self.assertTrue(inside.wait(10), "первый обработчик не дошёл до ИИ")
            b = threading.Thread(target=worker)
            b.start()
            b.join(10)
            release.set()
            a.join(10)
        self.assertEqual(len(calls), 1)
        self.assertEqual(PhotoJob.objects.get(pk=job.pk).status, PhotoJob.STATUS_REVIEW)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class PrivateStorageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        _make_product()

    def test_pipeline_fields_use_private_storage(self):
        from django.core.files.storage import storages
        private = storages["private"]
        for model, name in ((PhotoJob, "source"), (PhotoJob, "master"), (PhotoJob, "webp"),
                            (PhotoDetail, "image")):
            with self.subTest(field=name):
                self.assertIs(model._meta.get_field(name).storage, private)

    def test_showcase_photo_stays_public(self):
        from django.core.files.storage import default_storage
        from catalog.models import ProductPhoto
        self.assertIs(ProductPhoto._meta.get_field("image").storage, default_storage)

    def test_s3_private_options(self):
        from common.media import media_storages
        env = {"MEDIA_S3_BUCKET": "b", "MEDIA_S3_ACCESS_KEY": "a", "MEDIA_S3_SECRET_KEY": "s",
               "MEDIA_S3_CUSTOM_DOMAIN": "cdn.mata-club.ru"}
        st = media_storages(env)
        opts = st["private"]["OPTIONS"]
        self.assertEqual(opts["default_acl"], "private")
        self.assertTrue(opts["querystring_auth"])
        self.assertNotIn("custom_domain", opts)           # подпись по CDN-домену не работает
        self.assertEqual(opts["bucket_name"], "b")
        # Публичное хранилище витрины не изменилось.
        self.assertEqual(st["default"]["OPTIONS"]["default_acl"], "public-read")
        self.assertFalse(st["default"]["OPTIONS"]["querystring_auth"])

    def test_review_screen_uses_signed_urls(self):
        from django.contrib.auth import get_user_model
        from django.urls import reverse
        from common.testutils import login_admin
        get_user_model().objects.create_superuser("owner_ps", "ps@t.dev", "OwnerPass!2026")
        login_admin(self.client, "owner_ps", "OwnerPass!2026")
        job = _job(PhotoJob.STATUS_REVIEW)
        storage = PhotoJob._meta.get_field("source").storage
        signed = "https://storage.example/photopipeline/x?X-Amz-Signature=abc"
        with mock.patch.object(storage, "url", return_value=signed) as m_url:
            r = self.client.get(reverse("photo_review") + "?batch=%s" % job.batch_id)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(m_url.called)
        self.assertContains(r, "X-Amz-Signature=abc")

    def test_acl_command_dry_run_and_apply(self):
        out = io.StringIO()
        call_command("photopipeline_private_acl", stdout=out)
        self.assertIn("не S3", out.getvalue())             # локальный диск — нечего делать

        put = mock.Mock()
        objs = [mock.Mock(key="photopipeline/source/a.png"), mock.Mock(key="photopipeline/master/b.png")]
        bucket = mock.Mock()
        bucket.objects.filter.return_value = objs
        bucket.Object.return_value.Acl.return_value.put = put
        fake = mock.Mock(bucket=bucket)
        target = "productmedia.management.commands.photopipeline_private_acl.private_storage"
        with mock.patch(target, return_value=fake):
            out = io.StringIO()
            call_command("photopipeline_private_acl", stdout=out)
            put.assert_not_called()                         # сухой прогон ничего не меняет
            self.assertIn("2", out.getvalue())
            call_command("photopipeline_private_acl", "--apply", stdout=io.StringIO())
        bucket.objects.filter.assert_called_with(Prefix="photopipeline/")
        self.assertEqual(put.call_count, 2)
        put.assert_called_with(ACL="private")


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class UploadValidationTests(TestCase):
    """Загрузка исходников проверяет содержимое, а не заголовок клиента (D07)."""

    @classmethod
    def setUpTestData(cls):
        _make_product()

    def setUp(self):
        from django.contrib.auth import get_user_model
        from common.testutils import login_admin
        get_user_model().objects.create_superuser("owner_pu", "pu@t.dev", "OwnerPass!2026")
        login_admin(self.client, "owner_pu", "OwnerPass!2026")

    def _upload(self, data, name, attach_as="main"):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.urls import reverse
        url = reverse("photo_pipeline")
        batch = self.client.post(url, {"action": "create", "track": "catalog"}).json()["batch"]
        photo = SimpleUploadedFile(name, data, content_type="image/png")
        return self.client.post(url, {"action": "upload", "batch": batch, "article": "HJ-1",
                                      "attach_as": attach_as, "photo": photo}).json()

    def test_html_disguised_as_png_rejected(self):
        for attach_as in ("main", "detail"):
            with self.subTest(attach_as=attach_as):
                res = self._upload(b"<html><script>alert(1)</script></html>", "x.png", attach_as)
                self.assertFalse(res["ok"])
        self.assertEqual(PhotoJob.objects.count(), 0)
        self.assertEqual(PhotoDetail.objects.count(), 0)

    def test_broken_image_rejected(self):
        res = self._upload(bytes.fromhex("89504e470d0a1a0a") + bytes(64), "x.png")
        self.assertFalse(res["ok"])

    def test_stored_name_uses_real_type(self):
        res = self._upload(_png(), "evil.html")
        self.assertTrue(res["ok"])
        name = PhotoJob.objects.get(pk=res["job"]).source.name
        self.assertTrue(name.endswith(".png"), name)
        self.assertNotIn(".html", name)
