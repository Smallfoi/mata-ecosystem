# -*- coding: utf-8 -*-
"""Дорисовать средний размер (900 px) снимкам, залитым до его появления.

Зачем. До 02.10.2026 у снимка было два размера: витринный 1600 и миниатюра 400.
Лента каталога показывала миниатюру, растягивая её вдвое — владелец увидел это как
«в ленте фотографии ужасного качества, а в карточке нормального». Средний размер
теперь делается при загрузке, а этой командой он появляется у старых снимков.

Исходник — витринный файл 1600 (оригинал камеры мы не храним; 1600 → 900 для ленты
более чем достаточно).

    python manage.py backfill_photo_cards            # показать, сколько без среднего
    python manage.py backfill_photo_cards --apply    # дорисовать
"""
from django.core.management.base import BaseCommand

from catalog import photos as photolib
from catalog.models import ProductPhoto


class Command(BaseCommand):
    help = "Создаёт недостающие снимки среднего размера (лента каталога)"

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true",
                            help="выполнить (без флага — только показать)")
        parser.add_argument("--limit", type=int, default=0,
                            help="обработать не больше N снимков за запуск")

    def handle(self, *args, **opts):
        rows = ProductPhoto.objects.filter(card="").exclude(image="").order_by("id")
        if opts["limit"]:
            rows = rows[:opts["limit"]]
        rows = list(rows)
        if not rows:
            self.stdout.write("Все снимки уже со средним размером.")
            return
        if not opts["apply"]:
            self.stdout.write(f"Без среднего размера: {len(rows)}. Повторите с --apply.")
            return

        done = failed = 0
        for photo in rows:
            try:
                if photolib.ensure_card(photo):
                    done += 1
            except Exception as exc:  # файл пропал из хранилища, битый webp
                failed += 1
                self.stdout.write(f"  #{photo.pk}: не вышло — {exc}")
        self.stdout.write(f"Готово: дорисовано {done}, с ошибкой {failed}.")
