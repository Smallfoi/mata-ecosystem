"""Фоновые задачи каталога и сайта."""
import logging

from celery import shared_task
from django.core.cache import cache
from django.core.management import call_command

log = logging.getLogger(__name__)

# Транскод стомегабайтного ролика идёт минуты; второй запуск beat поверх первого
# скачал бы тот же файл ещё раз. Замок живёт дольше самого долгого транскода.
_LOCK = "catalog.webify_site_videos.lock"
_LOCK_TTL = 60 * 60


@shared_task(name="catalog.webify_site_videos", ignore_result=True)
def webify_site_videos():
    """Фоновые видео сайта — в web-формат, если на сайт попал исходник с камеры.

    17.11.2026 на каждом заходе на сайт качались два исходника по 86 и 105 МБ (фон
    окна входа): разовый `webify_site_videos --apply` после починки 25.09 так и не
    запустили. Теперь это делает beat сам и повторно: всё уже лёгкое — команда
    ничего не трогает, кроме недостающего постер-кадра."""
    if not cache.add(_LOCK, 1, _LOCK_TTL):
        log.info("webify_site_videos: предыдущий запуск ещё идёт")
        return
    try:
        call_command("webify_site_videos", apply=True)
    finally:
        cache.delete(_LOCK)


_IMG_LOCK = "catalog.webify_site_images.lock"
# Замок фото-задачи — короче интервала запуска (20 мин). Автодеплой перезапускает
# воркер посреди прогона, `finally` не успевает снять замок, и с часовым замком
# задача пропускала прогоны весь день частых выкладок (21.11.2026: «предыдущий
# запуск ещё идёт» при пустом воркере). Задача идемпотентна — сделанное пропускает,
# поэтому редкое наложение двух прогонов безвредно.
_IMG_LOCK_TTL = 15 * 60
# v2 (21.11.2026): команда теперь ставит и Cache-Control — один раз пройти бакет заново.
_TYPES_DONE = "catalog.fix_media_content_types.done.v2"


@shared_task(name="catalog.webify_site_images", ignore_result=True)
def webify_site_images():
    """Фото блоков сайта и баннеров в WebP (18.11.2026). Загрузка уже кладёт WebP;
    задача доводит то, что лежало раньше, и всё, что когда-то не пережалось."""
    if not cache.add(_IMG_LOCK, 1, _IMG_LOCK_TTL):
        log.info("webify_site_images: предыдущий запуск ещё идёт")
        return
    try:
        call_command("webify_site_images", apply=True)
        # Разово: старым WebP в S3 — честный Content-Type (были octet-stream). Отметка
        # на 30 дней, чтобы не перебирать бакет каждые 20 минут.
        if not cache.get(_TYPES_DONE):
            call_command("fix_media_content_types", apply=True)
            cache.set(_TYPES_DONE, 1, 30 * 24 * 3600)
    finally:
        cache.delete(_IMG_LOCK)
