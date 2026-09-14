"""Засев троп/районов Якутска из seed-JSON (D-74, режимы «Тропы» и «Захват»).

Тропы/районы вносим вручную (владелец): участок-маршрут, по которому бегают. Движок
сверки трека и доски «чаще всех» уже есть — этой командой лишь заводим сами маршруты,
иначе сверять не с чем (на проде их было 0). Идемпотентно (upsert по id).

Запуск:  python manage.py seed_trails
         python manage.py seed_trails --file путь/к/другому.json
"""
import json
import os

from django.core.management.base import BaseCommand, CommandError

from trails import matching
from trails.models import Trail

DEFAULT_SEED = os.path.join(os.path.dirname(__file__), "..", "..", "seed", "yakutsk.json")


class Command(BaseCommand):
    help = "Заводит/обновляет тропы-маршруты (Trail) из seed-JSON."

    def add_arguments(self, parser):
        parser.add_argument("--file", default=DEFAULT_SEED)

    def handle(self, *args, **options):
        path = os.path.abspath(options["file"])
        if not os.path.exists(path):
            raise CommandError(f"Файл не найден: {path}")
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        rows = data.get("trails") or []
        if not rows:
            raise CommandError("В seed нет trails.")

        n = 0
        for t in rows:
            tid = t.get("id")
            points = t.get("points") or []
            if not tid or len(points) < 2:
                continue
            min_lat, max_lat, min_lon, max_lon = matching.bbox(points)
            length_m = t.get("length_m") or round(matching.line_length_m(points))
            Trail.objects.update_or_create(
                id=tid,
                defaults={
                    "name": t.get("name") or tid,
                    "city": t.get("city") or "Якутск",
                    "points": points,
                    "length_m": length_m,
                    "min_lat": min_lat,
                    "max_lat": max_lat,
                    "min_lon": min_lon,
                    "max_lon": max_lon,
                    "is_public": True,
                    "created_by": "",
                },
            )
            n += 1
        self.stdout.write(self.style.SUCCESS(f"Заведено троп: {n}"))
