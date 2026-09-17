"""Удаление треков, которые больше не нужны (D-60).

Трек живёт ровно столько, сколько нужно, чтобы разобрать спор о накрутке.
Дальше он — просто карта передвижений человека, и хранить её мы не будем.

Исключение (D-86): у кого включена «Резервная копия треков» (opt-in, по согласию),
трек хранится долговременно, чтобы маршрут пережил переустановку/смену телефона —
такие треки задача не трогает.
"""
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from league.models import RunnerProfile
from trails.models import PendingTrack

TRACK_RETENTION_DAYS = 14


@shared_task(name="trails.cleanup_tracks", ignore_result=True)
def cleanup_tracks():
    edge = timezone.now() - timedelta(days=TRACK_RETENTION_DAYS)
    # Пользователи с включённым бэкапом (D-86): их треки не удаляем.
    backup_uids = set(
        RunnerProfile.objects.filter(track_backup=True).values_list("user_id", flat=True)
    )
    stale = PendingTrack.objects.filter(received_at__lt=edge).exclude(user_id__in=backup_uids)
    removed, _ = stale.delete()
    if removed:
        print(f"Тропы: удалено треков старше {TRACK_RETENTION_DAYS} дней — {removed}.")
    return removed
