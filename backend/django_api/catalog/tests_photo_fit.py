"""Разметка снимка витрины (productmedia.images.measure, 27.11.2026): где на кадре
товар, цвет фона и пропорции — по ним клиенты ставят товар целиком в центр рамки."""
import io
import random

from django.test import SimpleTestCase
from PIL import Image, ImageDraw

from catalog.photos import measure_safe
from productmedia.images import measure


def _bytes(im, fmt="WEBP"):
    buf = io.BytesIO()
    im.save(buf, format=fmt, quality=90)
    return buf.getvalue()


class MeasureTests(SimpleTestCase):
    def test_shoe_low_in_tall_frame(self):
        """Как у ANTA: кадр 2:3, товар в нижней трети на сером фоне."""
        im = Image.new("RGB", (400, 600), (223, 219, 216))
        ImageDraw.Draw(im).rectangle((40, 300, 360, 480), fill=(40, 40, 45))
        fit = measure(_bytes(im))
        self.assertEqual(fit["bg"], "#dfdbd8")
        self.assertAlmostEqual(fit["ar"], 0.6667, places=3)
        l, t, r, b = fit["box"]
        self.assertAlmostEqual(l, 0.1, delta=0.02)
        self.assertAlmostEqual(t, 0.5, delta=0.02)
        self.assertAlmostEqual(r, 0.9, delta=0.02)
        self.assertAlmostEqual(b, 0.8, delta=0.02)

    def test_transparent_background_is_white_not_black(self):
        """Гели SIS: прозрачный фон — это белый, а не чёрный."""
        im = Image.new("RGBA", (300, 300), (0, 0, 0, 0))
        ImageDraw.Draw(im).rectangle((100, 30, 200, 270), fill=(20, 20, 20, 255))
        fit = measure(_bytes(im, "PNG"))
        self.assertEqual(fit["bg"], "#ffffff")
        self.assertAlmostEqual(fit["box"][0], 0.333, delta=0.02)
        self.assertAlmostEqual(fit["box"][3], 0.9, delta=0.02)

    def test_busy_background_means_whole_frame(self):
        """Снимок на улице: товар из фона не вырезать — рамка = весь кадр."""
        rnd = random.Random(1)
        im = Image.new("RGB", (200, 200))
        im.putdata([(rnd.randrange(256), rnd.randrange(256), rnd.randrange(256))
                    for _ in range(200 * 200)])
        self.assertEqual(measure(_bytes(im, "PNG"))["box"], [0.0, 0.0, 1.0, 1.0])

    def test_broken_file_gives_empty_layout_not_error(self):
        self.assertEqual(measure_safe(b"not an image"), {})
