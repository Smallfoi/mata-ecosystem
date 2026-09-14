"""Загрузка городских кварталов в city_blocks из seed-GeoJSON (D-74, Ф1).

Идемпотентно (UPSERT по block_id) — можно гонять повторно после обновления нарезки.
Геометрия строится из GeoJSON через ST_GeomFromGeoJSON; центр — ST_PointOnSurface
(гарантированно ВНУТРИ полигона: в Фазе 2 захват считает «центр квартала в петле»).

Запуск:  python manage.py load_blocks
         python manage.py load_blocks --file путь/к/другому.geojson
"""
import json
import os

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

DEFAULT_SEED = os.path.join(os.path.dirname(__file__), "..", "..", "seed", "yakutsk.geojson")


class Command(BaseCommand):
    help = "Загружает/обновляет городские кварталы (city_blocks) из seed-GeoJSON."

    def add_arguments(self, parser):
        parser.add_argument("--file", default=DEFAULT_SEED, help="путь к GeoJSON FeatureCollection")

    def handle(self, *args, **options):
        path = os.path.abspath(options["file"])
        if not os.path.exists(path):
            raise CommandError(f"Файл не найден: {path}")
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        feats = data.get("features") or []
        if not feats:
            raise CommandError("В GeoJSON нет features.")

        upserted = 0
        with transaction.atomic(), connection.cursor() as cur:
            for ft in feats:
                props = ft.get("properties") or {}
                block_id = props.get("block_id")
                geom = ft.get("geometry")
                if not block_id or not geom or geom.get("type") != "Polygon":
                    continue
                gj = json.dumps(geom)
                district = props.get("district")
                area = int(props.get("area_m2") or 0)
                cur.execute(
                    """
                    INSERT INTO city_blocks (block_id, district, area_m2, geom, centroid)
                    VALUES (
                        %s, %s, %s,
                        ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326),
                        ST_PointOnSurface(ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326))
                    )
                    ON CONFLICT (block_id) DO UPDATE SET
                        district = EXCLUDED.district,
                        area_m2  = EXCLUDED.area_m2,
                        geom     = EXCLUDED.geom,
                        centroid = EXCLUDED.centroid
                    """,
                    [block_id, district, area, gj, gj],
                )
                upserted += 1

        self.stdout.write(self.style.SUCCESS(f"Загружено кварталов: {upserted}"))
