"""Карточки моделей на витрине: один товар — много цветов и размеров (D-94).

В 1С каждый размер и цвет — отдельная позиция (склад, этикетки). Покупатель
должен видеть одну карточку и выбирать внутри, а чего нет на складе — то
недоступно. Примеры названий взяты с боевого каталога.
"""
from django.test import TestCase

from catalog.models import Product, ProductPhoto
from catalog.naming import model_base, model_key


def make(pid, name, **extra):
    data = dict(id=pid, name=name, category_id="c1", price=3990)
    data.update(extra)
    product = Product.objects.create(**data)
    product.rebuild_display_name()
    product.save(update_fields=["display_name", "model_key"])
    return product


class ModelKeyTests(TestCase):
    def test_article_comes_only_from_the_field(self):
        """Из названия артикул не берём: «… темно-синий 3.5» — это длина шорт (D-95)."""
        self.assertEqual(model_key("Шорты мужские BMAI темно-синий 3.5"),
                         "ШОРТЫ МУЖСКИЕ BMAI ТЕМНО-СИНИЙ 3.5")
        self.assertEqual(model_key("ШОРТЫ мужские BMAI ЧЕРНЫЙ арт.FRSM007-1 р.S",
                                   article="FRSM007-1"), "FRSM007")

    def test_colour_suffix_is_cut(self):
        self.assertEqual(model_base("FRWK006-1"), "FRWK006")
        self.assertEqual(model_base("FRTK-003-1"), "FRTK-003")

    def test_filled_articles_split_the_models(self):
        """«Шорты мужские BMAI» — три РАЗНЫЕ модели; их разводит поле артикула."""
        a = model_key("ШОРТЫ мужские BMAI ЧЕРНЫЙ р.S", article="FRSM007-1")
        b = model_key("ШОРТЫ мужские BMAI СЕРЫЙ р.M", article="FRSM009-2")
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


class VariantsComeFromFieldsOnlyTests(TestCase):
    """Размер и цвет — только из строк 1С (решение владельца 24.09.2026).

    Названия дублируют всё подряд, а строки заполняются вручную и достоверны.
    Пока строка пуста — на витрине выбора нет; заполнили — появился сам.
    """

    def test_empty_fields_give_no_choice(self):
        make("pf-1", "ШОРТЫ мужские BMAI ЧЕРНЫЙ р.S", article="FRSM007-1", stock_count=3)
        card = self.client.get("/v1/models/FRSM007").json()
        self.assertEqual(card["sizes"], [], "размер вытянули из названия — так нельзя")
        self.assertEqual([c["name"] for c in card["colors"]], [""])

    def test_filled_fields_appear_on_the_storefront(self):
        make("pf-2", "ШОРТЫ мужские BMAI ЧЕРНЫЙ р.M", article="FRSM007-1",
             sizes=["M"], colors=["ЧЕРНЫЙ"], stock_count=3)
        card = self.client.get("/v1/models/FRSM007").json()
        self.assertEqual(card["sizes"], ["M"])
        self.assertEqual([c["name"] for c in card["colors"]], ["ЧЕРНЫЙ"])


class ModelSearchTests(TestCase):
    """Поиск обязан выглядеть как витрина: одна карточка, а не шесть размеров."""

    def setUp(self):
        make("s1", "BMAI EXPEDITION CORDURA ЧЕРНЫЙ 41р.", sizes=["41"],
             colors=["ЧЕРНЫЙ"], brand="BMAI", stock_count=5)
        make("s2", "BMAI EXPEDITION CORDURA ЧЕРНЫЙ 42р.", sizes=["42"],
             colors=["ЧЕРНЫЙ"], brand="BMAI", stock_count=5)
        make("s3", "ФУТБОЛКА женская MATA БЕЛЫЙ р.S", sizes=["S"],
             colors=["БЕЛЫЙ"], article="FRTW001", stock_count=1)

    def test_query_groups_variants_into_one_card(self):
        cards = self.client.get("/v1/models?q=expedition").json()
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["variantCount"], 2)

    def test_query_filters_out_the_rest(self):
        cards = self.client.get("/v1/models?q=футболка").json()
        self.assertEqual([c["variantCount"] for c in cards], [1])

    def test_article_is_searchable(self):
        cards = self.client.get("/v1/models?q=FRTW001").json()
        self.assertEqual(len(cards), 1)

    def test_empty_query_is_the_whole_storefront(self):
        self.assertEqual(len(self.client.get("/v1/models?q=").json()), 2)


class ModelReviewTests(TestCase):
    """Отзыв покупатель пишет на МОДЕЛЬ, а купил один размер (D-94).

    Иначе отзыв о кроссовках видят только те, кто смотрит ровно 42-й размер, и
    «оставить отзыв» не предлагается никому: куплена позиция, открыта модель.
    """

    def setUp(self):
        make("r1", "BMAI EXPEDITION CORDURA ЧЕРНЫЙ 41р.", sizes=["41"],
             colors=["ЧЕРНЫЙ"], stock_count=5)
        make("r2", "BMAI EXPEDITION CORDURA ЧЕРНЫЙ 42р.", sizes=["42"],
             colors=["ЧЕРНЫЙ"], stock_count=5)
        self.key = Product.objects.get(pk="r1").shop_model_key
        r = self.client.post(
            "/v1/auth/phone/verify",
            data='{"phone": "+79990004420", "code": "1234"}',
            content_type="application/json",
        )
        self.token = r.json()["token"]
        self.uid = r.json()["user"]["id"]

    def _buy(self, pid):
        from orders.models import Order
        Order.objects.create(
            user_id=self.uid, order_id=f"SS-R-{pid}", total=4990, status="paid",
            payment_status="paid",
            payload={"items": [{"productId": pid, "productName": "Кроссовки",
                                "price": 4990, "quantity": 1}]},
        )

    def _post_review(self, pid, rating=5, text="Хорошие"):
        return self.client.post(
            f"/v1/products/{pid}/reviews",
            data=f'{{"rating": {rating}, "text": "{text}"}}',
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.token}",
        )

    def test_review_on_the_model_key_is_allowed_after_buying_a_size(self):
        self._buy("r2")
        r = self._post_review(self.key)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["rating"], 5.0)

    def test_without_a_purchase_it_is_still_forbidden(self):
        self.assertEqual(self._post_review(self.key).status_code, 403)

    def test_review_is_visible_on_the_other_size(self):
        self._buy("r1")
        self._post_review(self.key)
        body = self.client.get("/v1/products/r2/reviews").json()
        self.assertEqual(len(body["reviews"]), 1)
        self.assertEqual(body["reviewCount"], 1)

    def test_rating_shows_up_on_the_model_card(self):
        self._buy("r1")
        self._post_review(self.key, rating=4)
        card = self.client.get(f"/v1/models/{self.key}").json()
        self.assertEqual(card["rating"], 4.0)
        self.assertEqual(card["reviewCount"], 1, "один отзыв не должен посчитаться дважды")

    def test_second_review_on_another_size_updates_the_same_one(self):
        self._buy("r1")
        self._post_review(self.key, rating=5)
        self._post_review("r2", rating=3)
        card = self.client.get(f"/v1/models/{self.key}").json()
        self.assertEqual(card["reviewCount"], 1)
        self.assertEqual(card["rating"], 3.0)

    def test_unknown_key_is_404(self):
        self.assertEqual(self.client.get("/v1/products/нет-такого/reviews").status_code, 404)

class ModelPhotoTests(TestCase):
    """Галерея витрины: снимки привязаны к модели и ЦВЕТУ (D-99).

    Выбрал чёрный — видишь чёрный. Снимки лежат не на складской позиции, потому
    что от размера они не зависят: иначе одно и то же заливали бы по разу на
    каждый размер.
    """

    def setUp(self):
        make("ph1", "BMAI EXPEDITION ЧЕРНЫЙ 41р.", sizes=["41"], colors=["ЧЕРНЫЙ"],
             stock_count=5)
        make("ph2", "BMAI EXPEDITION ЧЕРНЫЙ 42р.", sizes=["42"], colors=["ЧЕРНЫЙ"],
             stock_count=5)
        make("ph3", "BMAI EXPEDITION МЯТНЫЙ 41р.", sizes=["41"], colors=["МЯТНЫЙ"],
             stock_count=5)
        self.key = Product.objects.get(pk="ph1").shop_model_key

    def _photo(self, color, order=0, name="a"):
        return ProductPhoto.objects.create(
            model_key=self.key, color=color, order=order,
            image=f"uploads/photos/{name}.webp", thumb=f"uploads/photos/{name}-t.webp")

    def _card(self):
        return self.client.get(f"/v1/models/{self.key}").json()

    def test_photos_land_on_their_colour(self):
        self._photo("ЧЕРНЫЙ", 0, "black1")
        self._photo("ЧЕРНЫЙ", 1, "black2")
        self._photo("МЯТНЫЙ", 0, "mint1")
        colors = {c["name"]: c for c in self._card()["colors"]}
        self.assertEqual(len(colors["ЧЕРНЫЙ"]["photos"]), 2)
        self.assertEqual(len(colors["МЯТНЫЙ"]["photos"]), 1)
        self.assertIn("mint1", colors["МЯТНЫЙ"]["photos"][0]["url"])

    def test_photos_keep_their_order(self):
        self._photo("ЧЕРНЫЙ", 1, "second")
        self._photo("ЧЕРНЫЙ", 0, "first")
        black = next(c for c in self._card()["colors"] if c["name"] == "ЧЕРНЫЙ")
        self.assertIn("first", black["photos"][0]["url"], "обложка не первая")

    def test_cover_and_thumb_come_from_the_first_photo(self):
        self._photo("ЧЕРНЫЙ", 0, "cover")
        card = self._card()
        self.assertIn("cover.webp", card["imageUrl"])
        self.assertIn("cover-t.webp", card["thumbUrl"], "в ленту уходит полноразмерный снимок")

    def test_colour_without_photos_stays_empty(self):
        """У мятного снимков нет — чужие подставлять нельзя."""
        self._photo("ЧЕРНЫЙ", 0, "black1")
        mint = next(c for c in self._card()["colors"] if c["name"] == "МЯТНЫЙ")
        self.assertEqual(mint["photos"], [])

    def test_photos_without_colour_are_shared(self):
        """Цвет в 1С ещё не заполнен — снимки модели показываем всем цветам."""
        self._photo("", 0, "common")
        for color in self._card()["colors"]:
            self.assertEqual(len(color["photos"]), 1, color["name"])

    def test_list_gives_the_same_gallery(self):
        self._photo("ЧЕРНЫЙ", 0, "black1")
        card = self.client.get("/v1/models").json()[0]
        black = next(c for c in card["colors"] if c["name"] == "ЧЕРНЫЙ")
        self.assertEqual(len(black["photos"]), 1)

    def test_one_query_for_the_whole_list(self):
        """Две сотни карточек не должны превратиться в две сотни запросов."""
        for i in range(3):
            self._photo("ЧЕРНЫЙ", i, f"b{i}")
        with self.assertNumQueries(2):        # товары + фото
            self.client.get("/v1/models")

    def test_old_position_photo_still_works(self):
        """Пока галереи нет, показываем прежнее фото позиции — витрина не пустеет."""
        Product.objects.filter(pk="ph1").update(image_urls=["shoe.jpg"])
        card = self._card()
        self.assertIn("shoe.jpg", card["imageUrl"])
