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
    "preview", "name", "brand", "article", "category_name", "price",
    "stock", "in_stock", "is_published", "is_featured", "is_new", "sort_site",
    "sort_app", "sizes_list", "colors_list", "is_active_1c", "source_updated_at",
    "parcel", "description_short", "onec_code",
]


class ColumnPickerTests(TestCase):
    def setUp(self):
        get_user_model().objects.create_superuser("owner_cols", "oc@t.dev", "OwnerPass!2026")
        login_admin(self.client, "owner_cols", "OwnerPass!2026")
        Product.objects.create(id="p_col", name="Кроссовки", category_id="c",
                               price=5000, old_price=7000)

    def test_panel_is_offered(self):
        html = self.client.get(LIST).content.decode()
        self.assertIn("Столбцы", html)
        self.assertIn(COLUMNS, html)

    def test_all_1c_data_is_shown(self):
        """Всё, что присылает 1С, видно в таблице без настройки."""
        html = self.client.get(LIST).content.decode()
        for label in ("Артикул", "Размеры", "Цвета",
                      "В продаже (1С)", "Изменён в 1С", "Остаток"):
            self.assertIn(label, html, f"нет колонки «{label}»")

    def test_panel_is_outside_the_list_form(self):
        """Форма в форме запрещена в HTML: браузер выбрасывает внутреннюю, и кнопка
        «Применить» уходит не туда. Панель обязана стоять ДО формы списка."""
        html = self.client.get(LIST).content.decode()
        self.assertLess(html.index('class="m-cols"'), html.index('id="changelist-form"'))

    def test_table_is_not_clipped(self):
        """Обрезка таблицы убивает боковую прокрутку: полоса внизу есть, а двигать нечего.
        Реальный случай 18.09.2026 — `overflow: clip` ради скруглённых углов."""
        from django.conf import settings

        css = (settings.BASE_DIR / "static" / "admin" / "mata.css").read_text(encoding="utf-8")
        block = css.split("#result_list {", 1)[1].split("}", 1)[0]
        self.assertNotIn("overflow: hidden", block)
        self.assertNotIn("overflow: clip", block)

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


class CategoryRefTests(TestCase):
    """В карточке товара категория приходит кодом 1С — рядом должно быть название.

    В поле «Категория» лежит GUID из их справочника: по нему не понять, о чём речь,
    а если категории с таким кодом у нас нет, товар молча пропадает с витрины.
    """

    def setUp(self):
        get_user_model().objects.create_superuser("owner_cat", "cat@t.dev", "OwnerPass!2026")
        login_admin(self.client, "owner_cat", "OwnerPass!2026")
        from catalog.models import Category

        Category.objects.create(id="38d6081b-b0cd-11f1", name="Обувь")

    def _card(self, pid):
        return self.client.get(f"/admin/catalog/product/{pid}/change/").content.decode()

    def test_known_category_shows_its_name(self):
        Product.objects.create(id="p_cat", name="Кроссовки", category_id="38d6081b-b0cd-11f1",
                               price=100)
        self.assertIn("Обувь", self._card("p_cat"))

        # Код 1С в самой строке не повторяем: он и так в поле «Категория» выше.
        # (В ссылке на карточку категории он остаётся — это адрес, а не текст.)
        product_admin = admin.site._registry[Product]
        shown = product_admin.category_ref(Product.objects.get(pk="p_cat"))
        self.assertIn("Обувь", shown)
        self.assertNotIn("38d6081b-b0cd-11f1</span>", shown)
        self.assertNotIn("m-mono", shown)

    def test_unknown_category_is_flagged(self):
        Product.objects.create(id="p_lost", name="Кроссовки", category_id="нет-такого",
                               price=100)
        self.assertIn("категории с таким кодом нет", self._card("p_lost"))

    def test_empty_category_is_flagged(self):
        Product.objects.create(id="p_none", name="Кроссовки", category_id="", price=100)
        self.assertIn("категория не указана", self._card("p_none"))
