# -*- coding: utf-8 -*-
"""Сжать фоновые видео сайта, которые уже лежат в хранилище несжатыми.

Зачем. Сжатие при загрузке работало только с локальным диском: на проде хранилище
облачное, и ролик уходил на сайт как есть — 100 МБ прямо с камеры. Окно входа
«жёстко тормозило у всех» (владелец, 25.09.2026). Загрузку починили, но ссылки на
тяжёлые исходники уже прописаны в контенте сайта — эта команда переделывает их
на месте, без перезаливки руками.

Что делает: находит в контенте ключи `bgvid.*`, для каждого качает файл, гонит через
тот же транскод, что и загрузка, и подменяет ссылку на web-версию.

    python manage.py webify_site_videos            # показать, что будет сделано
    python manage.py webify_site_videos --apply    # сделать
"""
from django.core.management.base import BaseCommand

from catalog.models import SiteContent


def _storage_name(url: str) -> str:
    """Имя файла в хранилище по его публичной ссылке."""
    marker = "uploads/site-video/"
    i = url.find(marker)
    return url[i:].split("?")[0] if i >= 0 else ""


class Command(BaseCommand):
    help = "Сжать уже загруженные фоновые видео сайта (bgvid.*) в web-формат"

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true",
                            help="выполнить (без флага — только показать)")
        parser.add_argument("--quality", default="web", choices=["web", "high"])

    def handle(self, *args, **opts):
        from django.core.files.storage import default_storage

        from config.admin_views import _webify_video

        rows = [c for c in SiteContent.objects.all() if c.key.startswith("bgvid.")]
        todo = []
        for row in rows:
            url = row.value or ""
            name = _storage_name(url)
            if not name or name.endswith("_web.mp4"):
                continue
            try:
                size = default_storage.size(name)
            except Exception:
                self.stdout.write(f"  {row.key}: файла нет в хранилище — пропуск")
                continue
            todo.append((row, name, size))
            self.stdout.write(f"  {row.key}: {name} — {size // 1024 // 1024} МБ")

        if not todo:
            self.stdout.write("Нечего сжимать: все фоновые видео уже в web-формате.")
            return
        if not opts["apply"]:
            self.stdout.write(f"\nНайдено роликов: {len(todo)}. Повторите с --apply.")
            return

        for row, name, size in todo:
            web = _webify_video(name, opts["quality"])
            if not web:
                self.stdout.write(f"  {row.key}: сжать не удалось (нет ffmpeg?) — оставляем как есть")
                continue
            new_url = default_storage.url(web)
            row.value = new_url
            row.save(update_fields=["value"])
            try:
                small = default_storage.size(web)
                self.stdout.write(
                    f"  {row.key}: {size // 1024 // 1024} МБ → {small // 1024 // 1024} МБ")
            except Exception:
                self.stdout.write(f"  {row.key}: готово")
        self.stdout.write("Готово. Проверьте окно входа на сайте.")
