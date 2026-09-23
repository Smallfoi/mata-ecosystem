"""Витринное название: складское имя 1С → чистое имя модели.

Примеры взяты с боевого каталога (787 позиций витрины), не придуманы.
1С намеренно дублирует в названии артикул, цвет и размер — это нужно магазину
для термоэтикеток и работы в офлайн-точке, менять нельзя. Покупателю показываем
разобранное имя.
"""
from django.test import TestCase, override_settings

from catalog.models import Product
from catalog.naming import shop_name

TOKEN = "test-1c-token"
CATALOG = "/v1/integrations/1c/catalog"


class ShopNameTests(TestCase):
    def test_shoes_drop_color_and_size(self):
        self.assertEqual(
            shop_name("BMAI EXPEDITION CORDURA ЧЕРНЫЙ-СЕРЫЙ 42.5р.", ["42.5"], ["ЧЕРНЫЙ-СЕРЫЙ"]),
            "BMAI EXPEDITION CORDURA")
        self.assertEqual(
            shop_name("ANTA LIGHT Серый/Серый/Серебристый 42.5р.", ["42.5"],
                      ["Серый/Серый/Серебристый"]),
            "ANTA LIGHT")

    def test_clothes_with_article_block(self):
        """«арт. … цвет … р. …» — складской формат одежды, режется целиком."""
        self.assertEqual(
            shop_name("ЖИЛЕТ Жен. BMAI арт. FRWK006-1 цвет ЧЕРНЫЙ р. XL"),
            "Жилет женский BMAI")
        self.assertEqual(
            shop_name("ШОРТЫ мужские BMAI ЧЕРНЫЙ арт.FRSM007-1 р.S"),
            "Шорты мужские BMAI")

    def test_size_without_field(self):
        """1С не прислала размер полем — убираем хвост из названия."""
        self.assertEqual(shop_name("Трусы ANTA CHN Серый M"), "Трусы ANTA CHN")
        self.assertEqual(shop_name("Нижнее белье ANTA Черный 2XL"), "Нижнее белье ANTA")
        self.assertEqual(shop_name("Майка Anta RACING CHALLENGE мужской Фиолетовый (2XL)"),
                         "Майка Anta RACING CHALLENGE мужской")

    def test_cyrillic_size_letter(self):
        """«р. М» — размер, набранный русской буквой."""
        self.assertEqual(shop_name("MATA футболка женская синий р. М"),
                         "MATA футболка женская")

    def test_field_wins_over_name(self):
        """При расхождении верим полю: в справочнике «Черный», в названии «Черное серебро»."""
        self.assertEqual(shop_name("ANTA AIR WALKER Черное серебро 40р.", ["40"], ["Черный"]),
                         "ANTA AIR WALKER")

    def test_flavour_is_a_variant_too(self):
        """1С кладёт в «цвет» и вкус — тогда вкус тоже уходит из имени модели."""
        self.assertEqual(
            shop_name("RUNGEL FOR LIFE (ОЧИЩЕНИЕ) - ЛОПУХ И КЛЮКВА (45Г)", [], ["Лопух и Клюква"]),
            "RUNGEL FOR LIFE (Очищение) (45г)")

    def test_volume_is_not_a_variant(self):
        """«750мл» — часть товара, а не размер: остаётся."""
        self.assertEqual(
            shop_name("Бутылка для воды, пластиковая SIS черный, 750мл", [], ["черный"]),
            "Бутылка для воды, пластиковая SIS, 750мл")

    def test_case_is_normalised(self):
        """Капс выглядит как складской код; латиницу и бренды не трогаем."""
        self.assertEqual(shop_name("БЛУЗКА Муж. BMAI"), "Блузка мужская BMAI")
        self.assertEqual(shop_name("BMAI EXPEDITION RIVER"), "BMAI EXPEDITION RIVER")

    def test_full_gender_word_is_left_alone(self):
        """«футболка женская» уже по-русски — разворачиваем только сокращения."""
        self.assertEqual(shop_name("BMAI футболка мужская"), "BMAI футболка мужская")

    def test_empty_name(self):
        self.assertEqual(shop_name(""), "")


class ProductShopTitleTests(TestCase):
    def test_rebuild_and_priority(self):
        p = Product.objects.create(id="p1", name="Трусы ANTA CHN Серый M",
                                   category_id="c", price=100)
        p.rebuild_display_name()
        self.assertEqual(p.display_name, "Трусы ANTA CHN")
        self.assertEqual(p.shop_title, "Трусы ANTA CHN")

        p.display_name_override = "Трусы ANTA спортивные"
        self.assertEqual(p.shop_title, "Трусы ANTA спортивные",
                         "ручная правка обязана быть сильнее автоматики")

    def test_storefront_shows_shop_title(self):
        p = Product.objects.create(id="p2", name="BMAI PURE 2.0 ЧЕРНЫЙ 42р.",
                                   category_id="c", price=100, sizes=["42"], colors=["ЧЕРНЫЙ"])
        p.rebuild_display_name()
        p.save(update_fields=["display_name"])
        self.assertEqual(p.to_json()["name"], "BMAI PURE 2.0")
        self.assertEqual(Product.objects.get(pk="p2").name, "BMAI PURE 2.0 ЧЕРНЫЙ 42р.",
                         "складское имя нужно магазину — его не трогаем")


@override_settings(INTEGRATION_1C_TOKEN=TOKEN)
class ExchangeFillsShopNameTests(TestCase):
    def test_exchange_fills_display_name(self):
        self.client.post(CATALOG, {"products": [{
            "id": "SS-N", "name": "ЖИЛЕТ Жен. BMAI арт. FRWK006-1 цвет ЧЕРНЫЙ р. XL",
            "categoryId": "c", "article": "FRWK006-1",
        }]}, content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {TOKEN}")
        p = Product.objects.get(external_id="SS-N")
        self.assertEqual(p.display_name, "Жилет женский BMAI")

    def test_manual_name_survives_exchange(self):
        """Правка владельца не должна стираться следующей выгрузкой."""
        self.client.post(CATALOG, {"products": [{
            "id": "SS-M", "name": "Трусы ANTA CHN Серый M", "categoryId": "c",
        }]}, content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {TOKEN}")
        p = Product.objects.get(external_id="SS-M")
        p.display_name_override = "Бельё ANTA"
        p.save(update_fields=["display_name_override"])

        self.client.post(CATALOG, {"products": [{
            "id": "SS-M", "name": "Трусы ANTA CHN Серый L", "categoryId": "c",
        }]}, content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {TOKEN}")
        p.refresh_from_db()
        self.assertEqual(p.shop_title, "Бельё ANTA")


class RebuildActionTests(TestCase):
    """Кнопка «Пересчитать витринные названия» — чтобы не ходить на сервер."""

    def setUp(self):
        from django.contrib.auth import get_user_model

        from common.testutils import login_admin

        get_user_model().objects.create_superuser("owner_rb", "rb@t.dev", "OwnerPass!2026")
        login_admin(self.client, "owner_rb", "OwnerPass!2026")

    def test_action_fills_names_and_keys(self):
        p = Product.objects.create(id="p_rb", name="Трусы ANTA CHN Серый M",
                                   category_id="c", price=100)
        self.assertEqual(p.display_name, "")

        self.client.post("/admin/catalog/product/", {
            "action": "rebuild_names", "index": "0", "select_across": "0",
            "_selected_action": ["p_rb"],
        })
        p.refresh_from_db()
        self.assertEqual(p.display_name, "Трусы ANTA CHN")
        self.assertEqual(p.model_key, "ТРУСЫ ANTA CHN")

    def test_manual_edits_survive(self):
        p = Product.objects.create(id="p_rb2", name="Трусы ANTA CHN Серый L",
                                   category_id="c", price=100,
                                   display_name_override="Бельё ANTA",
                                   model_key_override="БЕЛЬЁ")
        self.client.post("/admin/catalog/product/", {
            "action": "rebuild_names", "index": "0", "select_across": "0",
            "_selected_action": ["p_rb2"],
        })
        p.refresh_from_db()
        self.assertEqual(p.shop_title, "Бельё ANTA")
        self.assertEqual(p.shop_model_key, "БЕЛЬЁ")
