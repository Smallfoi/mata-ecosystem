"""Вкладки витрины (D-132): раскладка категорий 1С, дубли — одной кнопкой,
пустое не показываем, обмен с 1С раскладку не стирает."""
from importlib import import_module

from django.apps import apps
from django.test import TestCase

from catalog.models import Category, Product, ShowcaseGroup, ShowcaseTab
from integrations.onec import import_categories

layout = import_module("catalog.migrations.0027_showcase_layout").forward


def _cat(cid, name):
    return Category.objects.create(id=cid, name=name)


def _product(pid, cat, model=None, **kw):
    return Product.objects.create(id=pid, name=pid, category_id=cat, price=1, model_key=model or pid, **kw)


class LayoutMigrationTests(TestCase):
    def test_categories_land_in_groups_and_demo_ones_go(self):
        _cat("all", "Все")
        _cat("g-sneak", "Кроссовки")
        _cat("g-tee", "Футболка")
        _cat("g-tank", "Майка")
        _cat("g-sl1", "Тапочки")
        _cat("g-sl2", "Тапочки")
        _cat("g-new", "Самокаты")
        _cat("tshirts", "Футболки")
        _cat("shoes", "Кроссовки")   # демо: удаляется, а не попадает в «Кроссовки»
        Category.objects.filter(pk__in=["g-sneak", "g-tee", "g-tank", "g-sl1", "g-sl2", "g-new", "all"]) \
            .update(showcase_group=None)

        # Миграция 0027 уже прошла на пустой базе — проверяем её функцию повторно.
        layout(apps, None)

        group = dict(Category.objects.values_list("pk", "showcase_group"))
        self.assertEqual(group["g-sneak"], "sneakers")
        self.assertEqual(group["g-tee"], "tees")
        self.assertEqual(group["g-tank"], "tees")
        self.assertEqual(group["g-sl1"], "slippers")
        self.assertEqual(group["g-sl2"], "slippers")
        self.assertIsNone(group["g-new"])
        self.assertIsNone(group["all"])
        self.assertNotIn("tshirts", group)
        self.assertNotIn("shoes", group)
        self.assertEqual(list(ShowcaseTab.objects.values_list("pk", flat=True)),
                         ["shoes", "clothing", "accessories", "nutrition"])

    def test_demo_category_with_1c_goods_is_kept(self):
        _cat("shoes", "Кроссовки")
        _product("real", "shoes", external_id="guid-1")
        layout(apps, None)
        self.assertTrue(Category.objects.filter(pk="shoes").exists())


class ShowcaseApiTests(TestCase):
    def setUp(self):
        _cat("all", "Все")
        for cid, name, gid in [("c-sneak", "Кроссовки", "sneakers"), ("c-spike", "Шиповки", "spikes"),
                               ("c-tee", "Футболка", "tees"), ("c-tank", "Майка", "tees"),
                               ("c-gel", "Гели", "gels"), ("c-new", "Самокаты", None)]:
            Category.objects.create(id=cid, name=name, showcase_group_id=gid)
        # Две позиции одной модели — одна карточка.
        _product("s1", "c-sneak", model="M1")
        _product("s2", "c-sneak", model="M1")
        _product("s3", "c-sneak", model="M2")
        _product("t1", "c-tee")
        _product("t2", "c-tank")
        _product("hidden", "c-gel", is_published=False)
        _product("n1", "c-new")

    def test_tabs_groups_and_card_counts(self):
        data = self.client.get("/v1/showcase").json()
        self.assertEqual([t["id"] for t in data], ["shoes", "clothing"], "пустые вкладки не отдаём")
        shoes, clothing = data
        self.assertEqual(shoes["count"], 2)
        self.assertEqual([(g["id"], g["count"], g["categoryIds"]) for g in shoes["groups"]],
                         [("sneakers", 2, ["c-sneak"])], "пустые «Шиповки» не показываем")
        self.assertEqual(clothing["groups"][0]["name"], "Футболки и майки")
        self.assertEqual(sorted(clothing["groups"][0]["categoryIds"]), ["c-tank", "c-tee"])
        self.assertEqual(clothing["count"], 2)

    def test_flat_categories_hide_empty_and_keep_all_first(self):
        ids = [c["id"] for c in self.client.get("/v1/categories").json()]
        self.assertEqual(ids[0], "all", "из «Все» приложение рисует первую кнопку")
        self.assertNotIn("c-spike", ids)
        self.assertNotIn("c-gel", ids, "товар снят с витрины — категория пустая")
        self.assertEqual(ids[1:], ["c-sneak", "c-tank", "c-tee", "c-new"],
                         "порядок вкладок и групп; без группы — в конце")


class OneCKeepsLayoutTests(TestCase):
    def test_exchange_updates_name_but_not_the_group(self):
        Category.objects.create(id="guid-1", name="Футболка", showcase_group_id="tees")
        import_categories([{"id": "guid-1", "name": "Футболки", "sort": 5}])
        c = Category.objects.get(pk="guid-1")
        self.assertEqual(c.name, "Футболки")
        self.assertEqual(c.showcase_group_id, "tees")
        self.assertTrue(ShowcaseGroup.objects.filter(pk="tees").exists())
