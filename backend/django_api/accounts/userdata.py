"""Реестр данных пользователя: что удалить и что выгрузить (аудит A04).

Раньше удаление и выгрузка аккаунта держали каждая свой ручной список моделей.
Новые модули (друзья, тропы, тренировки, медали, лиги…) в эти списки не попадали:
после удаления аккаунта их данные оставались, а в выгрузке их не было. Связи у нас
строковые (`user_id` — CharField, не ForeignKey), так что каскада нет.

Теперь список один — здесь. По нему работают `delete_account`, `account_export` и
`clean_orphans`, а тест `test_registry_covers_every_user_field` падает, если в
проекте появилась модель с полем пользователя, которой нет ни в реестре, ни в
исключениях. Забыть новый модуль больше не получится.

Политика (решение владельца 28.09.2026, docs/DECISIONS.md D-104):
- Удалить аккаунт можно, только когда все покупки завершены: оплаченный заказ
  получен и прошёл срок возврата (7 дней после получения), возвратов в работе нет.
- При удалении стирается ВСЁ: заказы, баллы, забеги, треки, друзья, устройства…
- Для статистики остаётся только то, что не указывает на человека: строки продаж
  (`analytics.SaleLine` — что купили, размер, цвет, цена, дата; пишутся при оплате)
  и события аналитики без id пользователя.
"""
from datetime import timedelta

from django.apps import apps
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone

DELETE = "delete"
ANON = "anon"  # строка остаётся, связь с человеком стирается

# Срок возврата товара при онлайн-продаже (D-73): 7 дней после получения.
RETURN_WINDOW = timedelta(days=7)

# (метка в выгрузке, модель, поля пользователя, политика).
MODELS = (
    ("runs", "runs.Run", ("user_id",), DELETE),
    ("trailTracks", "trails.PendingTrack", ("user_id",), DELETE),
    ("trailAttempts", "trails.TrailAttempt", ("user_id",), DELETE),
    ("externalWorkouts", "workouts.ExternalWorkout", ("user_id",), DELETE),
    ("workoutAwards", "workouts.WorkoutAward", ("user_id",), DELETE),
    ("captureAwards", "territories.CaptureAward", ("user_id",), DELETE),
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
    ("loyaltyTransactions", "loyalty.LoyaltyTransaction", ("user_id",), DELETE),
    # Программа лояльности v1: лоты, уровень, списания на заказы (части — каскадом).
    # Журнал `loyalty.LoyaltyEvent` поля пользователя не имеет — только псевдоним из
    # Account.loyalty_pseudonym; он стирается вместе с аккаунтом, и журнал остаётся
    # обезличенным (ТЗ §5, решение координатора).
    ("loyaltyLots", "loyalty.LoyaltyLot", ("user_id",), DELETE),
    ("loyaltyLevel", "loyalty.LoyaltyStatus", ("user_id",), DELETE),
    ("loyaltyRedemptions", "loyalty.LoyaltyRedemption", ("user_id",), DELETE),
    ("orders", "orders.Order", ("user_id",), DELETE),  # возвраты уходят каскадом
    ("analyticsEvents", "analytics.Event", ("user_id",), ANON),
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

# Оплата прошла, деньги у магазина — покупка ещё может вернуться.
_PAID = ("paid", "partially_refunded")


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


def _delivered_at(order):
    """Когда заказ получен — или None, если ещё не получен."""
    if order.onec_status == "delivered":
        return order.onec_status_at or order.created_at
    if order.status == "delivered":
        return order.onec_status_at or order.created_at
    return None


def blocking_reason(uid, now=None) -> str:
    """Почему аккаунт пока нельзя удалить (пусто — можно).

    Пока покупка не завершена, заказ нужен и складу (адрес, телефон), и для
    возврата денег: удалить его сейчас — оставить человека без доставки и возврата.
    """
    from orders.models import Order, OrderReturn

    now = now or timezone.now()
    if OrderReturn.objects.filter(order__user_id=uid).exclude(
            status__in=("done", "failed", "canceled")).exists():
        return "Идёт возврат по заказу — удалить аккаунт можно после его завершения"
    for order in Order.objects.filter(user_id=uid):
        if order.payment_status == "pending":
            return "Заказ ждёт оплаты — удалить аккаунт можно после оплаты или отмены"
        if order.payment_status not in _PAID or order.status == "cancelled":
            continue
        got = _delivered_at(order)
        if got is None:
            return ("Заказ ещё не получен — удалить аккаунт можно через 7 дней после "
                    "получения (срок возврата)")
        if now < got + RETURN_WINDOW:
            days = max(1, (got + RETURN_WINDOW - now).days + 1)
            return (f"Идёт срок возврата по заказу — удалить аккаунт можно через "
                    f"{days} дн.")
    return ""


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


def erase(uid: str) -> dict:
    """Удалить всё по реестру. Вызывать внутри transaction.atomic()."""
    from analytics import sales
    from orders.models import Order

    # Статистика продаж пишется при оплате; на всякий случай дописываем перед удалением
    # (заказы, оплаченные до появления статистики и не попавшие в перенос).
    for order in Order.objects.filter(user_id=uid, payment_status__in=sales.SOLD):
        sales.record(order)

    report = {}
    for label, model_label, fields, policy in MODELS:
        model = _model(model_label)
        if model is None:
            continue
        rows = model.objects.filter(_q(fields, uid))
        if policy == ANON:
            report[label] = {"anonymized": rows.update(**{fields[0]: ""})}
        else:
            report[label] = rows.delete()[0]
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
