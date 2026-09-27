"""Загрузки без метаданных: EXIF/GPS/XMP снимаются, ориентация сохраняется (аудит D07).

GPS в фото с телефона — это координаты человека (152-ФЗ). После загрузки в хранилище
не должно остаться ни координат, ни прочих сведений из EXIF/XMP/комментариев, а
снимок должен смотреть туда же, куда смотрел на телефоне.
"""
import io
import os
import tempfile
from unittest import mock

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from PIL import ExifTags, Image, ImageSequence

from common.testutils import ApiTestCase
from common.uploads import clean_image_bytes, prepare_image

SECRET = b"MATA-SECRET-META"          # метка в описании/XMP/комментарии: не должна дожить
RED, BLUE = (220, 20, 20), (20, 20, 220)


def _exif(orientation=6):
    """EXIF как у телефона: ориентация, координаты (Якутск) и описание с меткой."""
    ex = Image.Exif()
    ex[ExifTags.Base.Orientation] = orientation
    ex[ExifTags.Base.ImageDescription] = SECRET.decode()
    ex[ExifTags.Base.Make] = "PhoneMaker"
    gps = ex.get_ifd(ExifTags.IFD.GPSInfo)
    gps[ExifTags.GPS.GPSLatitudeRef] = "N"
    gps[ExifTags.GPS.GPSLatitude] = (62.0, 1.0, 30.0)
    gps[ExifTags.GPS.GPSLongitudeRef] = "E"
    gps[ExifTags.GPS.GPSLongitude] = (129.0, 43.0, 10.0)
    return ex


def _split(size=(40, 20), mode="RGB"):
    """Левая половина красная, правая синяя — по ним видно, как лёг снимок."""
    im = Image.new(mode, size, RED)
    im.paste(BLUE, (size[0] // 2, 0, size[0], size[1]))
    return im


def _xmp():
    return (b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/'
            b'1999/02/22-rdf-syntax-ns#"><rdf:Description exif:GPSLatitude="62,1.5N" '
            b'dc:description="' + SECRET + b'"/></rdf:RDF></x:xmpmeta>')


def _phone_jpeg(orientation=6):
    buf = io.BytesIO()
    _split().save(buf, "JPEG", quality=95, exif=_exif(orientation), xmp=_xmp(),
                  comment=SECRET)
    data = buf.getvalue()
    # Проверка самой подставы: в исходнике координаты действительно есть.
    assert Image.open(io.BytesIO(data)).getexif().get_ifd(ExifTags.IFD.GPSInfo)
    return data


def _file(data, name="x.bin"):
    return SimpleUploadedFile(name, data, content_type="application/octet-stream")


def _close(a, b, tol=40):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


class CleanAssertions:
    def assertClean(self, data):
        """Ни EXIF, ни XMP, ни комментариев, ни нашей метки в байтах файла."""
        for marker in (SECRET, b"PhoneMaker", b"xmpmeta"):
            self.assertFalse(marker in data, "в файле осталось: %r" % marker)
        im = Image.open(io.BytesIO(data))
        self.assertEqual(dict(im.getexif()), {}, "EXIF должен быть снят целиком")
        for key in ("exif", "xmp", "XML:com.adobe.xmp", "comment", "Description"):
            self.assertNotIn(key, im.info)

    def assertUpright(self, data):
        """Ориентация 6 (повернуть на 90° по часовой): 40×20 → 20×40, красное сверху."""
        im = Image.open(io.BytesIO(data)).convert("RGB")
        self.assertEqual(im.size, (20, 40))
        self.assertTrue(_close(im.getpixel((10, 5)), RED), im.getpixel((10, 5)))
        self.assertTrue(_close(im.getpixel((10, 35)), BLUE), im.getpixel((10, 35)))


class CleanImageTests(CleanAssertions, SimpleTestCase):
    def test_jpeg_gps_removed_orientation_applied(self):
        out = clean_image_bytes(_file(_phone_jpeg()), "jpg")
        self.assertEqual(Image.open(io.BytesIO(out)).format, "JPEG")
        self.assertClean(out)
        self.assertUpright(out)

    def test_every_orientation_matches_what_phone_shows(self):
        from PIL import ImageOps
        for o in range(1, 9):
            with self.subTest(orientation=o):
                src = _phone_jpeg(o)
                want = ImageOps.exif_transpose(Image.open(io.BytesIO(src))).convert("RGB")
                got = Image.open(io.BytesIO(clean_image_bytes(_file(src), "jpg"))).convert("RGB")
                self.assertEqual(got.size, want.size)
                self.assertTrue(_close(got.getpixel((2, 2)), want.getpixel((2, 2))))
                self.assertTrue(_close(got.getpixel((got.width - 3, got.height - 3)),
                                       want.getpixel((want.width - 3, want.height - 3))))

    def test_png_exif_and_text_removed_alpha_kept(self):
        from PIL.PngImagePlugin import PngInfo
        info = PngInfo()
        info.add_text("Comment", SECRET.decode())
        info.add_itxt("XML:com.adobe.xmp", _xmp().decode())
        buf = io.BytesIO()
        _split(mode="RGBA").save(buf, "PNG", exif=_exif(), pnginfo=info)
        out = clean_image_bytes(_file(buf.getvalue()), "png")
        self.assertClean(out)
        self.assertUpright(out)
        im = Image.open(io.BytesIO(out))
        self.assertEqual(im.format, "PNG")
        self.assertEqual(im.mode, "RGBA")

    def test_png_palette_transparency_kept(self):
        im = Image.new("P", (8, 8), 1)
        im.putpalette([0, 0, 0, 255, 0, 0] + [0] * 762)
        im.paste(0, (0, 0, 4, 8))
        buf = io.BytesIO()
        im.save(buf, "PNG", transparency=0)
        out = Image.open(io.BytesIO(clean_image_bytes(_file(buf.getvalue()), "png")))
        rgba = out.convert("RGBA")
        self.assertEqual(rgba.getpixel((1, 1))[3], 0)
        self.assertEqual(rgba.getpixel((6, 1)), (255, 0, 0, 255))

    def test_webp_exif_xmp_removed(self):
        buf = io.BytesIO()
        _split().save(buf, "WEBP", quality=95, exif=_exif(), xmp=_xmp())
        out = clean_image_bytes(_file(buf.getvalue()), "webp")
        self.assertEqual(Image.open(io.BytesIO(out)).format, "WEBP")
        self.assertClean(out)
        self.assertUpright(out)

    def test_icc_profile_kept(self):
        """ICC — это цвет снимка, а не сведения о человеке: оставляем."""
        from PIL import ImageCms
        icc = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
        buf = io.BytesIO()
        _split().save(buf, "JPEG", exif=_exif(), icc_profile=icc)
        out = clean_image_bytes(_file(buf.getvalue()), "jpg")
        self.assertEqual(Image.open(io.BytesIO(out)).info.get("icc_profile"), icc)
        self.assertClean(out)

    def test_animated_gif_keeps_frames_timing_and_loop(self):
        """Решение: анимацию GIF сохраняем (аватар-гифка должна остаться живой)."""
        frames = [Image.new("RGB", (16, 16), c) for c in (RED, BLUE, (20, 200, 20))]
        buf = io.BytesIO()
        frames[0].save(buf, "GIF", save_all=True, append_images=frames[1:],
                       duration=[100, 200, 300], loop=0, comment=SECRET)
        self.assertIn(SECRET, buf.getvalue())
        out = clean_image_bytes(_file(buf.getvalue()), "gif")
        self.assertNotIn(SECRET, out)
        im = Image.open(io.BytesIO(out))
        self.assertEqual(im.format, "GIF")
        self.assertEqual(im.n_frames, 3)
        self.assertEqual(im.info.get("loop"), 0)
        got = []
        for fr in ImageSequence.Iterator(im):
            got.append((fr.info.get("duration"), fr.convert("RGB").getpixel((8, 8))))
        self.assertEqual([d for d, _ in got], [100, 200, 300])
        for (_, px), want in zip(got, (RED, BLUE, (20, 200, 20))):
            self.assertTrue(_close(px, want), px)

    def test_animated_webp_keeps_frames_and_drops_exif(self):
        frames = [Image.new("RGB", (16, 16), c) for c in (RED, BLUE)]
        buf = io.BytesIO()
        frames[0].save(buf, "WEBP", save_all=True, append_images=frames[1:],
                       duration=[120, 240], loop=2, exif=_exif(), xmp=_xmp())
        self.assertIn(SECRET, buf.getvalue())
        out = clean_image_bytes(_file(buf.getvalue()), "webp")
        self.assertNotIn(SECRET, out)
        self.assertNotIn(b"xmpmeta", out)
        im = Image.open(io.BytesIO(out))
        self.assertEqual(im.n_frames, 2)
        self.assertEqual(im.info.get("loop"), 2)
        self.assertEqual(dict(im.getexif()), {})

    def test_single_frame_gif_comment_removed(self):
        buf = io.BytesIO()
        _split().convert("P").save(buf, "GIF", comment=SECRET)
        out = clean_image_bytes(_file(buf.getvalue()), "gif")
        self.assertNotIn(SECRET, out)
        self.assertEqual(Image.open(io.BytesIO(out)).format, "GIF")

    def test_archival_png_and_webp_are_lossless(self):
        noisy = Image.effect_noise((32, 32), 80).convert("RGB")
        for fmt, ext in (("PNG", "png"), ("WEBP", "webp")):
            with self.subTest(fmt=fmt):
                buf = io.BytesIO()
                noisy.save(buf, fmt, lossless=True, exif=_exif(1))
                out = clean_image_bytes(_file(buf.getvalue()), ext, archival=True)
                self.assertEqual(list(Image.open(io.BytesIO(out)).convert("RGB").getdata()),
                                 list(noisy.getdata()))
                self.assertNotIn(SECRET, out)

    def test_archival_jpeg_full_chroma(self):
        from PIL import JpegImagePlugin
        out = clean_image_bytes(_file(_phone_jpeg()), "jpg", archival=True)
        self.assertEqual(JpegImagePlugin.get_sampling(Image.open(io.BytesIO(out))), 0)
        self.assertClean(out)

    def test_phone_mpo_accepted_as_jpeg(self):
        """MPO (JPEG с доп. кадром) пишут камеры многих телефонов — это обычное фото."""
        buf = io.BytesIO()
        _split().save(buf, "MPO", save_all=True, append_images=[_split()], exif=_exif())
        ext, content, err = prepare_image(_file(buf.getvalue()))
        self.assertEqual((ext, err), ("jpg", None))
        data = content.read()
        im = Image.open(io.BytesIO(data))
        self.assertEqual(im.format, "JPEG")
        self.assertClean(data)
        self.assertUpright(data)

    def test_prepare_image_rejects_garbage(self):
        ext, content, err = prepare_image(_file(b"\xff\xd8\xffgarbage"))
        self.assertIsNone(content)
        self.assertTrue(err)


def _media_bytes(url):
    rel = url.split(settings.MEDIA_URL, 1)[1]
    with open(os.path.join(settings.MEDIA_ROOT, rel), "rb") as fh:
        return fh.read()


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class ApiUploadsTests(CleanAssertions, ApiTestCase):
    """Каждая ручка загрузки кладёт в хранилище уже очищенный файл."""
    phone = "+79990009081"

    def _post(self, path, data):
        return self.client.post(path, {"image": _file(data, "IMG_0001.jpg")},
                                HTTP_AUTHORIZATION=f"Bearer {self.token}")

    def test_avatar(self):
        r = self._post("/v1/profile/avatar", _phone_jpeg())
        self.assertEqual(r.status_code, 200)
        data = _media_bytes(r.json()["avatarPath"])
        self.assertClean(data)
        self.assertUpright(data)

    def test_review_photo(self):
        r = self._post("/v1/reviews/photo", _phone_jpeg())
        self.assertEqual(r.status_code, 200)
        data = _media_bytes(r.json()["url"])
        self.assertClean(data)
        self.assertUpright(data)

    def test_club_logo_and_cover(self):
        from clubs.models import Club
        Club.objects.create(id="exif_c", name="Клуб", owner_id=self.uid)
        r = self._post("/v1/clubs/exif_c/logo", _phone_jpeg())
        self.assertEqual(r.status_code, 200)
        r = self._post("/v1/clubs/exif_c/cover", _phone_jpeg())
        self.assertEqual(r.status_code, 200)
        club = Club.objects.get(id="exif_c")
        for url in (club.logo, club.cover):
            data = _media_bytes(url)
            self.assertClean(data)
            self.assertUpright(data)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class PhotoPipelineUploadTests(CleanAssertions, TestCase):
    """Исходники фотопайплайна и витринные снимки — тоже без EXIF/GPS."""

    @classmethod
    def setUpTestData(cls):
        from catalog.models import Product
        Product.objects.create(pk="ex1", name="Худи", category_id="c", price=2000,
                               article="EX-1", colors=["Чёрный"], model_key="EX")

    def setUp(self):
        from django.contrib.auth import get_user_model
        from common.testutils import login_admin
        get_user_model().objects.create_superuser("owner_ex", "ex@t.dev", "OwnerPass!2026")
        login_admin(self.client, "owner_ex", "OwnerPass!2026")

    def _upload(self, data, attach_as):
        from django.urls import reverse
        url = reverse("photo_pipeline")
        batch = self.client.post(url, {"action": "create", "track": "catalog"}).json()["batch"]
        photo = SimpleUploadedFile("IMG.jpg", data, content_type="image/jpeg")
        return self.client.post(url, {"action": "upload", "batch": batch, "article": "EX-1",
                                      "attach_as": attach_as, "photo": photo}).json()

    @mock.patch("productmedia.tasks.process_batch.delay")
    def test_source_and_detail_cleaned(self, _delay):
        from productmedia.models import PhotoDetail, PhotoJob
        res = self._upload(_phone_jpeg(), "main")
        self.assertTrue(res["ok"], res)
        with PhotoJob.objects.get(pk=res["job"]).source.open("rb") as fh:
            src = fh.read()
        self.assertClean(src)
        self.assertUpright(src)
        res = self._upload(_phone_jpeg(), "detail")
        self.assertTrue(res["ok"], res)
        with PhotoDetail.objects.get(pk=res["detail"]).image.open("rb") as fh:
            det = fh.read()
        self.assertClean(det)
        self.assertUpright(det)

    def test_showcase_webp_has_no_exif_and_is_upright(self):
        """catalog.photos перекодирует в webp — проверяем, что EXIF туда не протекает."""
        from catalog import photos
        row = photos.store_photo("EX", "", _phone_jpeg(), "exif-test")
        for field in (row.image, row.thumb):
            with field.open("rb") as fh:
                data = fh.read()
            self.assertClean(data)
            self.assertUpright(data)


class SiteImageTests(CleanAssertions, SimpleTestCase):
    """Фото блоков сайта/баннеров в Конструкторе (_webify_image) — тоже без метаданных."""

    def test_webify_drops_metadata_and_keeps_orientation(self):
        from config.admin_views import _webify_image
        out = _webify_image(_file(_phone_jpeg(), "IMG.jpg")).read()
        self.assertClean(out)
        self.assertUpright(out)
