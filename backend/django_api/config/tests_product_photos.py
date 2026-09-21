"""«Фото товаров»: заливка плиткой (D-91).

Фото ведём мы сами, карточек тысячи — значит заливка обязана быть быстрой и
безопасной: чужой файл под видом картинки принимать нельзя, а без права на
вкладку страница не открывается.
"""
import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from catalog.models import Product
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


@override_settings(MEDIA_ROOT=_MEDIA)
class ProductPhotosTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(_MEDIA, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        get_user_model().objects.create_superuser("owner_ph", "p@t.dev", "OwnerPass!2026")
        login_admin(self.client, "owner_ph", "OwnerPass!2026")
        Product.objects.create(id="p_no", name="Без фото", category_id="c", price=100)
        Product.objects.create(id="p_yes", name="С фото", category_id="c", price=100,
                               image_urls=["a.jpg"])

    def _upload(self, pid, data=PNG, name="photo.png", ctype="image/png"):
        return self.client.post(PAGE, {
            "id": pid, "photo": SimpleUploadedFile(name, data, content_type=ctype),
        })

    def test_page_shows_only_products_without_photo(self):
        r = self.client.get(PAGE)
        self.assertEqual(r.status_code, 200)
        self.assertEqual([i["id"] for i in r.context["items"]], ["p_no"])
        self.assertEqual(r.context["left"], 1)

    def test_all_tab_shows_everything(self):
        r = self.client.get(PAGE, {"only": "all"})
        self.assertEqual(sorted(i["id"] for i in r.context["items"]), ["p_no", "p_yes"])

    def test_upload_saves_photo_and_answers_json(self):
        r = self._upload("p_no")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body["ok"], body)
        self.assertTrue(body["url"])
        self.assertTrue(Product.objects.get(id="p_no").image)
        # После заливки товар уходит из списка «без фото» — счётчик уменьшается.
        self.assertEqual(self.client.get(PAGE).context["left"], 0)

    def test_upload_is_written_to_audit(self):
        self._upload("p_no")
        self.assertTrue(StaffAudit.objects.filter(action__contains="фото товара p_no").exists())

    def test_foreign_file_is_refused(self):
        r = self._upload("p_no", data=b"MZ\x90\x00 not a picture", name="virus.exe",
                         ctype="application/octet-stream")
        self.assertEqual(r.status_code, 400)
        self.assertFalse(r.json()["ok"])
        self.assertFalse(Product.objects.get(id="p_no").image)

    def test_unknown_product_is_refused(self):
        self.assertEqual(self._upload("нет-такого").status_code, 404)

    def test_search_finds_by_name(self):
        r = self.client.get(PAGE, {"q": "Без"})
        self.assertEqual([i["id"] for i in r.context["items"]], ["p_no"])

    def test_tab_permission_required(self):
        staff = get_user_model().objects.create_user("clerk_ph", "c@t.dev", "ClerkPass!2026",
                                                     is_staff=True)
        StaffProfile.objects.create(user=staff, full_name="Кладовщик")
        c = self.client_class()
        login_admin(c, "clerk_ph", "ClerkPass!2026")
        self.assertNotEqual(c.get(PAGE).status_code, 200, "открылось без права на вкладку")
