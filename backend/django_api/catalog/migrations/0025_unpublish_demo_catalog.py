"""Снять с витрины демо-товары первых дней разработки (17.11.2026, владелец).

16 выдуманных товаров из `seed_catalog` («Кроссовки Air Runner X1», бренды
UrbanFit/RunTech/ProGear/SportStore) стояли на проде рядом с настоящим каталогом
из 1С — с фото и ценами, их можно было заказать.

Снимаем публикацию, а не удаляем: на них могут ссылаться старые тестовые заказы
и отзывы, а вернуть флаг можно одной галочкой в админке. Товар считается демо,
только если совпадает всё сразу: id из сида, его название, нет идентификатора 1С
и артикула — настоящий товар под это не попадёт, даже если id случайно совпадёт.
"""
from django.db import migrations

DEMO = (
    ("1", "Беговая футболка Pro Dry"),
    ("2", "Худи Essential Fleece"),
    ("3", "Кроссовки Air Runner X1"),
    ("4", "Спортивные брюки Taper Fit"),
    ("5", "Ветровка Shield Pro"),
    ("6", "Компрессионная футболка"),
    ("7", "Рюкзак Training Pack 25L"),
    ("8", "Зимняя куртка Thermo Pro"),
    ("9", "Кроссовки Cloud Foam"),
    ("10", "Кроссовки Street Pro"),
    ("11", "Лонгслив Active Long"),
    ("12", "Футболка Statement"),
    ("13", "Шорты Denim Flex"),
    ("14", "Куртка Shearling Winter"),
    ("15", "Бутылка Thermo 750 мл"),
    ("16", "Рюкзак Urban Daypack"),
)


def demo_products(Product):
    names = dict(DEMO)
    rows = Product.objects.filter(pk__in=names, external_id__isnull=True, article="")
    return [p for p in rows if names[p.pk] == p.name]


def forward(apps, schema_editor):
    Product = apps.get_model("catalog", "Product")
    ids = [p.pk for p in demo_products(Product)]
    Product.objects.filter(pk__in=ids).update(is_published=False)


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0024_staw_model_keys"),
    ]

    operations = [
        migrations.RunPython(forward, migrations.RunPython.noop),
    ]
