"""Карточки моделей на витрине: один товар — много цветов и размеров (D-94).

В 1С каждый размер и цвет — отдельная позиция (склад, этикетки). Покупатель
должен видеть одну карточку и выбирать внутри, а чего нет на складе — то
недоступно. Примеры названий взяты с боевого каталога.
"""
from django.test import TestCase

from catalog.models import Product
from catalog.naming import (article_from_name, color_from_name, model_base,
                            model_key, size_from_name)


def make(pid, name, **extra):
    data = dict(id=pid, name=name, category_id="c1", price=3990)
    data.update(extra)
    product = Product.objects.create(**data)
    product.rebuild_display_name()
    product.save(update_fields=["display_name", "model_key"])
    return product


class ModelKeyTests(TestCase):
    def test_article_is_taken_from_the_name(self):
        self.assertEqual(article_from_name("ШОРТЫ мужские BMAI ЧЕРНЫЙ арт.FRSM007-1 р.S"),
                         "FRSM007-1")
        self.assertEqual(article_from_name("BMAI EXPEDITION CORDURA ЧЕРНЫЙ 42р."), "")

    def test_colour_suffix_is_cut(self):
        self.assertEqual(model_base("FRWK006-1"), "FRWK006")
        self.assertEqual(model_base("FRTK-003-1"), "FRTK-003")

    def test_clothes_group_by_article_not_by_name(self):
        """«ШОРТЫ мужские BMAI» — это три РАЗНЫЕ модели: FRSM007, FRSM009, FRSM013."""
        a = model_key("ШОРТЫ мужские BMAI ЧЕРНЫЙ арт.FRSM007-1 р.S")
        b = model_key("ШОРТЫ мужские BMAI СЕРЫЙ арт.FRSM009-2 р.M")
        self.assertEqual(a, "FRSM007")
        self.assertNotEqual(a, b, "разные модели склеились в одну карточку")

    def test_shoes_group_by_display_name(self):
        """У обуви артикула в названии нет, зато есть имя модели."""
        a = model_key("BMAI EXPEDITION CORDURA ЧЕРНЫЙ-СЕРЫЙ 42р.", ["42"], ["ЧЕРНЫЙ-СЕРЫЙ"])
        b = model_key("BMAI EXPEDITION CORDURA МЯТНЫЙ 38р.", ["38"], ["МЯТНЫЙ"])
        self.assertEqual(a, b)
        self.assertEqual(a, "BMAI EXPEDITION CORDURA")


class ModelCardTests(TestCase):
    def setUp(self):
        # Одна модель обуви: два цвета, по два размера; один размер распродан.
        make("p1", "BMAI EXPEDITION CORDURA ЧЕРНЫЙ 41р.", sizes=["41"], colors=["ЧЕРНЫЙ"],
             stock_count=5, stock_by_size={"41": 5})
        make("p2", "BMAI EXPEDITION CORDURA ЧЕРНЫЙ 42р.", sizes=["42"], colors=["ЧЕРНЫЙ"],
             stock_count=0, stock_by_size={"42": 0})
        make("p3", "BMAI EXPEDITION CORDURA МЯТНЫЙ 41р.", sizes=["41"], colors=["МЯТНЫЙ"],
             stock_count=2, stock_by_size={"41": 2}, price=4490)

    def test_list_returns_one_card(self):
        cards = self.client.get("/v1/models").json()
        self.assertEqual(len(cards), 1, "три складские позиции должны стать одной карточкой")
        card = cards[0]
        self.assertEqual(card["name"], "BMAI EXPEDITION CORDURA")
        self.assertEqual(card["variantCount"], 3)
        self.assertEqual(sorted(c["name"] for c in card["colors"]), ["МЯТНЫЙ", "ЧЕРНЫЙ"])
        self.assertEqual(card["sizes"], ["41", "42"])

    def test_sold_out_size_is_marked(self):
        card = self.client.get("/v1/models").json()[0]
        black = next(c for c in card["colors"] if c["name"] == "ЧЕРНЫЙ")
        by_size = {v["size"]: v["inStock"] for v in black["sizes"]}
        self.assertTrue(by_size["41"])
        self.assertFalse(by_size["42"], "распроданный размер обязан быть недоступен")

    def test_price_is_the_cheapest_available(self):
        card = self.client.get("/v1/models").json()[0]
        self.assertEqual(card["price"], 3990)

    def test_size_keeps_the_product_id(self):
        """Заказ оформляется на складскую позицию, а не на карточку."""
        card = self.client.get("/v1/models").json()[0]
        black = next(c for c in card["colors"] if c["name"] == "ЧЕРНЫЙ")
        self.assertEqual({v["productId"] for v in black["sizes"]}, {"p1", "p2"})

    def test_single_card_by_key(self):
        r = self.client.get("/v1/models/BMAI EXPEDITION CORDURA")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["variantCount"], 3)

    def test_unknown_key_is_404(self):
        self.assertEqual(self.client.get("/v1/models/НЕТ-ТАКОЙ").status_code, 404)

    def test_manual_key_moves_the_item(self):
        """Ручная склейка: вписали свой ключ — позиция уехала в другую карточку."""
        p = Product.objects.get(pk="p3")
        p.model_key_override = "ДРУГАЯ МОДЕЛЬ"
        p.save(update_fields=["model_key_override"])
        cards = self.client.get("/v1/models").json()
        self.assertEqual(len(cards), 2)

    def test_hidden_product_is_not_in_cards(self):
        Product.objects.filter(pk="p3").update(is_published=False)
        card = self.client.get("/v1/models").json()[0]
        self.assertEqual(card["variantCount"], 2)
        self.assertEqual([c["name"] for c in card["colors"]], ["ЧЕРНЫЙ"])


class VariantFromNameTests(TestCase):
    """1С часто не заполняет размер и цвет — они только в названии.

    Без разбора карточка собирается, но выбирать в ней нечего: у «Шорты мужские
    BMAI» было 21 позиция, 0 размеров и 0 цветов.
    """

    def test_size_is_found(self):
        self.assertEqual(size_from_name("ШОРТЫ мужские BMAI ЧЕРНЫЙ арт.FRSM007-1 р.S"), "S")
        self.assertEqual(size_from_name("BMAI EXPEDITION CORDURA ЧЕРНЫЙ 42.5р."), "42.5")
        self.assertEqual(size_from_name("Майка Anta RACING мужской Фиолетовый (2XL)"), "2XL")
        self.assertEqual(size_from_name("Трусы ANTA CHN Серый M"), "M")
        self.assertEqual(size_from_name("Бутылка для воды SIS черный, 750мл"), "")

    def test_colour_is_found(self):
        self.assertEqual(color_from_name("ЖИЛЕТ Жен. BMAI арт. FRWK006-1 цвет ЧЕРНЫЙ р. XL"),
                         "ЧЕРНЫЙ")
        self.assertEqual(color_from_name("ШОРТЫ мужские BMAI ЧЕРНЫЙ арт.FRSM007-1 р.S"),
                         "ЧЕРНЫЙ")
        self.assertEqual(color_from_name("BMAI EXPEDITION CORDURA ЧЕРНЫЙ-СЕРЫЙ 42.5р."),
                         "ЧЕРНЫЙ-СЕРЫЙ")

    def test_card_gets_sizes_from_names(self):
        """Карточка одежды собирается с размерами, даже если поля 1С пустые."""
        for size in ("S", "M", "L"):
            make(f"pn-{size}", f"ШОРТЫ мужские BMAI ЧЕРНЫЙ арт.FRSM007-1 р.{size}",
                 stock_count=3)
        card = self.client.get("/v1/models/FRSM007").json()
        self.assertEqual(card["variantCount"], 3)
        self.assertEqual(card["sizes"], ["S", "M", "L"])
        self.assertEqual([c["name"] for c in card["colors"]], ["ЧЕРНЫЙ"])
        self.assertTrue(all(v["inStock"] for v in card["colors"][0]["sizes"]))
