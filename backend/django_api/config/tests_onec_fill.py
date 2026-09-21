"""Страница «Заполненность 1С»: что не заполнено в карточках.

Главное, что проверяем: цифра в сводке и список по ссылке «Показать» — это одно
и то же. Если они разойдутся, страница начнёт врать, а поверить ей будет нечем.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from catalog.models import Category, Product
from common.testutils import login_admin

FILL = "/admin/1c-fill/"
LIST = "/admin/catalog/product/"


class OnecFillTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        Category.objects.create(id="c1", name="Обувь")
        # Заполненная карточка — в «пустых» не числится нигде.
        Product.objects.create(id="p_full", name="BMAI PURE 41р.", global_name="BMAI PURE",
                               brand="BMAI", article="AR-1", category_id="c1", price=7990,
                               sizes=["41"], colors=["чёрный"], description="Кроссовки",
                               image_urls=["a.jpg"], weight_g=800, stock_count=3)
        # Пустая: ни категории, ни бренда, ни фото, ни цены.
        Product.objects.create(id="p_empty", name="Без ничего", price=0)
        # С категорией, которой нет в справочнике: на витрине потеряется.
        Product.objects.create(id="p_lost", name="Чужая категория", category_id="c-НЕТ",
                               price=100, image_urls=["b.jpg"])

    def setUp(self):
        get_user_model().objects.create_superuser("owner_fill", "f@t.dev", "OwnerPass!2026")
        login_admin(self.client, "owner_fill", "OwnerPass!2026")

    def _row(self, key):
        rows = self.client.get(FILL).context["rows"]
        return next(r for r in rows if r["key"] == key)

    def test_page_opens(self):
        r = self.client.get(FILL)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["total"], 3)
        self.assertContains(r, "Что не заполнено")

    def test_counts_match_the_data(self):
        self.assertEqual(self._row("category")["blank"], 1)      # только p_empty
        self.assertEqual(self._row("brand")["blank"], 2)
        self.assertEqual(self._row("price")["blank"], 1)         # цена ноль
        self.assertEqual(self._row("photo")["blank"], 1)
        self.assertEqual(self._row("parcel")["blank"], 2)
        self.assertEqual(self._row("sizes")["blank"], 2)

    def test_link_opens_exactly_those_products(self):
        """Цифра в сводке обязана совпасть со списком по ссылке."""
        for key in ("category", "brand", "photo", "parcel", "sizes", "stock"):
            row = self._row(key)
            page = self.client.get(f"{LIST}?missing={key}")
            self.assertEqual(page.context["cl"].result_count, row["blank"],
                             f"расходится по полю «{row['title']}»")

    def test_foreign_category_is_visible(self):
        r = self.client.get(FILL)
        self.assertEqual(r.context["lost_total"], 1)
        self.assertContains(r, "c-НЕТ")

    def test_ready_counts_only_sellable(self):
        """«Готовы к витрине» — есть категория, цена и фото."""
        self.assertEqual(self.client.get(FILL).context["ready"], 1)

    def test_tab_permission_required(self):
        staff = get_user_model().objects.create_user("clerk_fill", "c@t.dev", "ClerkPass!2026",
                                                     is_staff=True)
        from staff.models import StaffProfile
        StaffProfile.objects.create(user=staff, full_name="Кладовщик")
        c = self.client_class()
        login_admin(c, "clerk_fill", "ClerkPass!2026")
        self.assertNotEqual(c.get(FILL).status_code, 200, "страница открылась без права на вкладку")

    def test_menu_item_present(self):
        html = self.client.get(reverse("admin:index")).content.decode()
        self.assertIn(FILL, html)
