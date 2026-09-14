from django.db import migrations


class Migration(migrations.Migration):
    """Городские кварталы Якутска — статичная нарезка города по улицам (D-74, Ф1).

    Единица захвата территорий: не бесформенное пятно по маршруту, а реальный
    квартал. Данные грузятся командой `load_blocks` из blocks/seed/yakutsk.geojson
    (632 квартала, © OpenStreetMap ODbL). Владение кварталами — отдельная таблица
    в Фазе 2; здесь только статичный справочник геометрии.
    """

    initial = True
    dependencies = [("territories", "0001_initial")]  # ради CREATE EXTENSION postgis

    operations = [
        migrations.RunSQL(
            sql=[
                """
                CREATE TABLE IF NOT EXISTS city_blocks (
                    block_id TEXT PRIMARY KEY,
                    district TEXT,
                    area_m2 INTEGER NOT NULL DEFAULT 0,
                    geom geometry(Polygon, 4326) NOT NULL,
                    centroid geometry(Point, 4326) NOT NULL
                );
                """,
                "CREATE INDEX IF NOT EXISTS city_blocks_geom_gix ON city_blocks USING GIST (geom);",
                "CREATE INDEX IF NOT EXISTS city_blocks_district_ix ON city_blocks (district);",
            ],
            reverse_sql=["DROP TABLE IF EXISTS city_blocks;"],
        ),
    ]
