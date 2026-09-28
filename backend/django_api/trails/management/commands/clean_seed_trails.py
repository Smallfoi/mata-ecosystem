# -*- coding: utf-8 -*-
"""Убрать тропы-заготовки, засеянные из OSM (`seed_trails`).

Зачем. 14.09.2026 в базу легли три осевые линии улиц Якутска (проспект Ленина,
Дзержинского, Орджоникидзе) — как заготовки, чтобы движку троп было что сверять.
Владелец увидел их на карте и назвал «непонятными линиями» (27.09.2026): это не
маршруты, по которым бегают, а просто середины улиц. Настоящие тропы рисует
человек — клуб отмечает свой круг, бегун маршрут у дома (D-60, D-102).

Почему отдельной командой, а не SQL по SSH. Удаление на проде должно быть
разобранным кодом с тестом, а не строкой, набранной в терминале: команда трогает
ТОЛЬКО заготовки (`ykt-trail-*`) и только те, по которым никто не бежал. Есть
попытки — тропа уже чья-то история, её не трогаем и говорим об этом вслух.

    python manage.py clean_seed_trails            # показать, что будет удалено
    python manage.py clean_seed_trails --apply    # удалить

Вернуть обратно: `python manage.py seed_trails` (сид лежит в репозитории).
"""
from django.core.management.base import BaseCommand

from trails.models import Trail, TrailAttempt

SEED_PREFIX = "ykt-trail-"


class Command(BaseCommand):
    help = "Удаляет тропы-заготовки из сида (ykt-trail-*), по которым нет попыток"

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true",
                            help="выполнить (без флага — только показать)")
        parser.add_argument("--prefix", default=SEED_PREFIX,
                            help=f"префикс id заготовок (по умолчанию {SEED_PREFIX})")

    def handle(self, *args, **opts):
        prefix = opts["prefix"]
        rows = list(Trail.objects.filter(id__startswith=prefix))
        if not rows:
            self.stdout.write("Заготовок не найдено — чистить нечего.")
            return

        used, free = [], []
        for t in rows:
            n = TrailAttempt.objects.filter(trail_id=t.id).count()
            (used if n else free).append((t, n))

        for t, n in free:
            self.stdout.write(f"  удалить: {t.id} — {t.name}")
        for t, n in used:
            self.stdout.write(
                f"  ОСТАВЛЯЮ: {t.id} — {t.name}: по ней {n} прохождений, это уже чья-то история")

        if not free:
            self.stdout.write("Удалять нечего: по всем заготовкам есть прохождения.")
            return
        if not opts["apply"]:
            self.stdout.write(f"\nБудет удалено: {len(free)}. Повторите с --apply.")
            return

        Trail.objects.filter(id__in=[t.id for t, _ in free]).delete()
        self.stdout.write(f"Удалено заготовок: {len(free)}. Осталось троп: {Trail.objects.count()}.")
