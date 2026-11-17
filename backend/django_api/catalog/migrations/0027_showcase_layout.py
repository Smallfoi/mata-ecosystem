"""Первая раскладка категорий 1С по вкладкам витрины (D-132, владелец 17.11.2026).

Категорию находим по названию: id у категорий 1С — GUID, у dev и прода разные.
Чего нет в базе — пропускаем; появится позже — отнесут к группе в админке.
Заодно удаляем 6 демо-категорий сида (tshirts, hoodies…): их товары сняты в 0025,
а сами категории стояли на витрине дублями «Футболки»/«Футболка».
"""
from django.db import migrations

TABS = [("shoes", "Обувь"), ("clothing", "Одежда"), ("accessories", "Аксессуары"), ("nutrition", "Питание")]

GROUPS = [
    ("shoes", "sneakers", "Кроссовки", ["Кроссовки"]),
    ("shoes", "boots", "Ботинки", ["Ботинки"]),
    ("shoes", "spikes", "Шиповки", ["Шиповки"]),
    ("shoes", "slippers", "Тапочки", ["Тапочки"]),
    ("clothing", "tees", "Футболки и майки", ["Футболка", "Майка"]),
    ("clothing", "longsleeves", "Лонгсливы", ["Лонгслив"]),
    ("clothing", "jackets", "Куртки и ветровки", ["Куртка", "Ветровка", "Жилет"]),
    ("clothing", "shorts", "Шорты", ["Шорты", "Велосипедка"]),
    ("clothing", "pants", "Брюки и тайтсы", ["Брюки", "Леггинсы", "Тайтсы"]),
    ("clothing", "underwear", "Бельё", ["Трусы", "Термобелье", "Топ"]),
    ("accessories", "glasses", "Очки", ["Очки"]),
    ("accessories", "bottles", "Бутылки и термосы", ["Бутылка", "Бутылки", "Термос"]),
    ("accessories", "headwear", "Головные уборы", ["Бафф", "Шапка", "Бейсболка"]),
    ("accessories", "socks", "Носки", ["Носки"]),
    ("accessories", "bags", "Сумки и рюкзаки", ["Сумка", "Рюкзак"]),
    ("accessories", "gloves", "Перчатки", ["Перчатки"]),
    ("accessories", "insoles", "Стельки", ["Стельки"]),
    ("nutrition", "gels", "Гели и изотоники", ["Гели"]),
]

DEMO_CATEGORIES = ["tshirts", "hoodies", "pants", "jackets", "shoes", "accessories"]


def forward(apps, schema_editor):
    Tab = apps.get_model("catalog", "ShowcaseTab")
    Group = apps.get_model("catalog", "ShowcaseGroup")
    Category = apps.get_model("catalog", "Category")
    Product = apps.get_model("catalog", "Product")

    # Демо-категорию удаляем, только если в ней не осталось товаров из 1С.
    for cid in DEMO_CATEGORIES:
        if not Product.objects.filter(category_id=cid, external_id__isnull=False).exists():
            Category.objects.filter(pk=cid).delete()

    tabs = {}
    for i, (tid, name) in enumerate(TABS):
        tabs[tid], _ = Tab.objects.get_or_create(pk=tid, defaults={"name": name, "sort": i * 10})
    for i, (tid, gid, name, names) in enumerate(GROUPS):
        group, _ = Group.objects.get_or_create(pk=gid, defaults={"tab": tabs[tid], "name": name, "sort": i * 10})
        lowered = {n.lower() for n in names}
        for category in Category.objects.filter(showcase_group__isnull=True).exclude(pk="all"):
            if category.name.strip().lower() in lowered:
                category.showcase_group = group
                category.save(update_fields=["showcase_group"])


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0026_showcase_tabs"),
    ]

    operations = [
        migrations.RunPython(forward, migrations.RunPython.noop),
    ]
