# -*- coding: utf-8 -*-
"""Пережать в WebP фото сайта, загруженные до 18.11.2026 (JPEG/PNG).

Загрузка в Конструкторе с 18.11 сразу кладёт WebP (`_webify_image`), а старые фото
блоков и баннеров остаются JPEG — вдвое тяжелее. Команда пережимает их на месте:
новый файл в поле картинки, старый удаляется. Уже WebP, SVG и GIF не трогает,
поэтому её можно запускать сколько угодно раз (её и запускает beat).

    python manage.py webify_site_images            # показать, что будет сделано
    python manage.py webify_site_images --apply    # сделать
"""
import os

from django.core.management.base import BaseCommand

SKIP = (".webp", ".svg", ".gif")


def _rows():
    from catalog.models import Banner, SiteContent

    for model in (SiteContent, Banner):
        for obj in model.objects.exclude(image="").exclude(image__isnull=True):
            if not obj.image.name.lower().endswith(SKIP):
                yield obj


class Command(BaseCommand):
    help = "Пережать в WebP фото блоков сайта и баннеров, загруженные до перехода на WebP"

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true",
                            help="выполнить (без флага — только показать)")

    def handle(self, *args, **opts):
        from django.core.files.storage import default_storage

        from config.admin_views import _webify_image

        todo = list(_rows())
        if not todo:
            self.stdout.write("Нечего пережимать: все фото сайта уже WebP.")
            return
        for obj in todo:
            self.stdout.write(f"  {obj._meta.model_name} {obj.pk}: {obj.image.name}")
        if not opts["apply"]:
            self.stdout.write(f"\nНайдено фото: {len(todo)}. Повторите с --apply.")
            return

        total_old = total_new = 0
        for obj in todo:
            old_name = obj.image.name
            try:
                with obj.image.open("rb") as fh:
                    data = fh.read()
            except Exception as exc:
                self.stdout.write(f"  {old_name}: не прочитать ({exc}) — пропуск")
                continue
            from django.core.files.base import ContentFile
            src = ContentFile(data, name=os.path.basename(old_name))
            web = _webify_image(src)
            if not getattr(web, "name", "").endswith(".webp"):
                self.stdout.write(f"  {old_name}: не пережалось — оставляем как есть")
                continue
            new_size = web.size
            obj.image.save(web.name, web, save=False)
            obj.save(update_fields=["image"])
            try:
                default_storage.delete(old_name)
            except Exception:
                pass
            total_old += len(data)
            total_new += new_size
            self.stdout.write(f"  {old_name} → {obj.image.name}: "
                              f"{len(data) // 1024} → {new_size // 1024} КБ")
        if total_old:
            self.stdout.write(f"Готово: {total_old // 1024} → {total_new // 1024} КБ.")
