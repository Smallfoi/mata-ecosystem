"""Проверка загрузок полным декодированием (аудит D07)."""
import io

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from PIL import Image

from common import uploads
from common.uploads import image_extension


def _img(fmt, size=(8, 8), **kw):
    buf = io.BytesIO()
    Image.new("RGB", size, (200, 10, 10)).save(buf, fmt, **kw)
    return buf.getvalue()


def _file(data, name="x.bin"):
    return SimpleUploadedFile(name, data, content_type="application/octet-stream")


class ImageDecodeTests(SimpleTestCase):
    def test_real_images_accepted(self):
        for fmt, ext in (("PNG", "png"), ("JPEG", "jpg"), ("GIF", "gif"), ("WEBP", "webp")):
            with self.subTest(fmt=fmt):
                f = _file(_img(fmt))
                self.assertEqual(image_extension(f), (ext, None))
                self.assertEqual(f.tell(), 0, "курсор должен вернуться в начало")

    def test_signature_with_garbage_rejected(self):
        """Правильные первые байты + мусор: раньше проходило по сигнатуре."""
        png_head = bytes.fromhex("89504e470d0a1a0a")
        for data in (png_head + bytes(64), png_head + b"<html><script>alert(1)</script>",
                     bytes.fromhex("ffd8ff") + b"garbage" * 10, b"GIF89a" + bytes(40),
                     b"RIFF\x10\x00\x00\x00WEBPjunkjunk"):
            with self.subTest(data=data[:12]):
                ext, err = image_extension(_file(data))
                self.assertIsNone(ext)
                self.assertTrue(err)

    def test_truncated_image_rejected(self):
        data = _img("JPEG", size=(64, 64))
        ext, err = image_extension(_file(data[: len(data) // 2]))
        self.assertIsNone(ext)
        self.assertTrue(err)

    def test_pixel_limit(self):
        """«Бомба»: маленький файл, огромные размеры — отказ без полного разбора."""
        data = _img("PNG", size=(300, 300))
        old = uploads.MAX_IMAGE_PIXELS
        uploads.MAX_IMAGE_PIXELS = 300 * 300 - 1
        try:
            ext, err = image_extension(_file(data))
        finally:
            uploads.MAX_IMAGE_PIXELS = old
        self.assertIsNone(ext)
        self.assertIn("слишком большое", err)

    def test_allowed_subset(self):
        ext, err = image_extension(_file(_img("GIF")), allowed={"jpg", "png", "webp"})
        self.assertIsNone(ext)
        self.assertTrue(err)
