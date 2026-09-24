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


def run_job(job, attach=True):
    """Одно задание: исходник → мастер (ИИ) → webp → привязка к карточке.

    `attach=False` — прогнать ИИ и получить мастер/webp на задании, но НЕ трогать витрину
    (режим предпросмотра: посмотреть результат, ничего не выкладывая). Идемпотентно по смыслу:
    skipped/без товара — ничего не делаем; сбой ИИ/сети → failed с текстом, карточка не меняется.
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

        # В галерею витрины кладём МАСТЕР — хранилище само сделает webp 1600 и миниатюру 400.
        # attach=False (предпросмотр) — витрину не трогаем, мастер/webp остаются на задании.
        attached = _attach(job, master) if attach else False

        job.status = PhotoJob.STATUS_DONE
        job.error = ""
        if attached:
            job.attached_at = timezone.now()
        job.save()
    except providers.ImageProviderError as e:
        job.status = PhotoJob.STATUS_FAILED
        job.error = str(e)[:2000]
        job.save(update_fields=["status", "error", "updated_at"])
    except ValueError as e:                      # у цвета уже 6 фото (ProductPhoto.MAX_PER_COLOR)
        job.status = PhotoJob.STATUS_FAILED
        job.error = str(e)[:2000]
        job.save(update_fields=["status", "error", "updated_at"])
    except Exception as e:                       # noqa: BLE001 — фиксируем любой сбой в задании
        job.status = PhotoJob.STATUS_FAILED
        job.error = ("непредвиденная ошибка: %s" % e)[:2000]
        job.save(update_fields=["status", "error", "updated_at"])
    return job


def _attach(job, data_bytes):
    """Прикрепить готовый снимок к галерее витрины (catalog.ProductPhoto). Возвращает True.

    Единое хранилище фото — у каталога (модель + ЦВЕТ, до 6, галерея меняется при
    переключении цвета; D-99). Отдаём мастер-байты, а витринный webp 1600, миниатюру 400,
    имена и порядок делает catalog.photos.attach. attach_as="main" → обложка (order 0),
    иначе снимок встаёт следующим. ValueError (у цвета уже 6) пробрасывается — run_job
    поставит заданию failed с текстом. Ключ модели и цвет берём как их читает витрина.
    """
    from catalog import photos as photolib

    # Товар в задании пришёл из intake через .only("id","article") — перечитываем полностью,
    # чтобы точно получить цвет и ключ модели (иначе цвет уедет пустым).
    product = Product.objects.get(pk=job.product_id)
    model_key = product.shop_model_key or str(product.id)
    colors = product.colors or []
    color = colors[0] if colors else ""
    photolib.attach(model_key, color=color, data=data_bytes,
                    first=(job.attach_as == PhotoJob.ATTACH_MAIN))
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
