"""Фото сайта в WebP (18.11.2026): загрузка кладёт WebP, старые JPEG/PNG пережимает
команда (её запускает beat), прозрачность и ориентация не теряются."""
import io
import shutil
import tempfile
from io import StringIO

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings
from PIL import Image

from catalog.models import SiteContent
from config.admin_views import _webify_image


def _img(fmt, mode="RGB", size=(3000, 2000), **save):
    im = Image.new(mode, size, (200, 30, 30, 128) if mode == "RGBA" else (200, 30, 30))
    if mode == "P":
        im = Image.new("RGB", size, (200, 30, 30)).convert("P")
        save.setdefault("transparency", 0)
    buf = io.BytesIO()
    im.save(buf, fmt, **save)
    return buf.getvalue()


def _open(content):
    content.seek(0)
    return Image.open(io.BytesIO(content.read()))


class WebifyImageTests(SimpleTestCase):
    def test_jpeg_becomes_smaller_webp(self):
        out = _webify_image(ContentFile(_img("JPEG"), name="IMG_1.jpg"))
        self.assertEqual(out.name, "IMG_1_web.webp")
        im = _open(out)
        self.assertEqual(im.format, "WEBP")
        self.assertEqual(max(im.size), 2560)

    def test_transparency_survives(self):
        for mode, name in (("RGBA", "logo.png"), ("P", "pal.png")):
            im = _open(_webify_image(ContentFile(_img("PNG", mode, size=(400, 300)), name=name)))
            self.assertEqual(im.format, "WEBP")
            self.assertIn("A", im.getbands(), mode)

    def test_already_light_file_gets_no_double_suffix(self):
        out = _webify_image(ContentFile(_img("JPEG", size=(100, 80)), name="SHS_3399_web.jpg"))
        self.assertEqual(out.name, "SHS_3399_web.webp")

    def test_not_an_image_goes_through_untouched(self):
        svg = ContentFile(b"<svg xmlns='http://www.w3.org/2000/svg'/>", name="icon.svg")
        self.assertIs(_webify_image(svg), svg)


class WebifySiteImagesCommandTests(TestCase):
    def setUp(self):
        media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media, True)
        ov = override_settings(MEDIA_ROOT=media)
        ov.enable()
        self.addCleanup(ov.disable)

    def test_old_jpeg_is_replaced_by_webp_and_removed(self):
        row = SiteContent.objects.create(key="bg.hero")
        row.image.save("SHS_1_web.jpg", ContentFile(_img("JPEG", size=(800, 600))), save=True)
        old = row.image.name
        SiteContent.objects.create(key="text.only", value="Привет")

        call_command("webify_site_images", apply=True, stdout=StringIO())

        row.refresh_from_db()
        self.assertTrue(row.image.name.endswith("SHS_1_web.webp"), row.image.name)
        self.assertTrue(default_storage.exists(row.image.name))
        self.assertFalse(default_storage.exists(old))

        out = StringIO()
        call_command("webify_site_images", apply=True, stdout=out)
        self.assertIn("Нечего пережимать", out.getvalue())

    def test_dry_run_changes_nothing(self):
        row = SiteContent.objects.create(key="bg.hero")
        row.image.save("a.jpg", ContentFile(_img("JPEG", size=(80, 60))), save=True)
        call_command("webify_site_images", stdout=StringIO())
        row.refresh_from_db()
        self.assertTrue(row.image.name.endswith(".jpg"))

    def test_beat_runs_it(self):
        tasks = {e["task"] for e in settings.CELERY_BEAT_SCHEDULE.values()}
        self.assertIn("catalog.webify_site_images", tasks)
