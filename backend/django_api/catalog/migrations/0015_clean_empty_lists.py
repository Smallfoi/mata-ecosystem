"""Разовая чистка: пустые размеры, цвета и фото, приехавшие из 1С как [null].

1С заводит размер и цвет у каждой позиции, но пока большинство карточек не заполнено —
приходил список с одним пустым значением. На витрине это пустая «плашка» размера.
Приём теперь чистит такие значения сам (integrations/onec.py), а миграция приводит в
порядок уже сохранённое, чтобы не ждать следующей выгрузки.
"""
from django.db import migrations

EMPTY = {"", "none", "null", "не указан", "не указано", "-", "—"}


def _clean(value):
    if not isinstance(value, list):
        return [], False
    out = []
    for item in value:
        if item is None:
            continue
        text = str(item).strip()
        if not text or text.lower() in EMPTY:
            continue
        if text not in out:
            out.append(text[:80])
    return out, out != value


def clean_lists(apps, schema_editor):
    Product = apps.get_model("catalog", "Product")
    changed = []
    for product in Product.objects.all().only("id", "sizes", "colors", "image_urls").iterator():
        touched = False
        for field in ("sizes", "colors", "image_urls"):
            cleaned, differs = _clean(getattr(product, field))
            if differs:
                setattr(product, field, cleaned)
                touched = True
        if touched:
            changed.append(product)
        if len(changed) >= 500:
            Product.objects.bulk_update(changed, ["sizes", "colors", "image_urls"])
            changed = []
    if changed:
        Product.objects.bulk_update(changed, ["sizes", "colors", "image_urls"])


class Migration(migrations.Migration):

    dependencies = [("catalog", "0014_parcel_dimensions")]

    # Назад не откатываем: восстанавливать пустые значения незачем.
    operations = [migrations.RunPython(clean_lists, migrations.RunPython.noop)]
