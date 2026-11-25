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

    def test_bmai_gender_comes_from_the_name(self):
        chart = chart_for(brand="BMAI", article="", name="Кроссовки женские BMAI PACE 6.0",
                          category_name="Кроссовки")
        self.assertEqual(titles(chart), ["BMAI · женская обувь"])
        self.assertEqual(chart["tables"][0]["rows"][0], ["35", "5", "22"])

    def test_unknown_gender_gives_both_tables(self):
        chart = chart_for(brand="BMAI", article="", name="BMAI EXPEDITION CORDURA",
                          category_name="Кроссовки")
        self.assertEqual(titles(chart), ["BMAI · мужская обувь", "BMAI · женская обувь"])

    def test_staw_model_table_wins(self):
        chart = chart_for(brand="STAW", article="26SACK0071850", name="Брюки женские",
                          category_name="Брюки")
        self.assertEqual(len(chart["tables"]), 1)
        self.assertEqual(chart["tables"][0]["columns"][0], "Размер")
        self.assertIn("stawrunning.com", chart["tables"][0]["source"])

    def test_no_chart_for_bottoms_and_unknown_brands(self):
        """Таблица по обхвату груди к брюкам не подходит — лучше никакой, чем неверная."""
        self.assertIsNone(chart_for(brand="ANTA", article="852000000-1", name="Брюки",
                                    category_name="Брюки"))
        self.assertIsNone(chart_for(brand="SIS", article="", name="Гель", category_name="Гели"))


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
