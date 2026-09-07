import secrets
from datetime import timedelta

from django.utils import timezone
from django.db.models import Sum
from rest_framework.decorators import api_view
from rest_framework.response import Response

from accounts.models import Account
from common.uploads import image_extension
from common.security import user_id_from_request
from loyalty.models import LoyaltyTransaction

from notifications.models import create_notification

from .models import Club, ClubChallenge, ClubJoinRequest, ClubMember

# Допустимые пресеты оформления клуба (см. клиентский club_style.dart).
CLUB_STYLES = {"minimal", "north", "fire", "neon", "festive"}


def _style(value) -> str:
    v = (value or "").strip()
    return v if v in CLUB_STYLES else "minimal"


def _uid(request):
    return user_id_from_request(request)


def _balance(uid) -> int:
    """Баланс одним агрегатом в БД, а не суммой всех строк в Python."""
    return LoyaltyTransaction.objects.filter(user_id=uid).aggregate(
        s=Sum("amount"))["s"] or 0


def _km(uid) -> float:
    """Суммарный пробег за всё время (км). Растёт с каждым забегом, не тратится —
    в отличие от баллов кошелька. Источник — начисления за бег (runnerRun)/10."""
    pts = LoyaltyTransaction.objects.filter(
        user_id=uid, source="runnerRun"
    ).aggregate(s=Sum("amount"))["s"] or 0
    return round(pts / 10.0, 1)


def _km_of_users(uids) -> dict:
    """Пробег СРАЗУ ДЛЯ ВСЕХ перечисленных бегунов — одним запросом.

    Раньше километры считались вызовом `_km()` на каждого участника каждого
    клуба. На 60 клубах по 83 человека это 5000 запросов к базе и две секунды
    на одну страницу списка клубов — при трёх воркерах на проде страница
    занимала бы весь сервер.
    """
    uids = list(uids)
    if not uids:
        return {}
    rows = (
        LoyaltyTransaction.objects
        .filter(user_id__in=uids, source="runnerRun")
        .values("user_id")
        .annotate(pts=Sum("amount"))
    )
    return {r["user_id"]: round((r["pts"] or 0) / 10.0, 1) for r in rows}


def _names_of(uids) -> dict:
    """Имена скопом — вместо запроса на каждого участника."""
    uids = list(uids)
    if not uids:
        return {}
    return {
        a.id: (a.name or "—")
        for a in Account.objects.filter(id__in=uids).only("id", "name")
    }


def _km_between(uid, start, end) -> float:
    """Пробег (км) участника за период [start, end) — для прогресса челленджа."""
    pts = sum(
        t.amount
        for t in LoyaltyTransaction.objects.filter(
            user_id=uid, source="runnerRun", created_at__gte=start, created_at__lt=end
        ).only("amount")
    )
    return round(pts / 10.0, 1)


def _km_between_users(uids, start, end) -> dict:
    """Пробег за период сразу для всех участников — одним запросом."""
    uids = list(uids)
    if not uids:
        return {}
    rows = (
        LoyaltyTransaction.objects
        .filter(user_id__in=uids, source="runnerRun",
                created_at__gte=start, created_at__lt=end)
        .values("user_id")
        .annotate(pts=Sum("amount"))
    )
    return {r["user_id"]: round((r["pts"] or 0) / 10.0, 1) for r in rows}


def _challenge_json(club_id):
    """Активный челлендж клуба + прогресс и вклад участников, либо None."""
    now = timezone.now()
    ch = (
        ClubChallenge.objects.filter(club_id=club_id, end_at__gte=now)
        .order_by("-created_at")
        .first()
    )
    if not ch:
        return None
    # Вклад участников — двумя запросами на весь клуб, а не по два на каждого:
    # на клубе в сотню человек это была разница в двести обращений к базе.
    uids = list(
        ClubMember.objects.filter(club_id=club_id).values_list("user_id", flat=True)
    )
    km_by_user = _km_between_users(uids, ch.start_at, ch.end_at)
    names = _names_of(uids)
    contribs, total = [], 0.0
    for uid_ in uids:
        km = km_by_user.get(uid_, 0.0)
        total += km
        if km > 0:
            contribs.append({"userId": uid_, "name": names.get(uid_, "—"), "km": km})
    contribs.sort(key=lambda x: x["km"], reverse=True)
    secs_left = (ch.end_at - now).total_seconds()
    return {
        "id": ch.id,
        "title": ch.title,
        "targetKm": round(ch.target_km, 1),
        "currentKm": round(total, 1),
        "startAt": ch.start_at.isoformat(),
        "endAt": ch.end_at.isoformat(),
        "daysLeft": max(0, int(secs_left // 86400)),
        "hoursLeft": max(0, int(secs_left // 3600)),
        "contributions": contribs[:5],
    }


def _club_territory(club_id):
    """Удерживаемая клубом площадь (м²) + число зон (PostGIS, активные < HOLD)."""
    from django.db import connection
    from territories.views import HOLD_HOURS

    with connection.cursor() as cur:
        cur.execute(
            "SELECT COALESCE(SUM(ST_Area(geom::geography)), 0), COUNT(*) "
            "FROM territories WHERE club_id = %s "
            "AND captured_at > now() - make_interval(hours => %s)",
            [club_id, HOLD_HOURS],
        )
        area, pieces = cur.fetchone()
    return {"areaM2": round(area or 0), "pieces": int(pieces or 0)}


def _current_club_id(uid):
    m = ClubMember.objects.filter(user_id=uid).first()
    return m.club_id if m else None


def _name_of(uid):
    a = Account.objects.filter(id=uid).only("name").first()
    return a.name if a else "—"


def _members_json(club_id):
    # Личные баллы кошелька в клубе не показываем — у участника отдаём вклад в км.
    members = list(ClubMember.objects.filter(club_id=club_id))
    uids = [m.user_id for m in members]
    km, names = _km_of_users(uids), _names_of(uids)
    out = [
        {"userId": m.user_id, "name": names.get(m.user_id, "—"), "role": m.role,
         "km": km.get(m.user_id, 0.0)}
        for m in members
    ]
    out.sort(key=lambda x: x["km"], reverse=True)
    return out


def _summary(club: Club, total_km=None, member_count=None) -> dict:
    """Карточка клуба. Километры и число участников можно передать снаружи —
    список клубов считает их сразу для всех одним запросом (см. `_club_totals`)."""
    if total_km is None or member_count is None:
        members = list(ClubMember.objects.filter(club_id=club.id))
        km = _km_of_users(m.user_id for m in members)
        member_count = len(members)
        total_km = round(sum(km.values()), 1)
    return {
        "id": club.id, "name": club.name, "logo": club.logo, "city": club.city,
        "description": club.description, "ownerId": club.owner_id,
        "joinPolicy": club.join_policy, "memberCount": member_count,
        "style": club.style or "minimal",
        "cover": club.cover,
        # Активность клуба — суммарный пробег (км), а не баллы (баллы тратятся/динамичны).
        "totalKm": total_km,
    }


def _club_totals(club_ids):
    """Километры и число участников для СПИСКА клубов — двумя запросами на всё.

    Ключевая часть починки списка клубов: раньше он стоил запрос на каждого
    участника каждого клуба.
    """
    club_ids = list(club_ids)
    if not club_ids:
        return {}, {}
    links = list(
        ClubMember.objects.filter(club_id__in=club_ids).values_list("club_id", "user_id")
    )
    counts = {}
    for cid, _uid_ in links:
        counts[cid] = counts.get(cid, 0) + 1
    km_by_user = _km_of_users({u for _c, u in links})
    totals = {}
    for cid, u in links:
        totals[cid] = totals.get(cid, 0.0) + km_by_user.get(u, 0.0)
    return {c: round(v, 1) for c, v in totals.items()}, counts


def _detail(club: Club, uid) -> dict:
    base = _summary(club)
    base["members"] = _members_json(club.id)
    base["challenge"] = _challenge_json(club.id)
    base["territory"] = _club_territory(club.id)
    m = ClubMember.objects.filter(club_id=club.id, user_id=uid).first()
    base["myRole"] = m.role if m else None
    return base


@api_view(["GET", "POST"])
def clubs_root(request):
    uid = _uid(request)
    if not uid:
        return Response({"detail": "Нет токена"}, status=401)
    if request.method == "GET":
        search = request.query_params.get("search")
        qs = Club.objects.filter(is_hidden=False)  # скрытые модерацией не показываем
        if search:
            from django.db.models import Q
            qs = qs.filter(Q(name__icontains=search) | Q(city__icontains=search))
        clubs = list(qs.order_by("-created_at"))
        totals, counts = _club_totals(c.id for c in clubs)
        result = [
            _summary(c, totals.get(c.id, 0.0), counts.get(c.id, 0)) for c in clubs
        ]
        result.sort(key=lambda c: c["totalKm"], reverse=True)
        return Response(result)
    # POST — create
    d = request.data
    name = (d.get("name") or "").strip()
    if not name:
        return Response({"detail": "Название клуба обязательно"}, status=400)
    if _current_club_id(uid):
        return Response({"detail": "Вы уже состоите в клубе"}, status=409)
    policy = d.get("joinPolicy") if d.get("joinPolicy") in ("open", "request") else "open"
    club = Club.objects.create(
        id=f"c_{secrets.token_hex(8)}",
        name=name,
        logo=d.get("logo"),
        city=((d.get("city") or "").strip() or None),
        description=((d.get("description") or "").strip() or None),
        owner_id=uid,
        join_policy=policy,
        style=_style(d.get("style")),
    )
    ClubMember.objects.create(club_id=club.id, user_id=uid, role="owner")
    return Response(_detail(club, uid))


@api_view(["GET"])
def my_club(request):
    uid = _uid(request)
    if not uid:
        return Response({"detail": "Нет токена"}, status=401)
    cid = _current_club_id(uid)
    if not cid:
        return Response({"club": None})
    club = Club.objects.filter(id=cid).first()
    return Response({"club": _detail(club, uid)})


@api_view(["GET", "PATCH"])
def club_detail_or_update(request, club_id):
    uid = _uid(request)
    if not uid:
        return Response({"detail": "Нет токена"}, status=401)
    club = Club.objects.filter(id=club_id).first()
    if not club:
        return Response({"detail": "Клуб не найден"}, status=404)
    if request.method == "GET":
        return Response(_detail(club, uid))
    # PATCH — owner only
    if club.owner_id != uid:
        return Response({"detail": "Только владелец клуба"}, status=403)
    d = request.data
    if d.get("name") is not None and (d.get("name") or "").strip():
        club.name = d["name"].strip()
    if d.get("logo") is not None:
        club.logo = d["logo"]
    if d.get("city") is not None:
        club.city = (d.get("city") or "").strip() or None
    if d.get("description") is not None:
        club.description = (d.get("description") or "").strip() or None
    if d.get("joinPolicy") in ("open", "request"):
        club.join_policy = d["joinPolicy"]
    if d.get("style") is not None:
        club.style = _style(d.get("style"))
    club.save()
    return Response(_detail(club, uid))


@api_view(["POST"])
def join_club(request, club_id):
    uid = _uid(request)
    if not uid:
        return Response({"detail": "Нет токена"}, status=401)
    club = Club.objects.filter(id=club_id).first()
    if not club or club.is_hidden:  # скрытый модерацией недоступен для вступления
        return Response({"detail": "Клуб не найден"}, status=404)
    if _current_club_id(uid):
        return Response({"detail": "Вы уже состоите в клубе"}, status=409)
    if club.join_policy == "open":
        ClubMember.objects.create(club_id=club_id, user_id=uid, role="member")
        return Response({"status": "joined"})
    if not ClubJoinRequest.objects.filter(
        club_id=club_id, user_id=uid, status="pending"
    ).exists():
        ClubJoinRequest.objects.create(
            id=f"r_{secrets.token_hex(8)}", club_id=club_id, user_id=uid, status="pending"
        )
        # Уведомляем владельца клуба о новой заявке.
        create_notification(
            club.owner_id,
            "Новая заявка в клуб",
            f"{_name_of(uid)} хочет вступить в клуб «{club.name}»",
            "system",
        )
    return Response({"status": "requested"})


@api_view(["POST"])
def leave_club(request, club_id):
    uid = _uid(request)
    if not uid:
        return Response({"detail": "Нет токена"}, status=401)
    m = ClubMember.objects.filter(club_id=club_id, user_id=uid).first()
    if not m:
        return Response({"detail": "Вы не состоите в этом клубе"}, status=404)
    if m.role == "owner":
        cnt = ClubMember.objects.filter(club_id=club_id).count()
        if cnt > 1:
            return Response({"detail": "Владелец не может выйти, пока есть участники"}, status=409)
        ClubMember.objects.filter(club_id=club_id).delete()
        ClubJoinRequest.objects.filter(club_id=club_id).delete()
        Club.objects.filter(id=club_id).delete()
        return Response({"status": "left", "clubDeleted": True})
    m.delete()
    return Response({"status": "left"})


@api_view(["GET"])
def club_requests(request, club_id):
    uid = _uid(request)
    if not uid:
        return Response({"detail": "Нет токена"}, status=401)
    club = Club.objects.filter(id=club_id).first()
    if not club:
        return Response({"detail": "Клуб не найден"}, status=404)
    if club.owner_id != uid:
        return Response({"detail": "Только владелец клуба"}, status=403)
    rows = ClubJoinRequest.objects.filter(club_id=club_id, status="pending").order_by("created_at")
    return Response(
        [{"id": r.id, "userId": r.user_id, "name": _name_of(r.user_id)} for r in rows]
    )


@api_view(["POST"])
def approve_request(request, req_id):
    uid = _uid(request)
    if not uid:
        return Response({"detail": "Нет токена"}, status=401)
    req = ClubJoinRequest.objects.filter(id=req_id).first()
    if not req or req.status != "pending":
        return Response({"detail": "Заявка не найдена"}, status=404)
    club = Club.objects.filter(id=req.club_id).first()
    if not club or club.owner_id != uid:
        return Response({"detail": "Только владелец клуба"}, status=403)
    if _current_club_id(req.user_id):
        req.status = "rejected"
        req.save(update_fields=["status"])
        return Response({"detail": "Пользователь уже состоит в клубе"}, status=409)
    ClubMember.objects.create(club_id=req.club_id, user_id=req.user_id, role="member")
    req.status = "approved"
    req.save(update_fields=["status"])
    create_notification(
        req.user_id,
        "Заявка одобрена",
        f"Вы вступили в клуб «{club.name}»",
        "system",
    )
    return Response({"status": "approved"})


@api_view(["POST"])
def reject_request(request, req_id):
    uid = _uid(request)
    if not uid:
        return Response({"detail": "Нет токена"}, status=401)
    req = ClubJoinRequest.objects.filter(id=req_id).first()
    if not req:
        return Response({"detail": "Заявка не найдена"}, status=404)
    club = Club.objects.filter(id=req.club_id).first()
    if not club or club.owner_id != uid:
        return Response({"detail": "Только владелец клуба"}, status=403)
    req.status = "rejected"
    req.save(update_fields=["status"])
    create_notification(
        req.user_id,
        "Заявка отклонена",
        f"Заявка на вступление в клуб «{club.name}» отклонена",
        "system",
    )
    return Response({"status": "rejected"})


@api_view(["POST"])
def club_logo(request, club_id):
    """Загрузка фото-логотипа клуба (multipart, поле `image`). Только владелец.
    Файл кладём в media, в `club.logo` — URL (клиент покажет фото вместо буквы)."""
    uid = _uid(request)
    if not uid:
        return Response({"detail": "Нет токена"}, status=401)
    club = Club.objects.filter(id=club_id).first()
    if not club:
        return Response({"detail": "Клуб не найден"}, status=404)
    if club.owner_id != uid:
        return Response({"detail": "Только владелец клуба"}, status=403)
    f = request.FILES.get("image")
    # Тип определяем по СОДЕРЖИМОМУ: имя файла и Content-Type присылает клиент (D-37).
    ext, upload_error = image_extension(f)
    if upload_error:
        return Response({"detail": upload_error}, status=400)
    from django.core.files.storage import default_storage

    saved = default_storage.save(
        f"uploads/clubs/{club_id}_{secrets.token_hex(4)}.{ext}", f
    )
    club.logo = default_storage.url(saved)  # локально /media/…, в проде S3/CDN (D-31)
    club.save(update_fields=["logo"])
    return Response(_detail(club, uid))


@api_view(["POST", "DELETE"])
def club_cover(request, club_id):
    """Обложка-баннер клуба (POST multipart, поле `image`; DELETE — снять).
    Только владелец. Файл в media, в `club.cover` — URL (фон шапки)."""
    uid = _uid(request)
    if not uid:
        return Response({"detail": "Нет токена"}, status=401)
    club = Club.objects.filter(id=club_id).first()
    if not club:
        return Response({"detail": "Клуб не найден"}, status=404)
    if club.owner_id != uid:
        return Response({"detail": "Только владелец клуба"}, status=403)
    if request.method == "DELETE":
        club.cover = None
        club.save(update_fields=["cover"])
        return Response(_detail(club, uid))
    f = request.FILES.get("image")
    # Тип определяем по СОДЕРЖИМОМУ: имя файла и Content-Type присылает клиент (D-37).
    ext, upload_error = image_extension(f)
    if upload_error:
        return Response({"detail": upload_error}, status=400)
    from django.core.files.storage import default_storage

    saved = default_storage.save(
        f"uploads/clubs/cover_{club_id}_{secrets.token_hex(4)}.{ext}", f
    )
    club.cover = default_storage.url(saved)  # локально /media/…, в проде S3/CDN (D-31)
    club.save(update_fields=["cover"])
    return Response(_detail(club, uid))


@api_view(["POST", "DELETE"])
def club_challenge(request, club_id):
    """Клубный челлендж (только владелец). POST — создать цель (title, targetKm,
    days); DELETE — отменить активный. Один активный челлендж на клуб."""
    uid = _uid(request)
    if not uid:
        return Response({"detail": "Нет токена"}, status=401)
    club = Club.objects.filter(id=club_id).first()
    if not club:
        return Response({"detail": "Клуб не найден"}, status=404)
    if club.owner_id != uid:
        return Response({"detail": "Только владелец клуба"}, status=403)
    now = timezone.now()
    if request.method == "DELETE":
        ClubChallenge.objects.filter(club_id=club.id, end_at__gte=now).delete()
        return Response(_detail(club, uid))
    d = request.data
    title = (d.get("title") or "").strip()
    if not title:
        return Response({"detail": "Название цели обязательно"}, status=400)
    try:
        target = float(d.get("targetKm") or 0)
    except (TypeError, ValueError):
        target = 0.0
    if target <= 0:
        return Response({"detail": "Цель в км должна быть больше 0"}, status=400)
    try:
        days = int(d.get("days") or 7)
    except (TypeError, ValueError):
        days = 7
    days = max(1, min(365, days))
    # Один активный челлендж: старые активные снимаем.
    ClubChallenge.objects.filter(club_id=club.id, end_at__gte=now).delete()
    ClubChallenge.objects.create(
        id=f"chl_{secrets.token_hex(8)}",
        club_id=club.id,
        title=title[:200],
        target_km=target,
        start_at=now,
        end_at=now + timedelta(days=days),
    )
    return Response(_detail(club, uid))


@api_view(["GET"])
def war(request):
    """«Война района» (Квартал 2.0, Ф6): позиции клубов по земле + угрозы недели.

    Угроза — чужой захват, отрезавший землю у тебя или у одноклубника за
    последние 7 дней (лента territory_events из capture).
    """
    uid = user_id_from_request(request)
    if not uid:
        return Response({"detail": "Нет токена"}, status=401)

    from django.db import connection

    from common.people import names_of
    from territories.views import HOLD_HOURS

    my_membership = ClubMember.objects.filter(user_id=uid).first()
    my_club = my_membership.club_id if my_membership else None

    with connection.cursor() as cur:
        cur.execute(
            """
            SELECT club_id, SUM(ST_Area(geom::geography)) AS area, COUNT(*)
            FROM territories
            WHERE club_id IS NOT NULL
              AND captured_at > now() - make_interval(hours => %s)
            GROUP BY club_id ORDER BY area DESC LIMIT 6
            """,
            [HOLD_HOURS],
        )
        standing_rows = cur.fetchall()

    standings = []
    for i, (club_id, area, pieces) in enumerate(standing_rows):
        club = Club.objects.filter(id=club_id).first()
        standings.append(
            {
                "clubId": club_id,
                "name": club.name if club else "Клуб",
                "areaM2": round(float(area or 0), 1),
                "pieces": pieces,
                "place": i + 1,
                "isMine": club_id == my_club,
            }
        )

    victims = [uid]
    if my_club:
        victims = list(
            ClubMember.objects.filter(club_id=my_club).values_list(
                "user_id", flat=True
            )
        )
    threats = []
    with connection.cursor() as cur:
        cur.execute(
            """
            SELECT victim_owner, attacker, area_m2,
                   EXTRACT(EPOCH FROM created_at) * 1000
            FROM territory_events
            WHERE victim_owner = ANY(%s)
              AND created_at > now() - interval '7 days'
            ORDER BY created_at DESC LIMIT 20
            """,
            [victims],
        )
        threat_rows = cur.fetchall()
    people = names_of(
        list({r[0] for r in threat_rows} | {r[1] for r in threat_rows})
    )
    for victim, attacker, area, at_ms in threat_rows:
        threats.append(
            {
                "victimName": people.get(victim, "Бегун"),
                "attackerName": people.get(attacker, "Бегун"),
                "mine": victim == uid,
                "areaM2": round(float(area or 0), 1),
                "atMs": int(at_ms or 0),
            }
        )

    return Response({"standings": standings, "threats": threats})
