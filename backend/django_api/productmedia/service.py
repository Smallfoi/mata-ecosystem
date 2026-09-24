"""Оркестрация фотопайплайна: приём партии по артикулам → ИИ → webp → карточка.

Всё синхронно и по одному заданию — так проще тестировать и логировать. Фоновый прогон
пакета вызывает эти же функции из Celery-задачи (tasks.process_batch). Любой сбой ИИ/сети
фиксируется в самом задании (status=failed, текст в error) и НЕ роняет воркер: например
403 с российского IP отметится в задании, остальные задания пакета продолжатся.
"""
import re

from django.core.files.base import ContentFile
from django.utils import timezone

from catalog.models import Product
from productmedia import images, processing, providers
from productmedia.matching import _norm
from productmedia.models import PhotoJob


def _safe_base(job):
    """Безопасная основа имени файла из артикула (или id, если артикула нет)."""
    base = re.sub(r"[^A-Za-z0-9._-]+", "-", (job.article or "").strip()) or str(job.pk or "job")
    return base[:60]


def intake(batch, items):
    """Создать задания пакета из партии исходников.

    items: список dict с ключами:
      article   — артикул (имя папки),
      content   — bytes или файловый объект с .read(),
      filename  — имя исходника (для хранения), необязательно,
      attach_as — "main"|"gallery" (по умолчанию главное фото).
    Привязка к товару по нормализованному артикулу (Вариант А). Нет товара → статус
    skipped (исходник всё равно сохраняем, ничего не теряем). Возвращает список PhotoJob.
    """
    by_article = {}
    for p in Product.objects.exclude(article="").only("id", "article"):
        by_article.setdefault(_norm(p.article), p)

    jobs = []
    for it in items:
        article = (it.get("article") or "").strip()
        product = by_article.get(_norm(article))
        content = it["content"]
        if not isinstance(content, (bytes, bytearray)):
            content = content.read()

        job = PhotoJob(
            batch=batch, article=article, product=product, track=batch.track,
            attach_as=it.get("attach_as", PhotoJob.ATTACH_MAIN),
            status=PhotoJob.STATUS_PENDING if product else PhotoJob.STATUS_SKIPPED,
            error="" if product else "артикул не найден в каталоге",
        )
        job.source.save(it.get("filename") or "source.bin",
                        ContentFile(bytes(content)), save=False)
        job.save()
        jobs.append(job)
    return jobs


def run_job(job):
    """Одно задание: исходник → мастер (ИИ) → webp → привязка к карточке.

    Идемпотентно по смыслу: skipped/без товара — ничего не делаем; сбой ИИ/сети → failed
    с текстом ошибки, карточка не меняется.
    """
    if job.product is None:
        job.status = PhotoJob.STATUS_SKIPPED
        if not job.error:
            job.error = "артикул не найден в каталоге"
        job.save(update_fields=["status", "error", "updated_at"])
        return job

    job.status = PhotoJob.STATUS_PROCESSING
    job.save(update_fields=["status", "updated_at"])
    try:
        source_bytes = job.source.read()
        job.source.close()

        master = processing.process(source_bytes, track=job.track)
        webp = images.make_webp(master)

        base = _safe_base(job)
        job.master.save("%s.png" % base, ContentFile(master), save=False)
        job.webp.save("%s.webp" % base, ContentFile(webp), save=False)

        attached = _attach(job, webp, base)

        job.status = PhotoJob.STATUS_DONE
        job.error = ""
        if attached:
            job.attached_at = timezone.now()
        job.save()
    except providers.ImageProviderError as e:
        job.status = PhotoJob.STATUS_FAILED
        job.error = str(e)[:2000]
        job.save(update_fields=["status", "error", "updated_at"])
    except Exception as e:                       # noqa: BLE001 — фиксируем любой сбой в задании
        job.status = PhotoJob.STATUS_FAILED
        job.error = ("непредвиденная ошибка: %s" % e)[:2000]
        job.save(update_fields=["status", "error", "updated_at"])
    return job


def _attach(job, webp_bytes, base):
    """Прикрепить готовый webp к карточке. Возвращает True, если реально прикрепили.

    Главное фото → product.image (тот же путь, что у ручной вкладки «Фото товаров»).
    Галерея (несколько фото на модель+ЦВЕТ, до 6, меняется при переключении цвета) поедет
    через catalog.ProductPhoto, когда она появится в main (координация с параллельной
    сессией). До тех пор webp уже сохранён на задании (job.webp), карточку НЕ трогаем, чтобы
    не плодить второе, неверное хранилище. В image_urls не пишем: это складская позиция, и
    network_image_url() всё равно режет полный S3-URL до имени файла.
    """
    if job.attach_as == PhotoJob.ATTACH_GALLERY:
        return False    # ждём catalog.ProductPhoto (модель+цвет)
    product = job.product
    product.image.save("%s.webp" % base, ContentFile(webp_bytes), save=False)
    product.save(update_fields=["image"])
    return True


def run_batch(batch):
    """Прогнать все задания пакета в статусе «в очереди». Возвращает сводку по статусам."""
    summary = {"done": 0, "failed": 0, "skipped": 0}
    for job in batch.jobs.filter(status=PhotoJob.STATUS_PENDING):
        run_job(job)
        if job.status == PhotoJob.STATUS_DONE:
            summary["done"] += 1
        elif job.status == PhotoJob.STATUS_FAILED:
            summary["failed"] += 1
        elif job.status == PhotoJob.STATUS_SKIPPED:
            summary["skipped"] += 1
    return summary
