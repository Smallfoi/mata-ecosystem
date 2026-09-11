from django.db import IntegrityError
from rest_framework.decorators import api_view, throttle_classes
from rest_framework.response import Response

from common.throttling import AuthEndpointThrottle

from common.uploads import image_extension
from common.security import (
    hash_password,
    make_token,
    new_user_id,
    normalize_phone,
    synthetic_email_for_phone,
    user_id_from_request,
    verify_password,
)
from loyalty.models import seed_runner_points

from .models import Account
from .sms import channel_info, check_code, code_error, request_code, sms_enabled


@api_view(["POST"])
@throttle_classes([AuthEndpointThrottle])
def register(request):
    """Регистрация в экосистеме.

    Основной путь (телефон+пароль): {phone, code, password, name, email?} — код
    из SMS (phone/request) подтверждает телефон ОДИН раз, дальше вход по паролю.
    Легаси (email+пароль, без phone/code) сохранён для обратной совместимости.
    """
    d = request.data
    from analytics.models import E_REGISTER, track

    phone = normalize_phone(d.get("phone") or "")
    password = d.get("password") or ""
    name = (d.get("name") or "").strip()
    email = (d.get("email") or "").strip().lower()

    if phone:  # регистрация по телефону — обязательное SMS-подтверждение
        if not check_code(phone, d.get("code") or ""):
            return Response({"detail": code_error(phone)}, status=401)
        if len(password) < 4:
            return Response({"detail": "Пароль слишком короткий (мин. 4 символа)"}, status=400)
        if Account.objects.filter(phone=phone).exists():
            return Response({"detail": "Этот телефон уже зарегистрирован — войдите по паролю"}, status=409)
        if not email:
            email = synthetic_email_for_phone(phone)
        elif Account.objects.filter(email=email).exists():
            return Response({"detail": "Этот email уже используется"}, status=409)
        acc = Account.objects.create(
            id=new_user_id(), name=name, email=email, phone=phone,
            provider="phone", password_hash=hash_password(password),
        )
        seed_runner_points(acc.id)
        track(E_REGISTER, user_id=acc.id, source="phone")
        return Response({"token": make_token(acc.id), "user": acc.to_json()})

    # Легаси: регистрация по email+паролю (обратная совместимость).
    if Account.objects.filter(email=email).exists():
        return Response({"detail": "Пользователь с таким email уже существует"}, status=409)
    acc = Account.objects.create(
        id=new_user_id(),
        name=name,
        email=email,
        phone=d.get("phone"),
        provider="email",
        password_hash=hash_password(password),
    )
    seed_runner_points(acc.id)
    track(E_REGISTER, user_id=acc.id, source="email")  # аналитика (D-30)
    return Response({"token": make_token(acc.id), "user": acc.to_json()})


@api_view(["POST"])
@throttle_classes([AuthEndpointThrottle])
def login(request):
    """Вход по паролю: {phone, password} (основной путь) или {email, password} (легаси)."""
    d = request.data
    phone = normalize_phone(d.get("phone") or "")
    if phone:
        acc = Account.objects.filter(phone=phone).first()
    else:
        email = (d.get("email") or "").strip().lower()
        acc = Account.objects.filter(email=email).first()
    if not acc or not verify_password(d.get("password") or "", acc.password_hash or ""):
        return Response({"detail": "Неверный телефон/email или пароль"}, status=401)
    if acc.is_blocked:
        return Response({"detail": "Аккаунт заблокирован"}, status=403)
    return Response({"token": make_token(acc.id), "user": acc.to_json()})


@api_view(["POST"])
@throttle_classes([AuthEndpointThrottle])
def password_reset(request):
    """Сброс пароля по SMS: {phone, code, password}. Код из phone/request (dev 1234).
    Тем же телефоном подтверждаем владение и ставим новый пароль."""
    d = request.data
    phone = normalize_phone(d.get("phone") or "")
    if not phone:
        return Response({"detail": "Нет телефона"}, status=400)
    if not check_code(phone, d.get("code") or ""):
        return Response({"detail": code_error(phone)}, status=401)
    password = d.get("password") or ""
    if len(password) < 4:
        return Response({"detail": "Пароль слишком короткий (мин. 4 символа)"}, status=400)
    acc = Account.objects.filter(phone=phone).first()
    if not acc:
        return Response({"detail": "Аккаунт с таким телефоном не найден"}, status=404)
    if acc.is_blocked:
        return Response({"detail": "Аккаунт заблокирован"}, status=403)
    acc.password_hash = hash_password(password)
    acc.save(update_fields=["password_hash"])
    return Response({"token": make_token(acc.id), "user": acc.to_json()})


@api_view(["POST"])
@throttle_classes([AuthEndpointThrottle])
def phone_request(request):
    """Отправить код входа на телефон. В dev (без провайдера) ничего не шлётся —
    код входа всегда 1234. С провайдером уходит одноразовый код (звонок или SMS)."""
    phone = normalize_phone(request.data.get("phone") or "")
    if not phone:
        return Response({"detail": "Нет телефона"}, status=400)
    if not request_code(phone):
        # Провайдер не принял отправку. Молчаливое «ok» оставило бы человека ждать
        # код, который никогда не придёт, — пусть лучше увидит ошибку и повторит.
        return Response(
            {"detail": "Не удалось отправить код. Попробуйте ещё раз."}, status=502
        )
    # channel говорит клиенту, показывать ли поле кода: часть каналов подтверждается
    # кнопкой на телефоне, и поле там просто некуда заполнять.
    return Response(
        {"ok": True, "smsEnabled": sms_enabled(), "channel": channel_info(phone)}
    )


@api_view(["POST"])
@throttle_classes([AuthEndpointThrottle])
def phone_channel(request):
    """Чем сейчас подтверждается вход: кодом или кнопкой на телефоне.

    Канал может смениться посреди сессии (провайдер сам переключается, если,
    например, звонок не прошёл), поэтому клиент переспрашивает это, пока ждёт.
    Намеренно НЕ используем long-polling провайдера: он держал бы наш рабочий
    процесс занятым до минуты на каждого входящего.
    """
    phone = normalize_phone(request.data.get("phone") or "")
    if not phone:
        return Response({"detail": "Нет телефона"}, status=400)
    info = channel_info(phone)
    if not info:
        return Response({"detail": "Сессия не найдена или истекла"}, status=404)
    return Response(info)


@api_view(["POST"])
@throttle_classes([AuthEndpointThrottle])
def phone_verify(request):
    d = request.data
    phone = normalize_phone(d.get("phone") or "")
    if not check_code(phone, d.get("code") or ""):
        return Response({"detail": code_error(phone)}, status=401)
    email = synthetic_email_for_phone(phone)
    acc = Account.objects.filter(phone=phone).first()
    if not acc:
        acc = Account.objects.filter(email=email).first()
        if acc:
            acc.phone = phone
            acc.save(update_fields=["phone"])
    created = False
    if not acc:
        acc = Account.objects.create(
            id=new_user_id(),
            name=(d.get("name") or "Runner").strip(),
            email=email,
            phone=phone,
            provider="phone",
            password_hash=hash_password(f"phone:{phone}"),
        )
        seed_runner_points(acc.id)
        created = True
    if acc.is_blocked:
        return Response({"detail": "Аккаунт заблокирован"}, status=403)
    # Аналитика (D-30): регистрация нового аккаунта или вход существующего.
    from analytics.models import E_LOGIN, E_REGISTER, track

    track(E_REGISTER if created else E_LOGIN, user_id=acc.id, source="phone")
    return Response({"token": make_token(acc.id), "user": acc.to_json()})


@api_view(["GET"])
def me(request):
    uid = user_id_from_request(request)
    if not uid:
        return Response({"detail": "Нет токена"}, status=401)
    acc = Account.objects.filter(id=uid).first()
    if not acc:
        return Response({"detail": "Пользователь не найден"}, status=404)
    return Response(acc.to_json())


@api_view(["PATCH"])
def update_profile(request):
    uid = user_id_from_request(request)
    if not uid:
        return Response({"detail": "Нет токена"}, status=401)
    acc = Account.objects.filter(id=uid).first()
    if not acc:
        return Response({"detail": "User not found"}, status=404)
    d = request.data
    if d.get("name") is not None:
        name = (d.get("name") or "").strip()
        if not name:
            return Response({"detail": "Name cannot be empty"}, status=400)
        acc.name = name
    if d.get("phone") is not None:
        # Телефон — это ЛОГИН: вход по SMS ищет аккаунт именно по нему, а поле не
        # уникально. Смена без подтверждения = присвоить себе чужой номер и перехватить
        # вход владельца (D-37). Меняем только первичное заполнение пустого поля;
        # смена номера — через поддержку или отдельный проверенный сценарий.
        new_phone = normalize_phone(d.get("phone") or "")
        if not acc.phone and new_phone:
            if Account.objects.filter(phone=new_phone).exclude(id=acc.id).exists():
                return Response({"detail": "Этот номер уже занят"}, status=409)
            acc.phone = new_phone
    if d.get("email") is not None:
        em = (d.get("email") or "").strip().lower()
        if em and "@" not in em:
            return Response({"detail": "Invalid email"}, status=400)
        if em:
            acc.email = em
    if d.get("city") is not None:
        acc.city = (d.get("city") or "").strip() or None
    if d.get("avatarPath") is not None:
        acc.avatar_path = (d.get("avatarPath") or "").strip() or None
    if d.get("addresses") is not None:
        # Адреса доставки — единые для экосистемы. Принимаем список (строки или объекты).
        addrs = d.get("addresses")
        acc.addresses = addrs if isinstance(addrs, list) else []
    try:
        acc.save()
    except IntegrityError:
        return Response({"detail": "Email already belongs to another account"}, status=409)
    return Response(acc.to_json())


@api_view(["POST", "DELETE"])
def profile_avatar(request):
    """Аватар профиля — единый для всей экосистемы. POST multipart `image` →
    media, в avatar_path кладём URL; все приложения берут аватар с сервера.
    DELETE — снять аватар (вернуться к инициалам)."""
    uid = user_id_from_request(request)
    if not uid:
        return Response({"detail": "Нет токена"}, status=401)
    acc = Account.objects.filter(id=uid).first()
    if not acc:
        return Response({"detail": "Пользователь не найден"}, status=404)
    if request.method == "DELETE":
        acc.avatar_path = None
        acc.save(update_fields=["avatar_path"])
        return Response(acc.to_json())
    f = request.FILES.get("image")
    # Тип определяем по СОДЕРЖИМОМУ: имя файла и Content-Type присылает клиент (D-37).
    ext, upload_error = image_extension(f)
    if upload_error:
        return Response({"detail": upload_error}, status=400)
    import secrets

    from django.core.files.storage import default_storage

    saved = default_storage.save(
        f"uploads/avatars/{uid}_{secrets.token_hex(4)}.{ext}", f
    )
    acc.avatar_path = default_storage.url(saved)  # локально /media/…, в проде S3/CDN (D-31)
    acc.save(update_fields=["avatar_path"])
    return Response(acc.to_json())


@api_view(["GET", "PATCH"])
def account_privacy(request):
    """Настройки приватности (LAUNCH_READINESS §2). GET → текущие; PATCH → меняет
    {profilePublic, routePublic, realtimePublic}. По умолчанию всё закрыто."""
    uid = user_id_from_request(request)
    if not uid:
        return Response({"detail": "Нет токена"}, status=401)
    acc = Account.objects.filter(id=uid).first()
    if not acc:
        return Response({"detail": "User not found"}, status=404)
    if request.method == "PATCH":
        d = request.data
        if d.get("profilePublic") is not None:
            acc.profile_public = bool(d.get("profilePublic"))
        if d.get("routePublic") is not None:
            acc.route_public = bool(d.get("routePublic"))
        if d.get("realtimePublic") is not None:
            acc.realtime_public = bool(d.get("realtimePublic"))
        acc.save(update_fields=["profile_public", "route_public", "realtime_public"])
    return Response(acc.privacy_json())


@api_view(["GET"])
def me_stats(request):
    """Личная аналитика пользователя: активность бега, баллы, заказы.
    Данные — из общего бэка (источник правды), одинаковы во всех приложениях."""
    uid = user_id_from_request(request)
    if not uid:
        return Response({"detail": "Нет токена"}, status=401)
    # Кэш на юзера (D-29): агрегаты тяжёлые, а меняются только при его транзакциях —
    # add_txn сбрасывает кэш (invalidate_stats). Плюс safety-TTL на изменения мимо add_txn.
    from common.cache import STATS_TTL, cache_json, stats_key

    data = cache_json(stats_key(uid), STATS_TTL, lambda: _compute_stats(uid))
    return Response(data)


def _compute_stats(uid):
    """Тяжёлый расчёт личной статистики (забеги/баллы/заказы). Кэшируется по uid."""
    from django.db.models import Count, Sum

    from loyalty.models import LoyaltyTransaction, balance_of
    from orders.models import Order
    from runs.models import Run

    runs = Run.objects.filter(user_id=uid)
    runs_agg = runs.aggregate(c=Count("id"))
    # «Реальные» км — без флаг-забегов (анти-чит); флаг-дистанцию не считаем.
    km_agg = runs.filter(flagged=False).aggregate(d=Sum("distance_m"))
    txns = LoyaltyTransaction.objects.filter(user_id=uid)
    earned = txns.filter(amount__gt=0).aggregate(s=Sum("amount"))["s"] or 0
    spent = txns.filter(amount__lt=0).aggregate(s=Sum("amount"))["s"] or 0
    orders_agg = Order.objects.filter(user_id=uid).aggregate(
        c=Count("id"), total=Sum("total")
    )
    return {
        "runs": {
            "count": runs_agg["c"] or 0,
            "totalKm": round((km_agg["d"] or 0) / 1000.0, 1),
        },
        "loyalty": {
            "balance": balance_of(uid),
            "earned": int(earned),
            "spent": int(-spent),  # положительное число потраченного
        },
        "orders": {
            "count": orders_agg["c"] or 0,
            "totalSpent": int(orders_agg["total"] or 0),
        },
        # Квартал 2.0 (Ф4): ближайшая веха км и недельный стрик с заморозкой.
        "milestone": _milestone_block((km_agg["d"] or 0) / 1000.0),
        "streak": _streak_block(uid),
    }


def _milestone_block(total_km):
    from runs.milestones import next_milestone

    return next_milestone(total_km)


def _streak_block(uid):
    from league.streaks import week_streak

    return week_streak(uid)


@api_view(["GET"])
def account_export(request):
    """Выгрузка ВСЕХ персональных данных пользователя (152-ФЗ, LR §2 «портируемость»).
    Зеркало delete_account: всё, что удаляется, — экспортируется. Отдаём JSON-файлом."""
    uid = user_id_from_request(request)
    if not uid:
        return Response({"detail": "Нет токена"}, status=401)
    acc = Account.objects.filter(id=uid).first()
    if not acc:
        return Response({"detail": "Пользователь не найден"}, status=404)

    from django.db import connection

    from analytics.models import Event
    from clubs.models import Club, ClubJoinRequest, ClubMember
    from legal.models import UserConsent
    from loyalty.models import LoyaltyTransaction, balance_of
    from notifications.models import Notification
    from orders.models import Order
    from runs.models import Run
    from shoes.models import ShoeAsset

    def rows(qs):
        return list(qs.values())  # DRF-JSON сериализует datetime/Decimal сам

    data = {
        "userId": uid,
        "profile": acc.to_json(),
        "loyalty": {
            "balance": balance_of(uid),
            "transactions": [
                t.to_json() for t in
                LoyaltyTransaction.objects.filter(user_id=uid).order_by("created_at")
            ],
        },
        "orders": [
            o.to_json() for o in Order.objects.filter(user_id=uid).order_by("created_at")
        ],
        "runs": rows(Run.objects.filter(user_id=uid).order_by("created_at")),
        "shoes": rows(ShoeAsset.objects.filter(user_id=uid)),
        "notifications": rows(Notification.objects.filter(user_id=uid).order_by("created_at")),
        "consents": rows(UserConsent.objects.filter(user_id=uid)),
        "clubMemberships": rows(ClubMember.objects.filter(user_id=uid)),
        "clubJoinRequests": rows(ClubJoinRequest.objects.filter(user_id=uid)),
        "ownedClubs": rows(Club.objects.filter(owner_id=uid)),
        "analyticsEvents": [
            e.to_json() for e in Event.objects.filter(user_id=uid).order_by("created_at")
        ],
    }
    # Гео (PostGIS, raw SQL): суммарная площадь территорий + вечный след.
    with connection.cursor() as cur:
        cur.execute(
            "SELECT COALESCE(SUM(ST_Area(geom::geography)),0) FROM territories WHERE owner_id=%s",
            [uid],
        )
        terr = cur.fetchone()[0] or 0
        cur.execute(
            "SELECT COALESCE(ST_Area(geom::geography),0) FROM footprints WHERE owner_id=%s",
            [uid],
        )
        fp_row = cur.fetchone()
        cur.execute("SELECT now()")
        now = cur.fetchone()[0]
    data["territoriesAreaM2"] = round(terr)
    data["footprintAreaM2"] = round((fp_row[0] if fp_row else 0) or 0)
    data["exportedAt"] = now.isoformat()

    resp = Response(data)
    resp["Content-Disposition"] = 'attachment; filename="mata_data_export.json"'
    return resp


@api_view(["POST"])
def delete_account(request):
    """Удаление аккаунта и всех персональных данных пользователя (152-ФЗ, LR §13).
    Требует Bearer + тело {"confirm": true}. Необратимо."""
    uid = user_id_from_request(request)
    if not uid:
        return Response({"detail": "Нет токена"}, status=401)
    acc = Account.objects.filter(id=uid).first()
    if not acc:
        return Response({"detail": "User not found"}, status=404)
    if request.data.get("confirm") is not True:
        return Response({"detail": "Требуется подтверждение: {confirm: true}"}, status=400)

    from django.db import connection
    from clubs.models import Club, ClubJoinRequest, ClubMember
    from legal.models import UserConsent
    from loyalty.models import LoyaltyTransaction
    from notifications.models import Notification
    from orders.models import Order
    from runs.models import Run
    from shoes.models import ShoeAsset

    # Клуб во владении с другими участниками — нельзя удалить «молча».
    owned = Club.objects.filter(owner_id=uid)
    for club in owned:
        others = ClubMember.objects.filter(club_id=club.id).exclude(user_id=uid).exists()
        if others:
            return Response(
                {"detail": "Вы владелец клуба с участниками — передайте или распустите клуб"},
                status=409,
            )

    deleted = {}
    # Клубы во владении (без чужих участников) — распускаем целиком.
    owned_ids = list(owned.values_list("id", flat=True))
    if owned_ids:
        ClubMember.objects.filter(club_id__in=owned_ids).delete()
        ClubJoinRequest.objects.filter(club_id__in=owned_ids).delete()
        deleted["clubs"] = owned.delete()[0]
    # Членство/заявки пользователя в чужих клубах.
    deleted["clubMemberships"] = ClubMember.objects.filter(user_id=uid).delete()[0]
    deleted["clubRequests"] = ClubJoinRequest.objects.filter(user_id=uid).delete()[0]
    # Личные данные по сервисам.
    deleted["loyalty"] = LoyaltyTransaction.objects.filter(user_id=uid).delete()[0]
    deleted["orders"] = Order.objects.filter(user_id=uid).delete()[0]
    deleted["runs"] = Run.objects.filter(user_id=uid).delete()[0]  # история забегов = ПДн (GPS)
    deleted["shoes"] = ShoeAsset.objects.filter(user_id=uid).delete()[0]
    deleted["notifications"] = Notification.objects.filter(user_id=uid).delete()[0]
    deleted["consents"] = UserConsent.objects.filter(user_id=uid).delete()[0]
    # Гео (PostGIS, raw SQL): территории + вечный след.
    with connection.cursor() as cur:
        cur.execute("DELETE FROM territories WHERE owner_id=%s", [uid])
        deleted["territories"] = cur.rowcount
        cur.execute("DELETE FROM footprints WHERE owner_id=%s", [uid])
        deleted["footprints"] = cur.rowcount
    # Сам аккаунт.
    acc.delete()
    return Response({"ok": True, "deleted": deleted})


@api_view(["GET"])
def me_digest(request):
    """Итоги недели (Квартал 2.0, Ф7): км, пробежки, баллы, территория.

    Приложение показывает дайджест и планирует локальное напоминание вс 20:00 —
    настоящий пуш подключится вместе с FCM-аккаунтом.
    """
    uid = user_id_from_request(request)
    if not uid:
        return Response({"detail": "Нет токена"}, status=401)

    from datetime import datetime, timezone as dt_tz

    from django.db import connection
    from django.db.models import Count, Sum

    from league.services import period_start
    from loyalty.models import LoyaltyTransaction
    from runs.models import Run

    week_start = period_start("week")
    week_agg = Run.objects.filter(
        user_id=uid, flagged=False, finished_at__gte=week_start
    ).aggregate(d=Sum("distance_m"), c=Count("id"))
    earned = (
        LoyaltyTransaction.objects.filter(
            user_id=uid, amount__gt=0, created_at__gte=week_start
        ).aggregate(s=Sum("amount"))["s"]
        or 0
    )

    territories = {"count": 0, "areaM2": 0.0, "expiringSoon": []}
    with connection.cursor() as cur:
        cur.execute(
            """
            SELECT ST_Area(geom::geography),
                   EXTRACT(EPOCH FROM (captured_at + make_interval(hours => 168)
                           - now())) / 3600.0
            FROM territories
            WHERE owner_id = %s
              AND captured_at > now() - make_interval(hours => 168)
            """,
            [uid],
        )
        for area, hours_left in cur.fetchall():
            territories["count"] += 1
            territories["areaM2"] += float(area or 0)
            if hours_left is not None and hours_left < 48:
                territories["expiringSoon"].append(
                    {
                        "areaM2": round(float(area or 0), 1),
                        "hoursLeft": round(float(hours_left), 1),
                    }
                )
    territories["areaM2"] = round(territories["areaM2"], 1)
    territories["expiringSoon"] = sorted(
        territories["expiringSoon"], key=lambda x: x["hoursLeft"]
    )[:5]

    return Response(
        {
            "weekStartMs": int(week_start.timestamp() * 1000),
            "weekKm": round((week_agg["d"] or 0) / 1000.0, 2),
            "weekRuns": week_agg["c"] or 0,
            "earnedPoints": int(earned),
            "territories": territories,
            "generatedAtMs": int(
                datetime.now(dt_tz.utc).timestamp() * 1000
            ),
        }
    )
