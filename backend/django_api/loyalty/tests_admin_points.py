"""«Баллы» в админке: клиенты за выбранные дни, по клику — их начисления с балансом после."""
from datetime import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from accounts.models import Account
from common.testutils import login_admin, verify_admin
from loyalty.models import LoyaltyTransaction
from staff.models import LEVEL_EDIT, LEVEL_VIEW, StaffProfile, TabPermission

LIST = "/admin/points/"


def _at(day, hour=10):
    """Время по Якутску (TIME_ZONE) — дни в разделе считаются именно так."""
    return timezone.make_aware(datetime(2026, 9, day, hour, 0))


def _txn(uid, amount, source, day, hour=10, **kw):
    return LoyaltyTransaction.objects.create(
        id=f"tx_{uid}_{day}_{hour}_{amount}", user_id=uid, amount=amount, source=source,
        created_at=_at(day, hour), **kw)


class PointsPagesTests(TestCase):
    def setUp(self):
        Account.objects.create(id="u_anna", name="Анна", email="anna@t.dev", phone="+79990002001")
        Account.objects.create(id="u_boris", name="Борис", email="boris@t.dev", phone="+79990002002")
        _txn("u_anna", 100, "runnerRun", 2, description="Пробежка 10 км")
        _txn("u_anna", 50, "runnerTerritory", 5, 9)
        _txn("u_anna", -30, "redeem", 5, 18, order_id="SS-77")
        _txn("u_boris", 40, "runnerRun", 2)
        # 23:30 5-го по Якутску — это ещё 5-е, хотя по UTC уже другой час суток.
        _txn("u_boris", 10, "runnerRun", 5, 23)

        get_user_model().objects.create_superuser("owner_p", "o@t.dev", "OwnerPass!2026")
        login_admin(self.client, "owner_p", "OwnerPass!2026")

    def _rows(self, query=""):
        r = self.client.get(LIST + query)
        self.assertEqual(r.status_code, 200)
        return {row["name"]: row for row in r.context["rows"]}, r

    def test_each_client_once_with_balance(self):
        rows, _ = self._rows()
        self.assertEqual(set(rows), {"Анна", "Борис"})
        self.assertEqual(rows["Анна"]["balance"], 120)
        self.assertEqual(rows["Анна"]["ops"], 3)

    def test_single_day_shows_who_got_what_that_day(self):
        rows, r = self._rows("?date_from=2026-09-05")
        self.assertEqual(rows["Анна"]["earned"], 50)
        self.assertEqual(rows["Анна"]["spent"], 30)
        self.assertEqual(rows["Анна"]["ops"], 2)
        self.assertEqual(rows["Борис"]["earned"], 10)
        self.assertEqual(r.context["totals"], {"earned": 60, "spent": 30, "ops": 3, "clients": 2})

    def test_day_without_operations_lists_nobody(self):
        rows, r = self._rows("?date_from=2026-09-03")
        self.assertEqual(rows, {})
        self.assertContains(r, "операций с баллами нет")

    def test_range_and_reversed_dates(self):
        rows, _ = self._rows("?date_from=2026-09-02&date_to=2026-09-01")   # перепутаны местами
        self.assertEqual(rows["Анна"]["earned"], 100)
        self.assertEqual(rows["Борис"]["earned"], 40)

    def test_search_by_phone(self):
        rows, _ = self._rows("?q=2002")
        self.assertEqual(set(rows), {"Борис"})

    def test_garbage_date_is_ignored(self):
        rows, _ = self._rows("?date_from=вчера")
        self.assertEqual(set(rows), {"Анна", "Борис"})

    def test_client_page_for_a_day_with_balance_after(self):
        r = self.client.get("/admin/points/u_anna/?date_from=2026-09-05&date_to=2026-09-05")
        self.assertEqual(r.status_code, 200)
        rows = r.context["rows"]
        self.assertEqual([x["amount"] for x in rows], [-30, 50])           # свежие сверху
        self.assertEqual([x["balance_after"] for x in rows], [120, 150])    # до периода было 100
        self.assertEqual(rows[1]["label"], "Захват территории")
        self.assertEqual(rows[0]["label"], "Оплата баллами")
        self.assertEqual(r.context["balance"], 120)
        self.assertContains(r, "SS-77")

    def test_client_page_without_period_shows_everything(self):
        r = self.client.get("/admin/points/u_anna/")
        self.assertEqual(len(r.context["rows"]), 3)

    def test_unknown_client_is_404(self):
        self.assertEqual(self.client.get("/admin/points/u_nobody/").status_code, 404)

    def test_staff_access_and_adjustment_link(self):
        staff = get_user_model().objects.create_user("acc@t.dev", "acc@t.dev", "AccPass!2026",
                                                     is_staff=True)
        StaffProfile.objects.create(user=staff, full_name="Бухгалтер")
        self.client.logout()
        self.client.force_login(staff)
        verify_admin(self.client, staff)
        self.assertEqual(self.client.get(LIST).status_code, 403)

        perm = TabPermission.objects.create(user=staff, tab="loyalty", level=LEVEL_VIEW)
        r = self.client.get("/admin/points/u_anna/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["adjust_url"], "", "смотрящему корректировка не положена")

        perm.level = LEVEL_EDIT
        perm.save()
        r = self.client.get("/admin/points/u_anna/")
        self.assertIn("/admin/loyalty/loyaltytransaction/add/?user_id=u_anna", r.context["adjust_url"])
