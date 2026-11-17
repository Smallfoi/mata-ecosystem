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
