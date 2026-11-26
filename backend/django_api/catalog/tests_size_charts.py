"""Таблица размеров и артикул цвета в карточке модели (D-138, 25.11.2026)."""
from django.test import SimpleTestCase, TestCase

from catalog.models import Category, Product
from catalog.models_api import build_card
from catalog.size_charts import chart_for


def titles(chart):
    return [t["title"] for t in chart["tables"]] if chart else None


class ChartForTests(SimpleTestCase):
    def test_anta_gender_comes_from_the_article(self):
        """812… — мужская обувь, 822… — женская (сверено с anta-sport.ru)."""
        men = chart_for(brand="ANTA", article="812625546-1", name="ANTA WALK 3.0",
                        category_name="Кроссовки")
        women = chart_for(brand="ANTA", article="822415583-6", name="ANTA MACH 4.0",
                          category_name="Кроссовки")
        self.assertEqual(titles(men), ["ANTA · мужская обувь"])
        self.assertEqual(titles(women), ["ANTA · женская обувь"])

    def test_footwear_columns_start_with_eu(self):
        """Наш размер — EU: по первой колонке витрина подсвечивает выбранный размер."""
        t = chart_for(brand="ANTA", article="812625546-1", name="",
                      category_name="Кроссовки")["tables"][0]
        self.assertEqual(t["columns"][0], "EU")
        self.assertEqual(t["match"], 0)
        self.assertIn(["42", "41", "8,5", "7,5", "26,5", "248"], t["rows"])

    def test_gender_comes_from_the_name_when_article_says_nothing(self):
        chart = chart_for(brand="ANTA", article="", name="Кроссовки женские ANTA",
                          category_name="Кроссовки")
        self.assertEqual(titles(chart), ["ANTA · женская обувь"])

    def test_unknown_gender_gives_both_tables(self):
        chart = chart_for(brand="ANTA", article="", name="ANTA WALK 2.0",
                          category_name="Кроссовки")
        self.assertEqual(titles(chart), ["ANTA · мужская обувь", "ANTA · женская обувь"])

    def test_bmai_model_without_table_on_site_gets_none(self):
        """Общей таблицы BMAI нет: сетки у моделей разные, чужую не подставляем (26.11.2026)."""
        self.assertIsNone(chart_for(brand="BMAI", article="XRMJ003-1", name="BMAI HUNTER 2",
                                    category_name="Кроссовки"))

    def test_staw_model_table_wins(self):
        chart = chart_for(brand="STAW", article="26SACK0071850", name="Брюки женские",
                          category_name="Брюки")
        self.assertEqual(len(chart["tables"]), 1)
        self.assertEqual(chart["tables"][0]["columns"][0], "Размер")
        self.assertIn("stawrunning.com", chart["tables"][0]["source"])

    def test_bottoms_get_waist_table_not_chest(self):
        """Низу — таблица по талии (ANTA, 26.11.2026); таблица по груди к брюкам не подходит."""
        men = chart_for(brand="ANTA", article="852515507C-1", name="Шорты мужские ANTA",
                        category_name="Шорты")
        women = chart_for(brand="ANTA", article="862647311N-1", name="Брюки", category_name="Брюки")
        self.assertEqual(titles(men), ["ANTA · мужской низ"])
        self.assertEqual(titles(women), ["ANTA · женский низ"])
        self.assertEqual(men["tables"][0]["columns"][2], "Обхват талии, см")
        self.assertIn(["M", "48-50", "80-84", "170-175"], men["tables"][0]["rows"])

    def test_no_chart_where_brand_publishes_none(self):
        """Общей таблицы одежды у BMAI нет — только своя у модели; у питания размеров нет вовсе."""
        self.assertIsNone(chart_for(brand="BMAI", article="", name="Шорты мужские BMAI",
                                    category_name="Шорты"))
        self.assertIsNone(chart_for(brand="SIS", article="", name="Гель", category_name="Гели"))

    def test_bmai_carbon_model_has_its_own_grid(self):
        """GCARBON 4 — своя сетка со страницы модели (26.11.2026): после 46 сразу 47 = US 13."""
        chart = chart_for(brand="BMAI", article="XRMM001-4", name="Кроссовки мужские BMAI GCARBON-4",
                          category_name="Кроссовки")
        t = chart["tables"][0]
        self.assertEqual(len(chart["tables"]), 1)
        self.assertEqual(t["columns"][:3], ["EU", "US", "Длина стопы, см"])
        self.assertIn(["47", "13", "30,5"], t["rows"])
        self.assertIn("bmai.com", t["source"])

    def test_bmai_unknown_gender_model_gets_both_own_tables(self):
        """Пол в названии 1С не указан — обе таблицы модели, а не общая таблица бренда."""
        chart = chart_for(brand="BMAI", article="XRPL003-2", name="BMAI PACE 6.0",
                          category_name="Кроссовки")
        self.assertEqual(titles(chart), ["BMAI · мужская обувь", "BMAI · женская обувь"])
        self.assertNotIn(["47", "13", "30,5"], chart["tables"][0]["rows"])

    def test_bmai_apparel_weight_is_in_kg(self):
        """На bmai.com вес в цзинях — у нас в кг (1 цзинь = 0,5 кг)."""
        t = chart_for(brand="BMAI", article="FRTM007-1", name="Футболка мужская BMAI",
                      category_name="Футболка")["tables"][0]
        self.assertEqual(t["columns"][0], "Размер")
        self.assertIn("Вес, кг", t["columns"])
        self.assertIn("2XL", [r[0] for r in t["rows"]])


class CardFieldsTests(TestCase):
    def test_card_has_colour_article_and_size_chart(self):
        Category.objects.create(id="shoes", name="Кроссовки")
        for pid, art, color in (("p1", "812625546-1", "Серый"), ("p2", "812625546-2", "Черный")):
            Product.objects.create(id=pid, name="ANTA WALK 3.0", brand="ANTA", category_id="shoes",
                                   price=9000, article=art, colors=[color], sizes=["42"],
                                   model_key="812625546")
        card = build_card(Product.objects.order_by("id"))
        self.assertEqual([c["article"] for c in card["colors"]], ["812625546-1", "812625546-2"])
        self.assertEqual(titles(card["sizeChart"]), ["ANTA · мужская обувь"])

    def test_card_without_chart_says_null(self):
        Product.objects.create(id="g1", name="Гель SIS", brand="SIS", category_id="gel", price=300)
        card = build_card(Product.objects.all())
        self.assertIsNone(card["sizeChart"])
