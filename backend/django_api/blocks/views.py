"""Городские кварталы Якутска — карта и владение (D-74, Ф1+Ф2).

GET /v1/blocks[?bbox=minLng,minLat,maxLng,maxLat] — полигоны кварталов с признаком
владения (rel: mine|club|enemy|free) для отрисовки на карте. Владение пишет захват
(territories.capture): квартал становится твоим, если его центр попал в петлю забега.
"""
import json

from django.db import connection
from rest_framework.decorators import api_view
from rest_framework.response import Response

from clubs.models import ClubMember
from common.people import names_of
from common.security import user_id_from_request

# Упрощение геометрии при отдаче (карте не нужны субметровые изломы улиц).
SIMPLIFY_TOLERANCE = 0.00003


def _club_of(uid):
    m = ClubMember.objects.filter(user_id=uid).first()
    return m.club_id if m else None


@api_view(["GET"])
def list_blocks(request):
    uid = user_id_from_request(request)
    if not uid:
        return Response({"detail": "Нет токена"}, status=401)
    my_club = _club_of(uid)

    bbox = request.query_params.get("bbox")
    cols = (
        "b.block_id, b.district, b.area_m2, "
        f"ST_AsGeoJSON(ST_SimplifyPreserveTopology(b.geom, {SIMPLIFY_TOLERANCE})), "
        "o.owner_id, o.club_id, EXTRACT(EPOCH FROM o.captured_at) * 1000"
    )
    join = "FROM city_blocks b LEFT JOIN block_ownership o ON o.block_id = b.block_id"
    with connection.cursor() as cur:
        if bbox:
            try:
                a, b, c, d = (float(x) for x in bbox.split(","))
            except (ValueError, TypeError):
                return Response({"detail": "bbox=minLng,minLat,maxLng,maxLat"}, status=400)
            cur.execute(
                f"SELECT {cols} {join} WHERE b.geom && ST_MakeEnvelope(%s,%s,%s,%s,4326)",
                [a, b, c, d],
            )
        else:
            cur.execute(f"SELECT {cols} {join}")
        rows = cur.fetchall()

    names = names_of([r[4] for r in rows if r[4]])
    blocks = []
    for block_id, district, area_m2, gj, owner_id, oclub, cap_ms in rows:
        if owner_id is None:
            rel = "free"
        elif owner_id == uid:
            rel = "mine"
        elif oclub and oclub == my_club:
            rel = "club"
        else:
            rel = "enemy"
        blocks.append(
            {
                "blockId": block_id,
                "district": district,
                "areaM2": area_m2,
                "rel": rel,
                "ownerId": owner_id,
                "ownerName": names.get(owner_id) if owner_id else None,
                "capturedAtMs": int(cap_ms or 0) if owner_id else None,
                "geojson": json.loads(gj),
            }
        )
    return Response({"blocks": blocks})
