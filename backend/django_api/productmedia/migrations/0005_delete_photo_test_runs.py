"""Удалить тестовые прогоны фотопайплайна (просьба владельца 27.09).

Удаляем ТОЛЬКО партии, созданные командой photo_test (note="photo_test"): это технические
прогоны при настройке релея и промтов — лонгслив и майки Staw, привязанные к кроссовкам BMAI
XRML222. Вместе с записями удаляем их файлы в хранилище (исходники, мастера, webp, крупные
планы): иначе они так и лежали бы в S3 по публичным ссылкам. Витрину (catalog.ProductPhoto)
не трогаем — тестовые снимки на неё не выкладывались (проверено по /v1/models).
Партии, загруженные через экран «Фотопайплайн», не трогаем.
"""
from django.db import migrations

TEST_NOTE = "photo_test"


def _drop_file(field):
    """Удалить файл из хранилища; сбой хранилища не должен ронять миграцию."""
    try:
        if field and field.name:
            field.delete(save=False)
    except Exception:                                    # noqa: BLE001
        pass


def forward(apps, schema_editor):
    PhotoBatch = apps.get_model("productmedia", "PhotoBatch")
    PhotoJob = apps.get_model("productmedia", "PhotoJob")
    PhotoDetail = apps.get_model("productmedia", "PhotoDetail")

    batches = list(PhotoBatch.objects.filter(note=TEST_NOTE).values_list("pk", flat=True))
    if not batches:
        return
    for job in PhotoJob.objects.filter(batch_id__in=batches):
        for field in (job.source, job.master, job.webp):
            _drop_file(field)
    for row in PhotoDetail.objects.filter(batch_id__in=batches):
        _drop_file(row.image)
    PhotoBatch.objects.filter(pk__in=batches).delete()   # задания и крупные планы — каскадом


class Migration(migrations.Migration):

    dependencies = [
        ("productmedia", "0004_unattached_done_to_rejected"),
    ]

    operations = [
        migrations.RunPython(forward, migrations.RunPython.noop),
    ]
