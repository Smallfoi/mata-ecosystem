"""«Согласия» в админке: клиент в списке один раз, его согласия и недостающие — на его странице."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from accounts.models import Account
from common.testutils import login_admin, verify_admin
from legal.models import LegalDocument, UserConsent
from staff.models import LEVEL_VIEW, StaffProfile, TabPermission

LIST = "/admin/legal/consentclient/"


def _doc(doc_type, version="1.0", required=True, published=True):
    return LegalDocument.objects.create(
        doc_type=doc_type, version=version, title=doc_type, is_required=required,
        published_at=timezone.now() if published else None,
    )


class ConsentClientsTests(TestCase):
    def setUp(self):
        self.terms_old = _doc("terms", "0.9")
        self.terms_old.published_at = timezone.now() - timezone.timedelta(days=30)
        self.terms_old.save()
        self.terms = _doc("terms", "1.0")
        self.privacy = _doc("privacy")
        self.marketing = _doc("marketing", required=False)

        self.anna = Account.objects.create(id="u_anna", name="Анна", email="anna@t.dev",
                                           phone="+79990001001")
        self.boris = Account.objects.create(id="u_boris", name="Борис", email="boris@t.dev",
                                            phone="+79990001002")
        Account.objects.create(id="u_nobody", name="Без согласий", email="none@t.dev")
        for doc in (self.terms, self.privacy, self.marketing):
            UserConsent.objects.create(user_id="u_anna", document=doc, source="kvartal")
        UserConsent.objects.create(user_id="u_boris", document=self.terms_old, source="site")

        get_user_model().objects.create_superuser("owner_c", "o@t.dev", "OwnerPass!2026")
        login_admin(self.client, "owner_c", "OwnerPass!2026")

    def test_each_client_is_listed_once(self):
        r = self.client.get(LIST)
        self.assertEqual(r.status_code, 200)
        ids = [c.id for c in r.context["cl"].result_list]
        self.assertEqual(sorted(ids), ["u_anna", "u_boris"])   # «Без согласий» не показываем

    def test_required_status_counts_current_versions_only(self):
        """Борис принял старую версию соглашения — обязательные у него не даны."""
        rows = {c.id: c for c in self.client.get(LIST).context["cl"].result_list}
        self.assertEqual(rows["u_anna"].required_given, 2)
        self.assertEqual(rows["u_boris"].required_given, 0)

    def test_filter_clients_missing_required(self):
        r = self.client.get(LIST + "?required=missing")
        self.assertEqual([c.id for c in r.context["cl"].result_list], ["u_boris"])
        r = self.client.get(LIST + "?required=all")
        self.assertEqual([c.id for c in r.context["cl"].result_list], ["u_anna"])

    def test_search_by_phone(self):
        r = self.client.get(LIST + "?q=1002")
        self.assertEqual([c.id for c in r.context["cl"].result_list], ["u_boris"])

    def test_client_page_shows_given_and_missing(self):
        r = self.client.get(f"{LIST}u_boris/change/")
        self.assertEqual(r.status_code, 200)
        titles = [m["title"] for m in r.context["missing_required"]]
        self.assertEqual(len(titles), 2)
        old = [m for m in r.context["missing_required"] if m["old_version"]]
        self.assertEqual(len(old), 1, "соглашение принято в старой версии — так и пометить")
        self.assertTrue(r.context["rows"][0]["outdated"])
        self.assertContains(r, "Не хватает обязательных")

    def test_client_page_is_read_only(self):
        r = self.client.post(f"{LIST}u_anna/change/", {"name": "Взлом"})
        self.assertNotEqual(Account.objects.get(id="u_anna").name, "Взлом")

    def test_staff_access_follows_the_legal_tab(self):
        staff = get_user_model().objects.create_user("lawyer@t.dev", "lawyer@t.dev",
                                                     "LawyerPass!2026", is_staff=True)
        StaffProfile.objects.create(user=staff, full_name="Юрист")
        self.client.logout()
        self.client.force_login(staff)
        verify_admin(self.client, staff)
        self.assertEqual(self.client.get(LIST).status_code, 403)

        TabPermission.objects.create(user=staff, tab="legal", level=LEVEL_VIEW)
        staff = get_user_model().objects.get(pk=staff.pk)   # сбросить кэш прав
        self.client.force_login(staff)
        verify_admin(self.client, staff)
        self.assertEqual(self.client.get(LIST).status_code, 200)
        self.assertEqual(self.client.get(f"{LIST}u_anna/change/").status_code, 200)
