"""Оркестрация фотопайплайна: приём партии по артикулам → ИИ → проверка → витрина.

Цикл задания:
  В очереди → Генерируется → НА ПРОВЕРКЕ → (Принять) На витрине
                                         → (Переделать с замечанием) снова В очереди
                                         → (Отклонить) Отклонено
На витрину без решения человека не попадает ничего: ИИ иногда выдумывает надписи и
переносит принт на другую сторону, это ловит только глаз.

Всё по одному заданию — так проще тестировать и логировать. Фоновый прогон пакета и
повторы идут через Celery (tasks). Любой сбой ИИ/сети фиксируется в самом задании
(status=failed, текст в error) и НЕ роняет воркер.
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
      attach_as — "main"|"gallery" (по умолчанию главное фото),
      text      — текст принта словами, необязательно.
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
            text=(it.get("text") or "").strip()[:300],
            status=PhotoJob.STATUS_PENDING if product else PhotoJob.STATUS_SKIPPED,
            error="" if product else "артикул не найден в каталоге",
        )
        job.source.save(it.get("filename") or "source.bin",
                        ContentFile(bytes(content)), save=False)
        job.save()
        jobs.append(job)
    return jobs


def _fail(job, text):
    job.status = PhotoJob.STATUS_FAILED
    job.error = str(text)[:2000]
    job.save(update_fields=["status", "error", "updated_at"])


def generate(job, note=None):
    """Исходник → мастер (ИИ) → webp на задании → статус «На проверке». Витрину НЕ трогает.

    note — замечание к этой попытке (по умолчанию берётся последнее job.note, его ставит
    «Переделать»). Сбой ИИ/сети → «Ошибка» с текстом.
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
        # Открываем заново: при повторной генерации файл мог остаться закрытым после
        # прошлого чтения, и read() упал бы на «I/O operation on closed file».
        with job.source.open("rb") as f:
            source_bytes = f.read()

        master = processing.process(source_bytes, track=job.track, text=job.text,
                                    note=job.note if note is None else note)
        webp = images.make_webp(master)

        base = _safe_base(job)
        job.master.save("%s.png" % base, ContentFile(master), save=False)
        job.webp.save("%s.webp" % base, ContentFile(webp), save=False)

        job.status = PhotoJob.STATUS_REVIEW
        job.error = ""
        job.attempts = (job.attempts or 0) + 1
        job.save()
    except providers.ImageProviderError as e:
        _fail(job, e)
    except Exception as e:                       # noqa: BLE001 — фиксируем любой сбой в задании
        _fail(job, "непредвиденная ошибка: %s" % e)
    return job


def approve(job, user=None):
    """«Принять»: выложить результат в галерею витрины → «На витрине».

    Возвращает текст ошибки или "" при успехе. Если у цвета уже 6 снимков — задание
    остаётся «На проверке» с понятной ошибкой: человек освободит место и примет снова.
    """
    if job.status != PhotoJob.STATUS_REVIEW or not job.master:
        return "снимок не на проверке"
    try:
        with job.master.open("rb") as f:
            master = f.read()
        _attach(job, master)
    except ValueError as e:                      # у цвета уже 6 фото (MAX_PER_COLOR)
        job.error = str(e)[:2000]
        job.save(update_fields=["error", "updated_at"])
        return job.error
    job.status = PhotoJob.STATUS_DONE
    job.error = ""
    job.attached_at = timezone.now()
    job.reviewed_by = user if getattr(user, "pk", None) else None
    job.reviewed_at = timezone.now()
    job.save()
    return ""


def redo(job, note="", user=None):
    """«Переделать»: запомнить замечание и вернуть задание в очередь.

    Саму генерацию запускает вызывающий (фоновая задача tasks.regenerate_job): запрос
    к ИИ идёт до ~2 минут, держать на нём веб-запрос нельзя.
    """
    job.note = (note or "").strip()[:2000]
    job.status = PhotoJob.STATUS_PENDING
    job.error = ""
    job.reviewed_by = user if getattr(user, "pk", None) else None
    job.reviewed_at = timezone.now()
    job.save()
    return job


def reject(job, note="", user=None):
    """«Отклонить»: брак, на витрину не идёт. Причина сохраняется для статистики."""
    job.note = (note or "").strip()[:2000]
    job.status = PhotoJob.STATUS_REJECTED
    job.reviewed_by = user if getattr(user, "pk", None) else None
    job.reviewed_at = timezone.now()
    job.save()
    return job


def run_job(job, attach=True, text=""):
    """Сгенерировать и сразу принять (для ручной команды photo_test).

    attach=False — только генерация: задание остаётся «На проверке» (предпросмотр).
    """
    if text:
        job.text = text.strip()[:300]
        job.save(update_fields=["text", "updated_at"])
    generate(job)
    if attach and job.status == PhotoJob.STATUS_REVIEW:
        err = approve(job)
        if err:
            _fail(job, err)
    return job


def _attach(job, data_bytes):
    """Прикрепить снимок к галерее витрины (catalog.ProductPhoto).

    Единое хранилище фото — у каталога (модель + ЦВЕТ, до 6, галерея меняется при
    переключении цвета; D-99). Отдаём мастер-байты, а витринный webp 1600, миниатюру 400,
    имена и порядок делает catalog.photos.attach. attach_as="main" → обложка (order 0),
    иначе снимок встаёт следующим. ValueError (у цвета уже 6) пробрасывается.
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
    """Сгенерировать все задания пакета «в очереди» → «На проверке». На витрину не выкладывает."""
    summary = {"review": 0, "failed": 0, "skipped": 0}
    for job in batch.jobs.filter(status=PhotoJob.STATUS_PENDING):
        generate(job)
        if job.status == PhotoJob.STATUS_REVIEW:
            summary["review"] += 1
        elif job.status == PhotoJob.STATUS_FAILED:
            summary["failed"] += 1
        elif job.status == PhotoJob.STATUS_SKIPPED:
            summary["skipped"] += 1
    return summary


def counts(batch):
    """Сводка пакета по статусам для экрана: {status: n}."""
    out = {code: 0 for code, _ in PhotoJob.STATUS_CHOICES}
    for status in batch.jobs.values_list("status", flat=True):
        out[status] = out.get(status, 0) + 1
    return out
