"""«Фото товаров»: галерея на модель и цвет (D-91, D-99).

Фото ведём мы сами, а снимки зависят от ЦВЕТА, не от размера: в 1С каждый размер
своя карточка, но чёрные кроссовки выглядят одинаково в 41-м и 42-м. Здесь
проверяем главное: плитка собирается по паре «модель + цвет», шесть снимков —
предел, чужой файл под видом картинки не проходит, а без права на вкладку
страница не открывается.
"""
import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from catalog.models import Product, ProductPhoto
from common.testutils import login_admin
from staff.models import StaffAudit, StaffProfile

PAGE = "/admin/photos/"

# Наименьший настоящий PNG: Django проверяет картинку через Pillow.
PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06"
       b"\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05"
       b"\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")


# Свой временный каталог для загрузок: без него тест писал бы в боевую папку
# медиа. На CI её просто нет (Permission denied: /srv/media) — и это правильно:
# тест не должен зависеть от того, куда настроено хранилище на машине.
_MEDIA = tempfile.mkdtemp(prefix="mata-photos-")


def make(pid, name, **extra):
    data = dict(id=pid, name=name, category_id="c", price=100)
    data.update(extra)
    product = Product.objects.create(**data)
    product.rebuild_display_name()
    product.save(update_fields=["display_name", "model_key"])
    return product


@override_settings(MEDIA_ROOT=_MEDIA)
class ProductPhotosTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(_MEDIA, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        get_user_model().objects.create_superuser("owner_ph", "p@t.dev", "OwnerPass!2026")
        login_admin(self.client, "owner_ph", "OwnerPass!2026")
        # Одна модель обуви: два цвета, по два размера.
        for size in ("41", "42"):
            make(f"p_black_{size}", f"BMAI EXPEDITION ЧЕРНЫЙ {size}р.",
                 sizes=[size], colors=["ЧЕРНЫЙ"])
            make(f"p_mint_{size}", f"BMAI EXPEDITION МЯТНЫЙ {size}р.",
                 sizes=[size], colors=["МЯТНЫЙ"])
        self.key = Product.objects.get(pk="p_black_41").shop_model_key

    def _upload(self, color="ЧЕРНЫЙ", key=None, data=PNG, name="photo.png",
                ctype="image/png"):
        return self.client.post(PAGE, {
            "key": key if key is not None else self.key,
            "color": color,
            "photo": SimpleUploadedFile(name, data, content_type=ctype),
        })

    # ── Раскладка страницы ──────────────────────────────────────────────────
    def test_tile_is_a_model_and_a_colour_not_a_size(self):
        """Четыре позиции — две плитки: снимки от размера не зависят."""
        items = self.client.get(PAGE).context["items"]
        self.assertEqual(len(items), 2)
        self.assertEqual(sorted(i["color"] for i in items), ["МЯТНЫЙ", "ЧЕРНЫЙ"])
        self.assertEqual({i["key"] for i in items}, {self.key})

    def test_colour_with_photos_leaves_the_empty_tab(self):
        self._upload("ЧЕРНЫЙ")
        items = self.client.get(PAGE).context["items"]
        self.assertEqual([i["color"] for i in items], ["МЯТНЫЙ"])
        self.assertEqual(self.client.get(PAGE).context["left"], 1)

    def test_all_tab_keeps_both(self):
        self._upload("ЧЕРНЫЙ")
        items = self.client.get(PAGE, {"only": "all"}).context["items"]
        self.assertEqual(len(items), 2)

    def test_product_without_colour_gets_one_tile(self):
        make("p_solo", "ФУТБОЛКА MATA", article="FRTW001")
        items = self.client.get(PAGE, {"q": "ФУТБОЛКА"}).context["items"]
        self.assertEqual([i["color"] for i in items], [""])

    def test_search_finds_by_article(self):
        make("p_art", "ШОРТЫ MATA", article="FRSM007")
        items = self.client.get(PAGE, {"q": "FRSM007"}).context["items"]
        self.assertEqual(len(items), 1)

    # ── Заливка ─────────────────────────────────────────────────────────────
    def test_upload_stores_photo_for_the_whole_colour(self):
        r = self._upload("ЧЕРНЫЙ")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body["ok"], body)
        self.assertTrue(body["url"] and body["thumb"])

        row = ProductPhoto.objects.get(pk=body["id"])
        self.assertEqual(row.model_key, self.key)
        self.assertEqual(row.color, "ЧЕРНЫЙ")
        self.assertEqual(row.order, 0)

    def test_webp_and_thumb_are_made(self):
        """Снимок с фотоаппарата в витрину не отдаём — только лёгкий webp."""
        body = self._upload().json()
        self.assertTrue(body["url"].endswith(".webp"), body["url"])
        self.assertTrue(body["thumb"].endswith(".webp"), body["thumb"])
        self.assertNotEqual(body["url"], body["thumb"])

    def test_photos_queue_up_in_order(self):
        for _ in range(3):
            self._upload("ЧЕРНЫЙ")
        orders = list(ProductPhoto.objects.filter(color="ЧЕРНЫЙ")
                      .values_list("order", flat=True))
        self.assertEqual(orders, [0, 1, 2])

    def test_seventh_photo_is_refused(self):
        """Шесть — решение владельца; седьмой не должен теряться молча."""
        for _ in range(ProductPhoto.MAX_PER_COLOR):
            self.assertTrue(self._upload().json()["ok"])
        r = self._upload()
        self.assertEqual(r.status_code, 400)
        self.assertIn("удалите", r.json()["error"])
        self.assertEqual(ProductPhoto.objects.count(), ProductPhoto.MAX_PER_COLOR)

    def test_colours_have_separate_limits(self):
        for _ in range(ProductPhoto.MAX_PER_COLOR):
            self._upload("ЧЕРНЫЙ")
        self.assertTrue(self._upload("МЯТНЫЙ").json()["ok"], "лимит слипся между цветами")

    def test_foreign_file_is_refused(self):
        r = self._upload(data=b"MZ\x90\x00 not a picture", name="virus.exe",
                         ctype="application/octet-stream")
        self.assertEqual(r.status_code, 400)
        self.assertFalse(ProductPhoto.objects.exists())

    def test_broken_picture_is_refused_politely(self):
        """Расширение картинки, а внутри мусор: 400 с объяснением, а не 500."""
        r = self._upload(data=PNG[:8] + b"broken", name="broken.png")
        self.assertEqual(r.status_code, 400)
        self.assertFalse(r.json()["ok"])

    def test_upload_without_model_is_refused(self):
        self.assertEqual(self._upload(key="").status_code, 400)

    def test_upload_is_written_to_audit(self):
        self._upload("ЧЕРНЫЙ")
        self.assertTrue(StaffAudit.objects.filter(action__contains="фото модели").exists())

    # ── Удаление и обложка ──────────────────────────────────────────────────
    def test_delete_frees_a_slot_and_renumbers(self):
        ids = [self._upload().json()["id"] for _ in range(3)]
        r = self.client.post(PAGE, {"action": "delete", "id": ids[0]})
        self.assertTrue(r.json()["ok"])
        self.assertEqual(list(ProductPhoto.objects.values_list("order", flat=True)), [0, 1])

    def test_make_main_moves_the_photo_first(self):
        ids = [self._upload().json()["id"] for _ in range(3)]
        self.client.post(PAGE, {"action": "main", "id": ids[2]})
        self.assertEqual(ProductPhoto.objects.get(pk=ids[2]).order, 0)
        self.assertEqual(sorted(ProductPhoto.objects.values_list("order", flat=True)),
                         [0, 1, 2], "порядок разъехался")

    def test_delete_of_unknown_photo_is_404(self):
        self.assertEqual(self.client.post(PAGE, {"action": "delete", "id": 999}).status_code, 404)

    # ── Доступ ──────────────────────────────────────────────────────────────
    def test_tab_permission_required(self):
        staff = get_user_model().objects.create_user("clerk_ph", "c@t.dev", "ClerkPass!2026",
                                                     is_staff=True)
        StaffProfile.objects.create(user=staff, full_name="Кладовщик")
        c = self.client_class()
        login_admin(c, "clerk_ph", "ClerkPass!2026")
        self.assertNotEqual(c.get(PAGE).status_code, 200, "открылось без права на вкладку")
