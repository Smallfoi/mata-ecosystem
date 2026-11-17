"""Плитки «Фото товаров»: у каждого цвета — свой артикул.

16.11.2026 владелец увидел у BMAI PURE 2.0 CORDURA одинаковый артикул XRPM008-3 на
жёлтом, мятном и фиолетовом: плитка брала артикул первой позиции модели. В 1С
артикул — у модели в цвете (-3 жёлтый, -5 мятный, -6 фиолетовый).
"""
from django.test import TestCase

from catalog.models import Product
from config.product_photos_view import _pairs


def item(pid, color, article, size):
    return Product.objects.create(
        id=pid, name=f"BMAI PURE 2.0 CORDURA, {color.upper()} {size}р.", category_id="c1",
        price=9990, brand="BMAI", colors=[color], sizes=[size], article=article,
        model_key="bmai pure 2.0 cordura")


class PhotoTileArticleTests(TestCase):
    def test_each_colour_shows_its_own_article(self):
        item("p1", "Желтый", "XRPM008-3", "35")
        item("p2", "Желтый", "XRPM008-3", "36")
        item("p3", "Мятный", "XRPM008-5", "35")
        item("p4", "Фиолетовый", "XRPM008-6", "35")
        tiles = {t["color"]: t["meta"] for t in _pairs(Product.objects.order_by("id"))}
        self.assertEqual(tiles, {"Желтый": "BMAI · XRPM008-3", "Мятный": "BMAI · XRPM008-5",
                                 "Фиолетовый": "BMAI · XRPM008-6"})

    def test_a_colour_without_an_article_shows_none_rather_than_another(self):
        item("p1", "Желтый", "XRPM008-3", "35")
        item("p2", "Мятный", "", "35")
        tiles = {t["color"]: t["meta"] for t in _pairs(Product.objects.order_by("id"))}
        self.assertEqual(tiles["Мятный"], "BMAI")

    def test_a_model_without_colours_keeps_its_article(self):
        Product.objects.create(id="p9", name="Бафф STAW", category_id="c1", price=990,
                               brand="STAW", article="ST-1", model_key="бафф staw")
        self.assertEqual(_pairs(Product.objects.all())[0]["meta"], "STAW · ST-1")
