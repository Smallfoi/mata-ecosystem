"""Городские кварталы Якутска — карта, владение и дом (D-74, Ф1–Ф3).

GET  /v1/blocks[?bbox=...] — полигоны кварталов с признаком владения (rel:
     mine|club|enemy|free) и флагом дома. Владение пишет захват (territories.capture).
POST /v1/blocks/home {blockId} — назначить домашний квартал (несгораемый, приватный).

Ф3: владение живёт до конца сезона-месяца (старое = свободно), домашний квартал
не сбрасывается и не перехватывается; чужой дом виден анонимно (не раскрываем адрес).
Эффективный владелец считается в SQL: дом → владелец навсегда; иначе — только если
захвачен в текущем месяце (date_trunc('month', now())).
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

# Эффективный владелец с учётом сезона и дома (общий для чтения и записи).
_EFF_OWNER_SQL = (
    "CASE WHEN h.owner_id IS NOT NULL THEN h.owner_id "
    "     WHEN o.captured_at >= date_trunc('month', now()) THEN o.owner_id "
    "     ELSE NULL END"
)


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
        f"{_EFF_OWNER_SQL} AS eff_owner, o.club_id, "
        "EXTRACT(EPOCH FROM o.captured_at) * 1000, h.owner_id AS home_owner"
    )
    join = (
        "FROM city_blocks b "
        "LEFT JOIN block_ownership o ON o.block_id = b.block_id "
        "LEFT JOIN home_block h ON h.block_id = b.block_id"
    )
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
    for block_id, district, area_m2, gj, eff_owner, oclub, cap_ms, home_owner in rows:
        others_home = home_owner is not None and home_owner != uid
        if eff_owner is None:
            rel = "free"
        elif eff_owner == uid:
            rel = "mine"
        elif oclub and oclub == my_club:
            rel = "club"
        else:
            rel = "enemy"
        # Приватность: чужой дом виден как занятый, но анонимно (не раскрываем, чей).
        if others_home:
            owner_id_out = None
            owner_name = None
            captured_ms = None
        else:
            owner_id_out = eff_owner
            owner_name = names.get(eff_owner) if eff_owner else None
            captured_ms = int(cap_ms or 0) if eff_owner else None
        blocks.append(
            {
                "blockId": block_id,
                "district": district,
                "areaM2": area_m2,
                "rel": rel,
                "ownerId": owner_id_out,
                "ownerName": owner_name,
                "capturedAtMs": captured_ms,
                "home": home_owner == uid,  # мой домашний квартал
                "geojson": json.loads(gj),
            }
        )
    return Response({"blocks": blocks})


@api_view(["POST"])
def set_home(request):
    """Назначить домашний квартал (D-74, Ф3). Один дом на пользователя; квартал должен
    быть свободен или уже твой (чужой захваченный/домашний — сначала отвоюй)."""
    uid = user_id_from_request(request)
    if not uid:
        return Response({"detail": "Нет токена"}, status=401)
    block_id = (request.data.get("blockId") or "").strip()
    if not block_id:
        return Response({"detail": "Нужен blockId"}, status=400)

    club_id = _club_of(uid)
    with connection.cursor() as cur:
        cur.execute("SELECT 1 FROM city_blocks WHERE block_id=%s", [block_id])
        if not cur.fetchone():
            return Response({"detail": "Квартал не найден"}, status=404)
        # Эффективный владелец: занятый кем-то другим (свежий или чужой дом) — нельзя.
        cur.execute(
            f"SELECT {_EFF_OWNER_SQL} FROM city_blocks b "
            "LEFT JOIN block_ownership o ON o.block_id=b.block_id "
            "LEFT JOIN home_block h ON h.block_id=b.block_id WHERE b.block_id=%s",
            [block_id],
        )
        eff = (cur.fetchone() or [None])[0]
        if eff is not None and eff != uid:
            return Response(
                {"detail": "Квартал занят — сначала захвати его пробежкой."}, status=409
            )
        # Один дом на пользователя (PK owner_id) — заменяем прежний.
        cur.execute(
            "INSERT INTO home_block (owner_id, block_id, set_at) VALUES (%s,%s,now()) "
            "ON CONFLICT (owner_id) DO UPDATE SET block_id=EXCLUDED.block_id, set_at=now()",
            [uid, block_id],
        )
        # Дом становится твоим владением.
        cur.execute(
            "INSERT INTO block_ownership (block_id, owner_id, club_id, captured_at) "
            "VALUES (%s,%s,%s,now()) ON CONFLICT (block_id) DO UPDATE SET "
            "owner_id=EXCLUDED.owner_id, club_id=EXCLUDED.club_id, captured_at=now()",
            [block_id, uid, club_id],
        )
    return Response({"ok": True, "blockId": block_id})
