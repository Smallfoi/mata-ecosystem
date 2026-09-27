"""Старые предпросмотры photo_test: «Готово» без выкладки → «Отклонено».

До экранов проверки (#792) предпросмотр ставил заданию статус «done», ничего не выкладывая
на витрину. После #792 «done» означает «На витрине», и эти тестовые снимки (лонгслив Staw,
привязанный к кроссовкам BMAI) показывались во вкладке «На витрине», хотя на витрине их нет.
Признак: status=done, но attached_at пуст (выкладка его всегда ставит).
"""
from django.db import migrations

NOTE = "тестовый предпросмотр (до экрана проверки) — на витрину не выкладывался"


def forward(apps, schema_editor):
    PhotoJob = apps.get_model("productmedia", "PhotoJob")
    PhotoJob.objects.filter(status="done", attached_at__isnull=True).update(
        status="rejected", note=NOTE)


class Migration(migrations.Migration):

    dependencies = [
        ("productmedia", "0003_photojob_usage_photodetail_photoprompt_and_more"),
    ]

    operations = [
        migrations.RunPython(forward, migrations.RunPython.noop),
    ]
