"""Дымовой обход страниц админки: каждая открывается и рисуется без ошибок.

Появился после перевода всех страниц на единый стиль (D-87): раньше у страниц было
своё оформление, и опечатка в вёрстке всплывала только у владельца. Тест дешёвый —
это защита от «сломал шаблон и не заметил».
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import Account
from catalog.models import Product
from common.testutils import login_admin
from legal.models import LegalDocument, UserConsent
from loyalty.models import LoyaltyTransaction
from orders.models import Order
from staff.models import StaffProfile


class AdminPagesRenderTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        Account.objects.create(id="u_page", name="Анна", email="anna@t.dev", phone="+79990003001")
        Product.objects.create(id="p_page", name="Кроссовки", category_id="c", price=1000,
                               stock_count=3, stock_by_size={"42": 3})
        LoyaltyTransaction.objects.create(id="tx_page", user_id="u_page", amount=100,
                                          source="runnerRun", description="Пробежка 10 км")
        doc = LegalDocument.objects.create(doc_type="terms", version="1.0", title="Соглашение",
                                           is_required=True)
        UserConsent.objects.create(user_id="u_page", document=doc, source="kvartal")
        cls.order = Order.objects.create(
            user_id="u_page", order_id="SS-PAGE", total=1000, payment_status="paid",
            payment_id="pay_page", status="paid",
            payload={"id": "SS-PAGE", "items": [{"productName": "Кроссовки", "price": 1000,
                                                 "quantity": 1}]},
        )
        staff = get_user_model().objects.create_user("clerk@t.dev", "clerk@t.dev", "ClerkPass!2026",
                                                     is_staff=True)
        cls.profile = StaffProfile.objects.create(user=staff, full_name="Кладовщик")

    def setUp(self):
        get_user_model().objects.create_superuser("owner_pages", "o@t.dev", "OwnerPass!2026")
        login_admin(self.client, "owner_pages", "OwnerPass!2026")

    def _open(self, url):
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200, f"{url} → {r.status_code}")
        return r.content.decode()

    def test_every_admin_page_opens(self):
        pages = [
            reverse("admin:index"),
            reverse("merch_console"),
            reverse("errors_console"),
            reverse("admin_storage"),
            reverse("onec_log"),
            reverse("runs_review"),
            reverse("order_return", args=[self.order.pk]),
            reverse("points_clients"),
            reverse("points_client", args=["u_page"]),
            reverse("staff_list"),
            reverse("staff_member", args=[self.profile.pk]),
            reverse("account_security"),
            "/admin/legal/consentclient/",
            "/admin/legal/consentclient/u_5Fpage/change/",
            "/admin/catalog/product/",
        ]
        for url in pages:
            self._open(url)

    def test_pages_use_the_shared_stylesheet(self):
        """Единый стиль подключён темой — значит, классы m-* на страницах работают."""
        html = self._open(reverse("points_clients"))
        self.assertIn("admin/mata.css", html)
        self.assertIn('class="m-card"', html)
        self.assertNotIn("<style>", html.split("</head>")[-1], "своё оформление в теле страницы")

    def test_delete_products_confirmation_opens(self):
        r = self.client.post("/admin/catalog/product/", {
            "action": "delete_products", "index": "0", "select_across": "0",
            "_selected_action": ["p_page"],
        })
        self.assertEqual(r.status_code, 200)
        self.assertIn("m-card", r.content.decode())

    def test_mass_notification_form_opens(self):
        r = self.client.post("/admin/accounts/account/", {
            "action": "send_notification", "index": "0", "_selected_action": ["u_page"],
        })
        self.assertEqual(r.status_code, 200)
        self.assertIn("m-btn", r.content.decode())
