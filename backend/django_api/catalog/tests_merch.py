"""Конструктор витрины (мерчендайзинг): раздельный порядок по площадкам +
правка центрального товара. Эндпоинты staff-only."""
import json
import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from catalog.models import Product
from common.testutils import login_admin


class MerchConsoleTests(TestCase):
    def setUp(self):
        User.objects.create_superuser("merch_admin", "a@t.dev", "pass12345")
        login_admin(self.client, "merch_admin", "pass12345")
        Product.objects.create(id="m1", name="M1", category_id="c", price=100,
                               sort_site=0, sort_app=0)
        Product.objects.create(id="m2", name="M2", category_id="c", price=200,
                               sort_site=1, sort_app=1)

    def _post(self, url, body):
        return self.client.post(url, data=json.dumps(body),
                                content_type="application/json")

    def test_reorder_updates_only_that_platform(self):
        r = self._post("/admin/merch/reorder", {"platform": "site", "order": ["m2", "m1"]})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Product.objects.get(id="m2").sort_site, 0)
        self.assertEqual(Product.objects.get(id="m1").sort_site, 1)
        # Порядок приложения не затронут.
        self.assertEqual(Product.objects.get(id="m2").sort_app, 1)
        self.assertEqual(Product.objects.get(id="m1").sort_app, 0)

    def test_reorder_bad_platform(self):
        self.assertEqual(self._post("/admin/merch/reorder", {"platform": "x", "order": []}).status_code, 400)

    def test_product_edit_is_central(self):
        r = self._post("/admin/merch/product/m1",
                       {"price": 999, "oldPrice": 1200, "isPublished": False,
                        "inStock": False, "sizes": ["M", "L"], "description": "новое"})
        self.assertEqual(r.status_code, 200)
        p = Product.objects.get(id="m1")
        self.assertEqual(p.price, 999)
        self.assertEqual(p.old_price, 1200)
        self.assertFalse(p.is_published)
        self.assertFalse(p.in_stock)
        self.assertEqual(p.sizes, ["M", "L"])
        self.assertEqual(p.description, "новое")

    def test_product_empty_old_price_clears(self):
        Product.objects.filter(id="m1").update(old_price=1200)
        self._post("/admin/merch/product/m1", {"oldPrice": ""})
        self.assertIsNone(Product.objects.get(id="m1").old_price)

    def test_product_404(self):
        self.assertEqual(self._post("/admin/merch/product/nope", {"price": 1}).status_code, 404)

    def test_products_list_ordered_by_platform(self):
        Product.objects.filter(id="m1").update(sort_app=5)
        Product.objects.filter(id="m2").update(sort_app=1)
        ids = [p["id"] for p in self.client.get("/admin/merch/products?platform=app").json()["products"]]
        self.assertEqual(ids[:2], ["m2", "m1"])

    def test_console_page_renders(self):
        r = self.client.get("/admin/merch/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Конструктор")
        self.assertContains(r, "Назад в админку")

    def test_site_content_edit_and_public_read(self):
        self.assertEqual(self.client.get("/v1/site/content").json(), {})
        r = self._post("/admin/merch/site-content", {"key": "hero.copy", "value": "Новый текст"})
        self.assertEqual(r.status_code, 200)
        got = self.client.get("/v1/site/content").json()
        self.assertEqual(got["hero.copy"]["value"], "Новый текст")

    def test_site_content_requires_key(self):
        self.assertEqual(self._post("/admin/merch/site-content", {"value": "x"}).status_code, 400)

    def test_site_content_requires_staff(self):
        self.client.logout()
        r = self._post("/admin/merch/site-content", {"key": "a", "value": "b"})
        self.assertIn(r.status_code, (302, 403))

    def test_site_image_upload(self):
        import tempfile
        from io import BytesIO

        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.test import override_settings
        from PIL import Image

        buf = BytesIO()
        Image.new("RGB", (16, 16), (1, 2, 3)).save(buf, "PNG")
        img = SimpleUploadedFile("s.png", buf.getvalue(), content_type="image/png")
        with override_settings(MEDIA_ROOT=tempfile.mkdtemp()):
            r = self.client.post("/admin/merch/site-image", {"key": "hero.image", "image": img})
            self.assertEqual(r.status_code, 200)
            got = self.client.get("/v1/site/content").json()
            self.assertTrue(got["hero.image"]["imageUrl"])

    def test_site_video_upload(self):
        import tempfile

        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.test import override_settings

        vid = SimpleUploadedFile("clip.mp4", b"\x00\x00\x00\x18ftypmp42fake",
                                 content_type="video/mp4")
        with override_settings(MEDIA_ROOT=tempfile.mkdtemp()):
            r = self.client.post("/admin/merch/site-video", {"video": vid})
            self.assertEqual(r.status_code, 200)
            self.assertTrue(r.json()["url"].endswith(".mp4"))

    def test_site_video_rejects_non_video(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        bad = SimpleUploadedFile("x.txt", b"hello", content_type="text/plain")
        r = self.client.post("/admin/merch/site-video", {"video": bad})
        self.assertEqual(r.status_code, 400)

    def test_site_video_requires_staff(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        self.client.logout()
        vid = SimpleUploadedFile("clip.mp4", b"x", content_type="video/mp4")
        r = self.client.post("/admin/merch/site-video", {"video": vid})
        self.assertIn(r.status_code, (302, 403))

    def test_requires_staff(self):
        self.client.logout()
        r = self._post("/admin/merch/reorder", {"platform": "site", "order": []})
        self.assertIn(r.status_code, (302, 403))


class MerchBannerTests(TestCase):
    """Баннеры (промо): CRUD в конструкторе + раздельный порядок по площадкам."""

    def setUp(self):
        User.objects.create_superuser("bnr_admin", "b@t.dev", "pass12345")
        login_admin(self.client, "bnr_admin", "pass12345")

    def _img(self):
        from io import BytesIO

        from django.core.files.uploadedfile import SimpleUploadedFile
        from PIL import Image
        buf = BytesIO()
        Image.new("RGB", (16, 16), (9, 9, 9)).save(buf, "PNG")
        return SimpleUploadedFile("b.png", buf.getvalue(), content_type="image/png")

    def test_create_then_list(self):
        r = self.client.post("/admin/merch/banner-create", {"title": "Промо-1", "subtitle": "sub", "action": "Купить"})
        self.assertEqual(r.status_code, 200)
        bid = r.json()["banner"]["id"]
        data = self.client.get("/admin/merch/banners?platform=site").json()["banners"]
        self.assertEqual([b["id"] for b in data], [bid])
        self.assertEqual(data[0]["title"], "Промо-1")

    def test_create_requires_title(self):
        self.assertEqual(self.client.post("/admin/merch/banner-create", {"subtitle": "x"}).status_code, 400)

    def test_update_fields(self):
        bid = self.client.post("/admin/merch/banner-create", {"title": "A"}).json()["banner"]["id"]
        r = self.client.post("/admin/merch/banner/%d" % bid, {"title": "B", "isPublished": "0"})
        self.assertEqual(r.status_code, 200)
        from catalog.models import Banner
        b = Banner.objects.get(id=bid)
        self.assertEqual(b.title, "B")
        self.assertFalse(b.is_published)

    def test_banner_fit_focal_defaults_and_update(self):
        r = self.client.post("/admin/merch/banner-create", {"title": "A"}).json()["banner"]
        self.assertEqual(r["imageFit"], "cover")
        self.assertEqual(r["imageFocal"], "50% 50%")
        bid = r["id"]
        upd = self.client.post("/admin/merch/banner/%d" % bid,
                               {"imageFit": "contain", "imageFocal": "50% 0%"}).json()["banner"]
        self.assertEqual(upd["imageFit"], "contain")
        self.assertEqual(upd["imageFocal"], "50% 0%")
        # публичный /v1/banners тоже отдаёт fit/focal
        from catalog.models import Banner
        self.assertEqual(Banner.objects.get(id=bid).to_json()["imageFit"], "contain")

    def test_update_image(self):
        import tempfile

        from django.test import override_settings
        bid = self.client.post("/admin/merch/banner-create", {"title": "A"}).json()["banner"]["id"]
        with override_settings(MEDIA_ROOT=tempfile.mkdtemp()):
            r = self.client.post("/admin/merch/banner/%d" % bid, {"image": self._img()})
            self.assertEqual(r.status_code, 200)
            self.assertTrue(r.json()["banner"]["imageUrl"])

    def test_delete(self):
        bid = self.client.post("/admin/merch/banner-create", {"title": "A"}).json()["banner"]["id"]
        self.assertEqual(self.client.post("/admin/merch/banner/%d/delete" % bid).status_code, 200)
        from catalog.models import Banner
        self.assertFalse(Banner.objects.filter(id=bid).exists())

    def test_delete_404(self):
        self.assertEqual(self.client.post("/admin/merch/banner/999999/delete").status_code, 404)

    def test_reorder_per_platform(self):
        a = self.client.post("/admin/merch/banner-create", {"title": "A"}).json()["banner"]["id"]
        b = self.client.post("/admin/merch/banner-create", {"title": "B"}).json()["banner"]["id"]
        r = self.client.post("/admin/merch/banner-reorder",
                             data=json.dumps({"platform": "app", "order": [b, a]}),
                             content_type="application/json")
        self.assertEqual(r.status_code, 200)
        from catalog.models import Banner
        self.assertEqual(Banner.objects.get(id=b).sort_app, 0)
        self.assertEqual(Banner.objects.get(id=a).sort_app, 1)
        # порядок сайта не затронут
        self.assertEqual(Banner.objects.get(id=a).sort_site, 0)

    def test_reorder_bad_platform(self):
        r = self.client.post("/admin/merch/banner-reorder",
                             data=json.dumps({"platform": "x", "order": []}),
                             content_type="application/json")
        self.assertEqual(r.status_code, 400)

    def test_requires_staff(self):
        self.client.logout()
        self.assertIn(self.client.get("/admin/merch/banners").status_code, (302, 403))
        self.assertIn(self.client.post("/admin/merch/banner-create", {"title": "x"}).status_code, (302, 403))


class MerchOverride1CTests(TestCase):
    """Гибрид «1С + Конструктор» (D-62): правка владельца держится, возврат — снимает её."""

    def setUp(self):
        User.objects.create_superuser("merch_1c", "b@t.dev", "pass12345")
        login_admin(self.client, "merch_1c", "pass12345")
        self.p = Product.objects.create(
            id="k1", name="Кроссовки", category_id="c", price=11990,
            external_id="1c-guid-1", article="ART-1",
            description="из 1С", sizes=["41", "42"],
            from_1c={"price": 11990, "description": "из 1С", "sizes": ["41", "42"]},
        )

    def _post(self, body, pid="k1"):
        return self.client.post(f"/admin/merch/product/{pid}", data=json.dumps(body),
                                content_type="application/json")

    def test_edit_marks_field_as_owners(self):
        self._post({"price": 10990, "description": "из 1С", "sizes": ["41", "42"]})
        p = Product.objects.get(id="k1")
        self.assertEqual(p.price, 10990)
        self.assertEqual(p.overrides, ["price"])          # тронута только цена
        self.assertEqual(p.from_1c["price"], 11990)       # значение 1С сохранено

    def test_resend_unchanged_form_does_not_override(self):
        """Конструктор шлёт все поля разом — нетронутые не должны становиться «моими»."""
        self._post({"price": 11990, "description": "из 1С", "sizes": ["41", "42"]})
        self.assertEqual(Product.objects.get(id="k1").overrides, [])

    def test_return_to_1c_value_clears_override(self):
        self._post({"price": 10990})
        self.assertEqual(Product.objects.get(id="k1").overrides, ["price"])
        self._post({"price": 11990})                      # «вернуть как в 1С» + сохранить
        self.assertEqual(Product.objects.get(id="k1").overrides, [])

    def test_console_json_shows_1c_values(self):
        self._post({"price": 10990})
        r = self.client.get("/admin/merch/products?platform=site")
        item = [x for x in r.json()["products"] if x["id"] == "k1"][0]
        self.assertTrue(item["onec"]["linked"])
        self.assertEqual(item["onec"]["article"], "ART-1")
        self.assertEqual(item["onec"]["overrides"], ["price"])
        self.assertEqual(item["onec"]["from1c"]["price"], 11990)

    def test_plain_product_gets_no_overrides(self):
        Product.objects.create(id="k2", name="Свой", category_id="c", price=100)
        self.client.post("/admin/merch/product/k2", data=json.dumps({"price": 200}),
                         content_type="application/json")
        self.assertEqual(Product.objects.get(id="k2").overrides, [])

# Свой временный каталог: без него тест пишет в боевую папку медиа, которой на CI
# просто нет (Permission denied: /srv/media). Грабли записаны в PITFALLS.
_VIDEO_MEDIA = tempfile.mkdtemp(prefix="mata-merch-video-")


@override_settings(MEDIA_ROOT=_VIDEO_MEDIA)
class HeavyVideoTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(_VIDEO_MEDIA, ignore_errors=True)
        super().tearDownClass()

    """Тяжёлое видео на фон не пускаем молча (владелец: «жёстко тормозит у всех»).

    Сжатие при загрузке работало только с локальным диском: на проде хранилище
    облачное, и на сайт уходил стомегабайтный исходник прямо с камеры. Теперь при
    неудачном сжатии тяжёлый файл получает честный отказ, а не тихо едет на витрину.
    """

    def setUp(self):
        get_user_model().objects.create_superuser("owner_vid", "v@t.dev", "OwnerPass!2026")
        login_admin(self.client, "owner_vid", "OwnerPass!2026")

    def _send(self, size_mb):
        data = bytes(size_mb * 1024 * 1024)
        return self.client.post("/admin/merch/site-video", {
            "video": SimpleUploadedFile("158A9990.MP4", data, content_type="video/mp4"),
        })

    def test_heavy_unwebifiable_video_is_refused(self):
        r = self._send(21)
        self.assertEqual(r.status_code, 400)
        self.assertIn("тормозить", r.json()["detail"])

    def test_small_video_still_passes(self):
        r = self._send(1)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()["url"])

    def test_broken_video_does_not_break_upload(self):
        """Мусор под видом mp4: постер не снимется, но 500 быть не должно."""
        from config.admin_views import _video_poster

        self.assertIsNone(_video_poster("uploads/site-video/нет-такого.mp4"))
