"""Черновики каталога (?preview=1) — только сотрудникам (находка аудита, catalog.preview)."""
from unittest import mock

from django.contrib.auth import get_user_model
from django.core import signing
from django.test import TestCase

from catalog import preview
from catalog.models import Banner, Product
from common.testutils import login_admin


class PreviewAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        Product.objects.create(id="pub1", name="Опубликованный", category_id="c", price=100,
                               model_key="PUB")
        Product.objects.create(id="draft1", name="Черновик", category_id="c", price=100,
                               model_key="DRAFT", is_published=False)
        Banner.objects.create(title="Черновой баннер", is_published=False)
        User = get_user_model()
        cls.staff = User.objects.create_superuser("owner_pv", "pv@t.dev", "OwnerPass!2026")
        cls.plain = User.objects.create_user("plain_pv", "plain@t.dev", "PlainPass!2026")

    def _ids(self, url):
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        return {p["id"] for p in r.json()}

    def _has_draft(self, suffix=""):
        """Черновик виден на всех витринных адресах? (products / models / деталь / баннеры)"""
        prods = "draft1" in self._ids("/v1/products?preview=1" + suffix)
        models = any("Черновик" in str(c) for c in
                     self.client.get("/v1/models?preview=1" + suffix).json())
        detail = self.client.get("/v1/products/draft1?preview=1" + suffix).status_code == 200
        banners = any(b.get("title") == "Черновой баннер" for b in
                      self.client.get("/v1/banners?preview=1" + suffix).json())
        return prods, models, detail, banners

    def test_anonymous_preview_param_ignored(self):
        """Раньше ?preview=1 открывал черновики любому."""
        self.assertEqual(self._has_draft(), (False, False, False, False))
        # Обычная витрина при этом работает.
        self.assertIn("pub1", self._ids("/v1/products?preview=1"))

    def test_staff_token_opens_drafts(self):
        token = preview.issue_token(self.staff)
        self.assertEqual(self._has_draft("&preview_token=" + token), (True, True, True, True))

    def test_token_in_header(self):
        token = preview.issue_token(self.staff)
        r = self.client.get("/v1/products?preview=1", HTTP_X_PREVIEW_TOKEN=token)
        self.assertIn("draft1", {p["id"] for p in r.json()})

    def test_token_without_preview_param_changes_nothing(self):
        token = preview.issue_token(self.staff)
        self.assertNotIn("draft1", self._ids("/v1/products?preview_token=" + token))

    def test_bad_tokens_rejected(self):
        forged = signing.TimestampSigner(salt="чужая соль").sign(str(self.staff.pk))
        for token in ("", "garbage", forged, preview.issue_token(self.plain)):
            with self.subTest(token=token[:20]):
                self.assertEqual(self._has_draft("&preview_token=" + token),
                                 (False, False, False, False))

    def test_expired_token_rejected(self):
        token = preview.issue_token(self.staff)
        with mock.patch.object(preview, "PREVIEW_TOKEN_TTL", -1):
            self.assertNotIn("draft1", self._ids("/v1/products?preview=1&preview_token=" + token))

    def test_token_dies_with_staff_rights(self):
        User = get_user_model()
        worker = User.objects.create_user("worker_pv", "w@t.dev", "WorkerPass!2026",
                                          is_staff=True)
        token = preview.issue_token(worker)
        url = "/v1/products?preview=1&preview_token=" + token
        self.assertIn("draft1", self._ids(url))
        User.objects.filter(pk=worker.pk).update(is_staff=False)
        self.assertNotIn("draft1", self._ids(url))
        User.objects.filter(pk=worker.pk).update(is_staff=True, is_active=False)
        self.assertNotIn("draft1", self._ids(url))

    def test_admin_session_alone_is_not_a_pass(self):
        """Сессия админки без токена черновики не открывает (фреймы cookie и не шлют)."""
        login_admin(self.client, "owner_pv", "OwnerPass!2026")
        self.assertNotIn("draft1", self._ids("/v1/products?preview=1"))

    def test_merch_console_hands_token_to_frames(self):
        """Конструктор отдаёт фреймам сайта и приложения рабочий токен."""
        login_admin(self.client, "owner_pv", "OwnerPass!2026")
        r = self.client.get("/admin/merch/")
        self.assertEqual(r.status_code, 200)
        token = r.context["preview_token"]
        self.assertTrue(token)
        self.assertIn("&pt=", r.context["site_preview_url"])
        self.assertContains(r, 'data-preview-token="%s"' % token)
        self.client.logout()
        self.assertIn("draft1", self._ids("/v1/products?preview=1&preview_token=" + token))
