"""Фоновый прогон пакета фотопайплайна (Celery). Тяжёлые вызовы ИИ — не в веб-запросе."""
from celery import shared_task

from productmedia import service
from productmedia.models import PhotoBatch


@shared_task
def process_batch(batch_id):
    """Прогнать все задания пакета в очереди. Возвращает сводку по статусам."""
    batch = PhotoBatch.objects.filter(pk=batch_id).first()
    if batch is None:
        return {"error": "пакет %s не найден" % batch_id}
    return service.run_batch(batch)
