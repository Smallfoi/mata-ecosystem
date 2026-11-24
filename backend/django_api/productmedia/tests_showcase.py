"""Витринная обработка: ровный фон и единый кадр БЕЗ перерисовки товара.

Главное, что здесь проверяется, — пиксели товара остаются теми же. Генерация
(`gpt-image` edit) рисует картинку заново и ракурс не сохраняет в принципе;
эта ветка существует ровно затем, чтобы снимок остался снимком.
"""
import io

from django.test import SimpleTestCase
from PIL import Image

from productmedia import images


def _photo(bg=(255, 255, 255), item=(200, 60, 70), size=(900, 600),
           box=(120, 90, 360, 400)) -> bytes:
    """Снимок: цветной прямоугольник не по центру, на ровном фоне."""
    im = Image.new("RGB", size, bg)
    im.paste(Image.new("RGB", (box[2] - box[0], box[3] - box[1]), item), (box[0], box[1]))
    out = io.BytesIO()
    im.save(out, format="PNG")
    return out.getvalue()


def _open(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data)).convert("RGB")


class ShowcaseTests(SimpleTestCase):
    def test_square_canvas_of_requested_size(self):
        im = _open(images.showcase(_photo(), size=512))
        self.assertEqual(im.size, (512, 512))

    def test_product_is_centred_with_equal_margins(self):
        """Товар был смещён влево-вверх — должен оказаться ровно по центру."""
        im = _open(images.showcase(_photo(), size=512, sharpen=False))
        box = images._content_box(im, (255, 255, 255), images.BG_TOLERANCE)
        left, top, right, bottom = box
        self.assertAlmostEqual(left, 512 - right, delta=2)
        self.assertAlmostEqual(top, 512 - bottom, delta=2)

    def test_grey_studio_background_becomes_white(self):
        """Решение владельца 25.11: витрина белая, какой бы ни была подложка."""
        im = _open(images.showcase(_photo(bg=(236, 236, 236)), size=400, sharpen=False))
        self.assertEqual(im.getpixel((5, 5)), (255, 255, 255))

    def test_white_is_everywhere_not_only_in_the_margins(self):
        """Серый фон СНИМКА тоже белеет — иначе он лёг бы рамкой вокруг товара.

        Смотрим точку впритык к товару: она внутри обрезанного кадра, то есть
        там, где раньше оставалась подложка исходника.
        """
        data = images.showcase(_photo(bg=(236, 236, 236), box=(300, 250, 420, 330)),
                               size=400, sharpen=False)
        im = _open(data)
        box = images._content_box(im, (255, 255, 255), images.BG_TOLERANCE)
        just_outside = (max(0, box[0] - 3), (box[1] + box[3]) // 2)
        self.assertEqual(im.getpixel(just_outside), (255, 255, 255))

    def test_product_colour_survives(self):
        """Цвет товара не «улучшается»: как сняли, так и осталось."""
        im = _open(images.showcase(_photo(item=(40, 90, 200)), size=600, sharpen=False))
        self.assertEqual(im.getpixel((300, 300)), (40, 90, 200))

    def test_two_photos_of_different_framing_come_out_alike(self):
        """Единый вид витрины: разный кадр на входе — одинаковая рамка на выходе."""
        a = _open(images.showcase(_photo(box=(50, 40, 300, 500)), size=512, sharpen=False))
        b = _open(images.showcase(_photo(size=(1400, 900), box=(700, 100, 900, 700)),
                                  size=512, sharpen=False))
        box_a = images._content_box(a, (255, 255, 255), images.BG_TOLERANCE)
        box_b = images._content_box(b, (255, 255, 255), images.BG_TOLERANCE)
        # Поля сверху и снизу у вертикальных предметов совпадают с точностью до пикселя.
        self.assertAlmostEqual(box_a[1], box_b[1], delta=2)
        self.assertAlmostEqual(box_a[3], box_b[3], delta=2)

    def test_photo_without_product_does_not_crash(self):
        """Пустой кадр (всё — фон) обрабатывается, а не падает."""
        blank = Image.new("RGB", (300, 200), (255, 255, 255))
        out = io.BytesIO()
        blank.save(out, format="PNG")
        im = _open(images.showcase(out.getvalue(), size=256))
        self.assertEqual(im.size, (256, 256))

    def test_webp_for_the_shop_is_made_from_the_master(self):
        """Мастер крупнее витринного webp: make_webp уменьшает, но не растягивает."""
        master = images.showcase(_photo(), size=images.SHOWCASE_PX)
        webp = images.make_webp(master)
        self.assertEqual(_open(webp).size, (images.WEBP_MAX_PX, images.WEBP_MAX_PX))


class ShowcaseTrackTests(SimpleTestCase):
    """Витринный трек не должен ходить к провайдеру — ни запроса, ни токенов."""

    def test_track_goes_around_the_provider(self):
        from unittest import mock

        from productmedia import processing

        with mock.patch.object(processing.providers, "edit_image") as ai:
            out = processing.process(_photo(), track="showcase")

        ai.assert_not_called()
        self.assertEqual(_open(out).size, (2048, 2048))

    def test_ai_tracks_still_call_the_provider(self):
        from unittest import mock

        from productmedia import processing

        with mock.patch.object(processing.providers, "edit_image",
                               return_value=_photo()) as ai:
            processing.process(_photo(), track="catalog", item="Кроссовки")

        ai.assert_called_once()
