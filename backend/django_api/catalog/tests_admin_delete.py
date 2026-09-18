"""Массовое удаление товаров в админке.

Владелец выбрал «все 3309» и получил 400: страница подтверждения штатного действия
кладёт скрытое поле на каждый товар, а запрос принимает не больше
`DATA_UPLOAD_MAX_NUMBER_FIELDS` (1000). Своё действие подтверждает удаление, не
раздувая форму, и удаляет пачками.
"""
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase

from catalog.models import Product
from common.testutils import login_admin, verify_admin
from staff.models import LEVEL_EDIT, LEVEL_FULL, StaffAudit, StaffProfile, TabPermission

LIST = "/admin/catalog/product/"
PAGE = 100  # столько строк на странице списка — столько и приходит в запросе


class DeleteProductsTests(TestCase):
    def setUp(self):
        Product.objects.bulk_create([
            Product(id=f"p{i:04d}", name=f"Товар {i}", category_id="c", price=100)
            for i in range(120)
        ])
        get_user_model().objects.create_superuser("owner_d", "o@t.dev", "OwnerPass!2026")
        login_admin(self.client, "owner_d", "OwnerPass!2026")

    def _page_ids(self):
        return list(Product.objects.order_by("id").values_list("id", flat=True)[:PAGE])

    def _act(self, **extra):
        data = {"action": "delete_products", "index": "0", "select_across": "0",
                "_selected_action": self._page_ids()}
        data.update(extra)
        return self.client.post(LIST, data)

    def test_select_all_deletes_everything_at_once(self):
        confirm = self._act(select_across="1")
        self.assertEqual(confirm.status_code, 200)
        self.assertEqual(confirm.context["count"], 120)
        # Ключевое: в форме подтверждения полей столько же, сколько пришло со страницы,
        # а не по одному на каждый из 120 товаров — иначе снова 400.
        self.assertEqual(len(confirm.context["selected"]), PAGE)

        done = self._act(select_across="1", confirm="yes")
        self.assertEqual(done.status_code, 302)
        self.assertEqual(Product.objects.count(), 0)

    def test_without_select_all_deletes_only_marked(self):
        ids = self._page_ids()[:3]
        self.client.post(LIST, {"action": "delete_products", "index": "0", "select_across": "0",
                                "confirm": "yes", "_selected_action": ids})
        self.assertEqual(Product.objects.count(), 117)
        self.assertFalse(Product.objects.filter(id__in=ids).exists())

    def test_deletes_in_chunks(self):
        with mock.patch("catalog.admin.DELETE_CHUNK", 7):
            self._act(select_across="1", confirm="yes")
        self.assertEqual(Product.objects.count(), 0)

    def test_deletion_is_written_to_the_staff_log(self):
        self._act(select_across="1", confirm="yes")
        self.assertTrue(StaffAudit.objects.filter(action="удалено товаров: 120").exists())

    def test_broken_standard_action_is_replaced(self):
        choices = dict(self.client.get(LIST).context["action_form"].fields["action"].choices)
        self.assertIn("delete_products", choices)
        self.assertNotIn("delete_selected", choices)

    def test_only_staff_allowed_to_delete(self):
        staff = get_user_model().objects.create_user("merch@t.dev", "merch@t.dev",
                                                     "MerchPass!2026", is_staff=True)
        StaffProfile.objects.create(user=staff, full_name="Контент")
        perm = TabPermission.objects.create(user=staff, tab="catalog.products", level=LEVEL_EDIT)
        self.client.logout()
        self.client.force_login(staff)
        verify_admin(self.client, staff)

        self._act(select_across="1", confirm="yes")
        self.assertEqual(Product.objects.count(), 120, "правки без удаления — товары на месте")

        perm.level = LEVEL_FULL
        perm.save()
        self.client.force_login(staff)
        verify_admin(self.client, staff)
        self._act(select_across="1", confirm="yes")
        self.assertEqual(Product.objects.count(), 0)
