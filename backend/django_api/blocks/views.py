"""Городские кварталы Якутска — статичный слой карты (D-74, Ф1).

GET /v1/blocks[?bbox=minLng,minLat,maxLng,maxLat] — полигоны кварталов для отрисовки
на карте. Владения (кто чем владеет) появятся в Фазе 2 — пока каждый квартал rel=free.
"""
import json

from django.db import connection
from rest_framework.decorators import api_view
from rest_framework.response import Response

from common.security import user_id_from_request

# Упрощение геометрии при отдаче (карте не нужны субметровые изломы улиц).
SIMPLIFY_TOLERANCE = 0.00003


@api_view(["GET"])
def list_blocks(request):
    if not user_id_from_request(request):
        return Response({"detail": "Нет токена"}, status=401)

    bbox = request.query_params.get("bbox")
    cols = (
        "block_id, district, area_m2, "
        f"ST_AsGeoJSON(ST_SimplifyPreserveTopology(geom, {SIMPLIFY_TOLERANCE}))"
    )
    with connection.cursor() as cur:
        if bbox:
            try:
                a, b, c, d = (float(x) for x in bbox.split(","))
            except (ValueError, TypeError):
                return Response({"detail": "bbox=minLng,minLat,maxLng,maxLat"}, status=400)
            cur.execute(
                f"SELECT {cols} FROM city_blocks "
                "WHERE geom && ST_MakeEnvelope(%s,%s,%s,%s,4326)",
                [a, b, c, d],
            )
        else:
            cur.execute(f"SELECT {cols} FROM city_blocks")
        rows = cur.fetchall()

    blocks = [
        {
            "blockId": block_id,
            "district": district,
            "areaM2": area_m2,
            "rel": "free",       # Ф2: mine|club|enemy по владению
            "ownerId": None,     # Ф2
            "geojson": json.loads(gj),
        }
        for block_id, district, area_m2, gj in rows
    ]
    return Response({"blocks": blocks})
