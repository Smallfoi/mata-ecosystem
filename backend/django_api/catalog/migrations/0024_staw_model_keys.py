"""Склеить цвета STAW в одну карточку (D-131).

У STAW цвет приклеен к коду модели без дефиса (26SADT003 + 1850), и прежнее
правило «отрезать -1» его не видело: каждый цвет был отдельной карточкой, 67
позиций — 67 карточек. Теперь модель — первые 9 знаков (catalog/naming.py).

Ключ пересчитывается сам при следующей выгрузке из 1С, но к нему привязаны фото
карточек и история продаж: их ключ — старый, полный артикул. Переносим всё
вместе, иначе фото STAW пропали бы с витрины. Ручную склейку
(`model_key_override`) не трогаем — она сильнее автоматики.
"""
import re

from django.db import migrations

STAW = re.compile(r"^(\d{2}SA[A-Z]{2}\d{3})[A-Z0-9]{2,6}$")


def _base(key: str) -> str:
    found = STAW.match((key or "").strip().upper())
    return found.group(1) if found else ""


def forward(apps, schema_editor):
    Product = apps.get_model("catalog", "Product")
    ProductPhoto = apps.get_model("catalog", "ProductPhoto")
    SaleLine = apps.get_model("analytics", "SaleLine")

    products = []
    for product in Product.objects.filter(article__regex=r"^[0-9]{2}SA"):
        base = _base(product.article)
        if base and product.model_key != base:
            product.model_key = base
            products.append(product)
    Product.objects.bulk_update(products, ["model_key"], batch_size=500)

    # Фото: порядок внутри цвета сохраняется — у разных цветов разные строки color.
    for model in (ProductPhoto, SaleLine):
        rows = []
        for row in model.objects.filter(model_key__regex=r"^[0-9]{2}SA"):
            base = _base(row.model_key)
            if base and row.model_key != base:
                row.model_key = base
                rows.append(row)
        model.objects.bulk_update(rows, ["model_key"], batch_size=500)


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0023_product_barcodes"),
        ("analytics", "0003_backfill_sale_lines"),
    ]

    operations = [
        migrations.RunPython(forward, migrations.RunPython.noop),
    ]
