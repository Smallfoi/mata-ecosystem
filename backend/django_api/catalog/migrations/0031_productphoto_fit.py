"""Разметка снимков витрины: где на кадре товар, цвет фона, пропорции (27.11.2026).

Новые снимки размечаются при загрузке (catalog.photos.store_photo); здесь —
уже залитые. Меряем по миниатюре (400 px): для рамки товара этого достаточно,
а качать полноразмерные 1600 px с хранилища на каждый снимок незачем.
Снимок, который не прочитался, остаётся без разметки — клиент покажет его
целиком без центровки, миграция из-за него не падает.
"""
from django.db import migrations, models


def measure_existing(apps, schema_editor):
    from productmedia.images import measure

    ProductPhoto = apps.get_model("catalog", "ProductPhoto")
    for photo in ProductPhoto.objects.filter(fit={}).iterator():
        src = photo.thumb or photo.image
        if not src:
            continue
        try:
            src.open("rb")
            try:
                data = src.read()
            finally:
                src.close()
            photo.fit = measure(data)
        except Exception:  # noqa: BLE001 — один битый файл не останавливает остальные
            continue
        photo.save(update_fields=["fit"])


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0030_content_fixes_2026_11_26"),
    ]

    operations = [
        migrations.AddField(
            model_name="productphoto",
            name="fit",
            field=models.JSONField(blank=True, default=dict, verbose_name="Разметка снимка"),
        ),
        migrations.RunPython(measure_existing, migrations.RunPython.noop),
    ]
