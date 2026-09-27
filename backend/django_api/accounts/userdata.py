"""Реестр данных пользователя: что удалить, что обезличить, что выгрузить (аудит A04).

Раньше удаление и выгрузка аккаунта держали каждая свой ручной список моделей.
Новые модули (друзья, тропы, тренировки, медали, лиги…) в эти списки не попадали:
после удаления аккаунта их данные оставались, а в выгрузке их не было. Связи у нас
строковые (`user_id` — CharField, не ForeignKey), так что каскада нет.

Теперь список один — здесь. По нему работают `delete_account`, `account_export` и
`clean_orphans`, а тест `test_registry_covers_every_user_field` падает, если в
проекте появилась модель с полем пользователя, которой нет ни в реестре, ни в
исключениях. Забыть новый модуль больше не получится.

Политика (решение для владельца — docs/DECISIONS.md, D-103):
- DELETE — личные данные: забеги, треки, друзья, позиции, устройства, медали…
- ANON — финансовый и учётный след: проводки баллов, оплаченные заказы, реестр
  учтённых тренировок, события аналитики. Строка остаётся (бухгалтерия, 1С,
  сверка платежей), но связь с человеком рвётся: user_id заменяется меткой
  `del_<хэш>`, персональные поля заказа стираются. Неоплаченные заказы — удаляются.
"""
import hashlib

from django.apps import apps
from django.db import connection, transaction
from django.db.models import Q

DELETE = "delete"
ANON = "anon"

# (метка в выгрузке, модель, поля пользователя, политика).
MODELS = (
    ("runs", "runs.Run", ("user_id",), DELETE),
    ("trailTracks", "trails.PendingTrack", ("user_id",), DELETE),
    ("trailAttempts", "trails.TrailAttempt", ("user_id",), DELETE),
    ("externalWorkouts", "workouts.ExternalWorkout", ("user_id",), DELETE),
    ("workoutAwards", "workouts.WorkoutAward", ("user_id",), ANON),
    ("shoes", "shoes.ShoeAsset", ("user_id",), DELETE),
    ("medals", "medals.MedalAward", ("user_id",), DELETE),
    ("runnerProfile", "league.RunnerProfile", ("user_id",), DELETE),
    ("divisionMemberships", "league.DivisionMember", ("user_id",), DELETE),
    ("seasonResults", "league.SeasonResult", ("user_id",), DELETE),
    ("friendships", "friends.Friendship", ("requester_id", "addressee_id"), DELETE),
    ("friendMapPrefs", "friends.FriendMapPrefs", ("user_id",), DELETE),
    ("friendPosition", "friends.FriendPosition", ("user_id",), DELETE),
    ("notifications", "notifications.Notification", ("user_id",), DELETE),
    ("deviceTokens", "notifications.DeviceToken", ("user_id",), DELETE),
    ("devices", "notifications.DeviceAccount", ("user_id",), DELETE),
    ("reviews", "catalog.Review", ("user_id",), DELETE),
    ("consents", "legal.UserConsent", ("user_id",), DELETE),
    ("clubMemberships", "clubs.ClubMember", ("user_id",), DELETE),
    ("clubJoinRequests", "clubs.ClubJoinRequest", ("user_id",), DELETE),
    # Клубы во владении: удаление решает delete_account (с чужими участниками — 409).
    ("ownedClubs", "clubs.Club", ("owner_id",), DELETE),
    ("loyaltyTransactions", "loyalty.LoyaltyTransaction", ("user_id",), ANON),
    ("analyticsEvents", "analytics.Event", ("user_id",), ANON),
    ("orders", "orders.Order", ("user_id",), ANON),  # оплаченные — ANON, прочие — DELETE
)

# Модели с полем «пользователь», которые сознательно НЕ входят в данные клиента.
EXCLUDED = {
    "staff.StaffProfile": "сотрудник админки (Django User), не клиент",
    "staff.TabPermission": "права сотрудника",
    "staff.OwnerPin": "закрепление владельца админки",
    "core.AdminColumns": "настройки колонок сотрудника",
    "integrations.OneCExchange": "журнал обмена; kept_by_owner — это «владелец магазина»",
    "admin.LogEntry": "журнал действий сотрудников в админке",
    "otp_totp.TOTPDevice": "2FA сотрудника админки",
    "otp_static.StaticDevice": "резервные коды 2FA сотрудника",
}

# Таблицы PostGIS без моделей: (метка, таблица, колонки владельца).
RAW_TABLES = (
    ("territories", "territories", ("owner_id",)),
    ("footprint", "footprints", ("owner_id",)),
    ("blockOwnership", "block_ownership", ("owner_id",)),
    ("homeBlock", "home_block", ("owner_id",)),
    ("processedCaptures", "processed_captures", ("owner_id",)),
    ("recentCaptures", "recent_captures", ("owner_id",)),
    ("territoryEvents", "territory_events", ("victim_owner", "attacker")),
)

# Персональные поля оформления заказа — стираются при обезличивании.
CHECKOUT_PII = ("name", "phone", "email", "city", "street", "house", "apartment",
                "postalCode", "address", "comment", "recipient")

# Заказ с движением денег или уже ушедший в 1С — финансовый документ, его храним.
PAID_STATUSES = ("paid", "refunded", "partially_refunded")


def tombstone(uid: str) -> str:
    """Метка вместо user_id у обезличенных строк: одна на человека (строки одного
    бывшего клиента остаются связаны между собой — нужно для сверок), но по ней
    не восстановить, чей это был аккаунт."""
    return "del_" + hashlib.sha256(f"mata-erased:{uid}".encode()).hexdigest()[:24]


def _model(label):
    try:
        return apps.get_model(label)
    except LookupError:
        return None  # модуль ещё не в этой сборке — просто пропускаем


def _q(fields, uid):
    q = Q()
    for f in fields:
        q |= Q(**{f: uid})
    return q


def _table_exists(table) -> bool:
    return table in connection.introspection.table_names()


def export(uid: str) -> dict:
    """Все данные человека по реестру (для выгрузки 152-ФЗ)."""
    out = {}
    for label, model_label, fields, _policy in MODELS:
        model = _model(model_label)
        if model is None:
            continue
        qs = model.objects.filter(_q(fields, uid))
        if hasattr(model, "to_json") and model_label in ("orders.Order",
                                                         "loyalty.LoyaltyTransaction",
                                                         "analytics.Event"):
            out[label] = [row.to_json() for row in qs]
        else:
            out[label] = list(qs.values())
    with connection.cursor() as cur:
        for label, table, cols in RAW_TABLES:
            if not _table_exists(table):
                continue
            where = " OR ".join(f"{c}=%s" for c in cols)
            cur.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}", [uid] * len(cols))
            out[label] = {"rows": cur.fetchone()[0]}
    return out


def _anonymize_orders(model, uid, tomb) -> dict:
    mine = model.objects.filter(user_id=uid)
    keep = mine.filter(Q(payment_status__in=PAID_STATUSES) | Q(onec_taken_at__isnull=False))
    kept = 0
    for order in keep:
        payload = dict(order.payload or {})
        checkout = dict(payload.get("checkoutData") or {})
        for key in CHECKOUT_PII:
            if key in checkout:
                checkout[key] = ""
        payload["checkoutData"] = checkout
        order.payload = payload
        order.user_id = tomb
        order.courier_note = ""
        order.save(update_fields=["payload", "user_id", "courier_note"])
        kept += 1
    deleted = mine.exclude(pk__in=keep.values("pk")).delete()[0]
    return {"anonymized": kept, "deleted": deleted}


def erase(uid: str) -> dict:
    """Удалить/обезличить всё по реестру. Вызывать внутри transaction.atomic()."""
    tomb = tombstone(uid)
    report = {}
    for label, model_label, fields, policy in MODELS:
        model = _model(model_label)
        if model is None:
            continue
        if model_label == "orders.Order":
            report[label] = _anonymize_orders(model, uid, tomb)
        elif policy == ANON:
            new = "" if model_label == "analytics.Event" else tomb
            report[label] = {"anonymized": model.objects.filter(_q(fields, uid))
                             .update(**{fields[0]: new})}
        else:
            report[label] = model.objects.filter(_q(fields, uid)).delete()[0]
    with connection.cursor() as cur:
        for label, table, cols in RAW_TABLES:
            if not _table_exists(table):
                continue
            where = " OR ".join(f"{c}=%s" for c in cols)
            cur.execute(f"DELETE FROM {table} WHERE {where}", [uid] * len(cols))
            report[label] = cur.rowcount
    return report


def erase_atomic(uid: str) -> dict:
    with transaction.atomic():
        return erase(uid)
