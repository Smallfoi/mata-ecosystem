"""«Импорт контента»: фото и описания с сайтов брендов — только после проверки и только в пустое.

Главное: цвет определяется по артикулу цвета из 1С; готовые фото и описания
сотрудников не перетираются; пакеты берутся только из нашего хранилища.
"""
import io
import shutil
import tempfile
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from catalog.models import Product, ProductPhoto
from common.testutils import login_admin
from config import content_import_view as ci

_MEDIA = tempfile.mkdtemp(prefix="mata-content-import-")
URL = "/admin/content-import/"
PREFIX = "https://storage.yandexcloud.net/mata-media/content-import/"


def _png() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (40, 30), "red").save(out, format="PNG")
    return out.getvalue()


MANIFEST = {
    "title": "BMAI тест",
    "items": [
        {"article": "XRMM002", "description": "BMAI GCARBON 4 — тест",
         "missing": ["нет веса"], "source": "https://www.bmai.com/x",
         "photos": {"XRMM002-4": [PREFIX + "t/a.jpg"], "XRMM002-2": [PREFIX + "t/b.jpg"],
                    "XRMM002-9": [PREFIX + "t/c.jpg"]}},
        {"article": "NOPE01", "description": "чужое", "photos": {}},
        # STAW: код цвета в артикуле без дефиса — модель по началу артикула, цвет по названию.
        {"article": "26SADT003", "prefix": True, "description": "STAW футболка",
         "photos": {"26SADT003|Горчичный": [PREFIX + "t/s.jpg"],
                    "26SADT003|Фиолетовый": [PREFIX + "t/v.jpg"]}},
    ],
}


@override_settings(CONTENT_IMPORT_PREFIX=PREFIX, MEDIA_ROOT=_MEDIA)
class ContentImportTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_MEDIA, ignore_errors=True)

    @classmethod
    def setUpTestData(cls):
        # Две позиции цвета -4 (два размера), одна позиция цвета -2 — у неё уже есть фото.
        for pid, art, color in (("p1", "XRMM002-4", "Белый/Красный"),
                                ("p2", "XRMM002-4", "Белый/Красный"),
                                ("p3", "XRMM002-2", "Оранжевый")):
            Product.objects.create(id=pid, name="Кроссовки женские BMAI GCARBON-4",
                                   brand="BMAI", article=art, price=100, colors=[color],
                                   model_key_override="XRMM002")
        Product.objects.filter(pk="p3").update(description="уже написано сотрудником")
        Product.objects.create(id="s1", name="Футболка женская STAW", brand="STAW",
                               article="26SADT0031850", price=100, colors=["Горчичный"])
        ProductPhoto.objects.create(model_key="XRMM002", color="Оранжевый",
                                    image="uploads/photos/old.webp")

    def setUp(self):
        get_user_model().objects.create_superuser("owner_ci", "ci@t.dev", "OwnerPass!2026")
        login_admin(self.client, "owner_ci", "OwnerPass!2026")
        patcher = mock.patch.object(ci, "load_manifest", return_value=MANIFEST)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_page_shows_plan(self):
        r = self.client.get(URL, {"batch": "bmai-test"})
        self.assertEqual(r.status_code, 200)
        rows = r.context["rows"]
        first = rows[0]
        by_code = {c["code"]: c for c in first["colors"]}
        self.assertEqual(by_code["XRMM002-4"]["state"], "fill")
        self.assertEqual(by_code["XRMM002-4"]["color"], "Белый/Красный")
        self.assertEqual(by_code["XRMM002-2"]["state"], "has")     # фото уже есть
        self.assertEqual(by_code["XRMM002-9"]["state"], "none")    # такого цвета нет
        self.assertEqual(first["desc_state"], "fill")
        self.assertEqual(rows[1]["models"], [])                    # NOPE01 у нас нет
        self.assertEqual(r.context["not_found"], 1)

    def test_apply_fills_only_empty(self):
        with mock.patch.object(ci, "_fetch", return_value=_png()):
            j = self.client.post(URL, {"batch": "bmai-test", "item": "0"}).json()
        self.assertEqual(j["photos"], 1, j)              # только цвет -4
        self.assertEqual(j["described"], 2)              # p1, p2; p3 уже с описанием
        self.assertEqual(ProductPhoto.objects.filter(model_key="XRMM002",
                                                     color="Белый/Красный").count(), 1)
        self.assertEqual(ProductPhoto.objects.filter(color="Оранжевый").count(), 1)
        p1 = Product.objects.get(pk="p1")
        self.assertEqual(p1.description, "BMAI GCARBON 4 — тест")
        self.assertTrue(p1.is_overridden("description"))  # 1С не сотрёт
        self.assertEqual(Product.objects.get(pk="p3").description, "уже написано сотрудником")

    def test_staw_prefix_and_color_name(self):
        r = self.client.get(URL, {"batch": "bmai-test"})
        staw = r.context["rows"][2]
        states = {c["code"]: c["state"] for c in staw["colors"]}
        self.assertEqual(states, {"26SADT003|Горчичный": "fill", "26SADT003|Фиолетовый": "none"})
        with mock.patch.object(ci, "_fetch", return_value=_png()):
            j = self.client.post(URL, {"batch": "bmai-test", "item": "2"}).json()
        self.assertEqual((j["photos"], j["described"]), (1, 1))
        self.assertEqual(Product.objects.get(pk="s1").description, "STAW футболка")

    def test_apply_twice_is_noop(self):
        with mock.patch.object(ci, "_fetch", return_value=_png()):
            self.client.post(URL, {"batch": "bmai-test", "item": "0"})
            j = self.client.post(URL, {"batch": "bmai-test", "item": "0"}).json()
        self.assertEqual((j["photos"], j["described"]), (0, 0))

    def test_fetch_only_from_our_storage(self):
        for bad in ("https://evil.example/x.jpg", PREFIX + "../secret", PREFIX.replace("https://", "https://u@")):
            with self.assertRaises(ValueError):
                ci._fetch(bad, 10)

    def test_bad_batch_name(self):
        mock.patch.stopall()
        with self.assertRaises(ValueError):
            ci.load_manifest("../etc")

    def test_viewer_cannot_apply(self):
        from staff.models import StaffProfile
        staff = get_user_model().objects.create_user("clerk_ci", "c@t.dev", "ClerkPass!2026",
                                                     is_staff=True)
        StaffProfile.objects.create(user=staff, full_name="Кладовщик")
        c = self.client_class()
        login_admin(c, "clerk_ci", "ClerkPass!2026")
        self.assertNotEqual(c.get(URL).status_code, 200)
        self.assertNotEqual(c.post(URL, {"batch": "bmai-test", "item": "0"}).status_code, 200)
        self.assertFalse(ProductPhoto.objects.filter(color="Белый/Красный").exists())

    def test_menu_item_present(self):
        html = self.client.get(reverse("admin:index")).content.decode()
        self.assertIn(URL, html)
