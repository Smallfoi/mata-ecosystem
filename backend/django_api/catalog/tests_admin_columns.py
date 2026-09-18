"""Настройка столбцов в списке товаров: шестерёнка «Столбцы».

Колонок в «Товарах» много — всё, что ведёт 1С, плюс наши поля витрины. Каждый
сотрудник прячет лишнее сам, и выбор переживает выход из админки.

Отдельно проверяем главную опасность: у части колонок правка прямо в списке.
Если скрыть такую колонку, но оставить её в форме, «Сохранить» затрёт значение
пустотой — тихая потеря данных.
"""
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.urls import reverse

from catalog.models import Product
from common.testutils import login_admin
from core.models import AdminColumns

LIST = "/admin/catalog/product/"
COLUMNS = "/admin/catalog/product/columns/"
# Всё, кроме «Старой цены»: имитируем галочки в панели.
ALL_BUT_OLD_PRICE = [
    "preview", "name", "global_name", "brand", "article", "category_name", "price",
    "stock", "in_stock", "is_published", "is_featured", "is_new", "sort_site",
    "sort_app", "sizes_list", "colors_list", "is_active_1c", "source_updated_at",
    "parcel", "description_short", "onec_code",
]


class ColumnPickerTests(TestCase):
    def setUp(self):
        get_user_model().objects.create_superuser("owner_cols", "oc@t.dev", "OwnerPass!2026")
        login_admin(self.client, "owner_cols", "OwnerPass!2026")
        Product.objects.create(id="p_col", name="Кроссовки", category_id="c",
                               price=5000, old_price=7000, global_name="BMAI PURE 2.0")

    def test_panel_is_offered(self):
        html = self.client.get(LIST).content.decode()
        self.assertIn("Столбцы", html)
        self.assertIn(COLUMNS, html)

    def test_all_1c_data_is_shown(self):
        """Всё, что присылает 1С, видно в таблице без настройки."""
        html = self.client.get(LIST).content.decode()
        for label in ("Общее название (1С)", "Артикул", "Размеры", "Цвета",
                      "В продаже (1С)", "Изменён в 1С", "Остаток"):
            self.assertIn(label, html, f"нет колонки «{label}»")

    def test_hidden_column_disappears(self):
        self.client.post(COLUMNS, {"show": ALL_BUT_OLD_PRICE, "next": LIST})
        html = self.client.get(LIST).content.decode()
        self.assertNotIn("field-old_price", html)
        self.assertIn("field-price", html)

    def test_hidden_editable_column_is_not_wiped_on_save(self):
        """Скрыли «Старую цену» и сохранили список — значение осталось."""
        self.client.post(COLUMNS, {"show": ALL_BUT_OLD_PRICE, "next": LIST})
        self.client.post(LIST, {
            "form-TOTAL_FORMS": "1", "form-INITIAL_FORMS": "1",
            "form-MIN_NUM_FORMS": "0", "form-MAX_NUM_FORMS": "1",
            "form-0-id": "p_col", "form-0-price": "5500",
            "form-0-in_stock": "on", "form-0-is_published": "on",
            "form-0-sort_site": "0", "form-0-sort_app": "0",
            "_save": "Сохранить", "index": "0",
        })
        p = Product.objects.get(id="p_col")
        self.assertEqual(p.price, 5500, "правка цены не сохранилась")
        self.assertEqual(p.old_price, 7000, "скрытая колонка затёрлась при сохранении")

    def test_link_column_cannot_be_hidden(self):
        """Название — ссылка на карточку: спрятать его нельзя, иначе список не открыть."""
        self.client.post(COLUMNS, {"show": ["preview"], "next": LIST})
        html = self.client.get(LIST).content.decode()
        self.assertIn("field-name", html)
        self.assertNotIn("name", AdminColumns.objects.get(user__username="owner_cols").hidden)

    def test_choice_is_personal_and_resettable(self):
        self.client.post(COLUMNS, {"show": ALL_BUT_OLD_PRICE, "next": LIST})
        other = get_user_model().objects.create_user("clerk_cols", "cc@t.dev",
                                                     "ClerkPass!2026", is_staff=True)
        self.assertEqual(AdminColumns.objects.filter(user=other).count(), 0)
        # У другого сотрудника — набор по умолчанию: чужой выбор к нему не протекает.
        request = RequestFactory().get(LIST)
        request.user = other
        product_admin = admin.site._registry[Product]
        self.assertEqual(product_admin.hidden_columns(request),
                         tuple(product_admin.columns_hidden_default))

        self.client.post(COLUMNS, {"reset": "1", "next": LIST})
        self.assertIn("field-old_price", self.client.get(LIST).content.decode())

    def test_unsafe_redirect_is_ignored(self):
        r = self.client.post(COLUMNS, {"show": ALL_BUT_OLD_PRICE, "next": "https://evil.tld/"})
        self.assertEqual(r["Location"], reverse("admin:catalog_product_changelist"))
