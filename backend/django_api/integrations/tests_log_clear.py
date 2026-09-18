"""Очистка журнала обмена: удалять записи может только владелец.

Журнал — разбор того, что и когда прислала 1С. Право на вкладку даёт смотреть, но не
переписывать прошлое: стереть историю может лишь закреплённый владелец (D-88).
"""
from django.contrib.auth import get_user_model
from django.test import TestCase

from common.testutils import login_admin, verify_admin
from integrations.models import OneCExchange
from staff.models import LEVEL_FULL, StaffAudit, StaffProfile, TabPermission

PAGE = "/admin/1c-log/"


class LogClearTests(TestCase):
    def setUp(self):
        for n in range(3):
            OneCExchange.objects.create(operation="catalog", status="ok", received=n)
        self.owner = get_user_model().objects.create_superuser("owner_l", "o@t.dev",
                                                              "OwnerPass!2026")
        login_admin(self.client, "owner_l", "OwnerPass!2026")

    def _ids(self):
        return list(OneCExchange.objects.order_by("id").values_list("id", flat=True))

    def _staff_with_full_access(self):
        staff = get_user_model().objects.create_user("ops@t.dev", "ops@t.dev", "OpsPass!2026",
                                                     is_staff=True)
        StaffProfile.objects.create(user=staff, full_name="Оператор")
        TabPermission.objects.create(user=staff, tab="onec_log", level=LEVEL_FULL)
        self.client.logout()
        self.client.force_login(staff)
        verify_admin(self.client, staff)
        return staff

    def test_owner_deletes_selected_records(self):
        ids = self._ids()
        r = self.client.post(PAGE, {"id": [str(ids[0]), str(ids[2])]})
        self.assertEqual(r.status_code, 302)          # POST → redirect, F5 не повторит
        self.assertEqual(self._ids(), [ids[1]])

    def test_deletion_is_written_to_the_staff_log(self):
        self.client.post(PAGE, {"id": [str(self._ids()[0])]})
        self.assertTrue(StaffAudit.objects.filter(action="удалены записи журнала обмена: 1")
                        .exists())

    def test_nothing_selected_deletes_nothing(self):
        self.client.post(PAGE, {})
        self.assertEqual(len(self._ids()), 3)

    def test_owner_sees_the_button(self):
        html = self.client.get(PAGE).content.decode()
        self.assertIn("Удалить выбранные", html)
        self.assertIn('name="id"', html)

    def test_staff_cannot_delete_even_with_full_tab_rights(self):
        self._staff_with_full_access()
        r = self.client.post(PAGE, {"id": [str(self._ids()[0])]})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(len(self._ids()), 3)

    def test_staff_does_not_see_the_button(self):
        self._staff_with_full_access()
        html = self.client.get(PAGE).content.decode()
        self.assertEqual(self.client.get(PAGE).status_code, 200, "смотреть журнал он может")
        self.assertNotIn("Удалить выбранные", html)
