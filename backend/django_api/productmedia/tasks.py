"""Фоновые задачи фотопайплайна (Celery). Тяжёлые вызовы ИИ — не в веб-запросе."""
from celery import shared_task

from productmedia import service
from productmedia.models import PhotoBatch, PhotoJob


@shared_task
def process_batch(batch_id):
    """Сгенерировать все задания пакета в очереди → «На проверке». Сводка по статусам."""
    batch = PhotoBatch.objects.filter(pk=batch_id).first()
    if batch is None:
        return {"error": "пакет %s не найден" % batch_id}
    return service.run_batch(batch)


@shared_task
def regenerate_job(job_id):
    """Повторная генерация одного задания («Переделать» / «Повторить» после ошибки)."""
    job = PhotoJob.objects.filter(pk=job_id).first()
    if job is None:
        return {"error": "задание %s не найдено" % job_id}
    service.generate(job)
    return {"status": job.status}
