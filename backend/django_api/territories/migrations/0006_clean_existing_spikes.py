"""Одноразовая чистка GPS-игл в УЖЕ захваченных территориях и вечном следе.

«Идеальный маршрут» (03.09.2026) отрезает иглы у НОВЫХ захватов, но геометрия,
записанная до фикса, доживает с иглами: живой слой — до 7 дней, footprints —
навсегда (и ST_Union новых забегов сохранил бы старые иглы). Применяем то же
морфологическое открытие (буфер ∓5 м по geography) к существующим строкам;
выродившиеся в пустоту записи удаляем.
"""
from django.db import migrations

_OPEN = (
    "ST_Multi(ST_CollectionExtract(ST_MakeValid("
    "ST_Buffer(ST_Buffer(geom::geography, -5), 5)::geometry), 3))"
)

SQL = f"""
UPDATE territories SET geom = {_OPEN};
DELETE FROM territories WHERE geom IS NULL OR ST_IsEmpty(geom) OR ST_Area(geom::geography) < 50;
UPDATE recent_captures SET geom = {_OPEN};
DELETE FROM recent_captures WHERE geom IS NULL OR ST_IsEmpty(geom);
UPDATE footprints SET geom = {_OPEN};
DELETE FROM footprints WHERE geom IS NULL OR ST_IsEmpty(geom);
"""


class Migration(migrations.Migration):
    dependencies = [("territories", "0005_territory_events")]
    operations = [migrations.RunSQL(SQL, reverse_sql=migrations.RunSQL.noop)]
