"""Программа лояльности v1 — ядро на сервере (ТЗ владельца 30.09.2026, этап 1).

Одна валюта — бонус (целое, 1 бонус = 1 ₽). Баланс — набор ЛОТОВ (`LoyaltyLot`):
одно начисление = один лот с остатком, состоянием и датой сгорания. Числа —
в настройках (`loyalty.config`), правила — здесь.

Выключатель — настройка LOYALTY_V1_ENABLED (по умолчанию ВЫКЛ):
- выключено — баллы работают по-старому (реестр `LoyaltyTransaction`);
- включено — покупка, списание, возврат, удержание, сгорание, уровни — по v1.

Как совмещены два реестра (без двойного счёта):
- `LoyaltyTransaction` — прежний реестр. При включённой v1 он становится историей
  и продолжает получать записи от кода, который ещё не переведён (бег, захват —
  этап 2).
- Человек попадает в v1 ПЕРЕНОСОМ (`migrate_user`: команда `loyalty_migrate_v1`
  или лениво при первом обращении к v1): его баланс по старому реестру на этот
  момент становится лотом `migration`, начисления за 365 дней — статусными
  (`legacy_history`), и заводится строка `LoyaltyStatus`.
- С момента переноса каждая НОВАЯ запись старого реестра по этому человеку
  зеркалится в лоты (`mirror_legacy`, сигнал post_save): плюс — лот, минус —
  списание из лотов. Перенос и зеркало идут под одним замком кошелька, поэтому
  запись либо вошла в перенесённый баланс, либо зеркалится — не то и другое.
- Операции v1 (покупка, списание, возврат) в старый реестр не пишут.
Итого при включённой v1 баланс = лоты, и ни одна операция не считается дважды.

Блокировка — та же, что у старого кошелька (`loyalty.wallet.lock_wallet`,
pg_advisory_xact_lock по пользователю): одна схема на оба реестра.
"""
import calendar
import hashlib
import json
import logging
import secrets
from collections import defaultdict
from datetime import timedelta
from decimal import ROUND_FLOOR, Decimal

from django.db import transaction
from django.db.models import F, Max, Q, Sum
from django.utils import timezone

from . import config
from .models_v1 import (
    LoyaltyEvent,
    LoyaltyLot,
    LoyaltyRedemption,
    LoyaltyRedemptionPart,
    LoyaltyReserve,
    LoyaltyRuleSnapshot,
    LoyaltyStatus,
)
from .wallet import lock_wallet

log = logging.getLogger(__name__)

BASIC, SILVER, GOLD, PLATINUM = 0, 1, 2, 3
HELD, AVAILABLE, SPENT, EXPIRED, CANCELLED = (
    LoyaltyLot.HELD, LoyaltyLot.AVAILABLE, LoyaltyLot.SPENT, LoyaltyLot.EXPIRED,
    LoyaltyLot.CANCELLED)

# Источники лотов.
PURCHASE = "purchase"
MIGRATION = "migration"          # баланс старого реестра на момент переноса
HISTORY = "legacy_history"       # начисления старого реестра за 365 дней → статусные
LEGACY = "legacy"                # зеркало записи старого реестра (не активность)
LEGACY_ACTIVITY = "legacy_activity"  # зеркало начисления за бег/захват
DEBT = "debt"                    # отрицательный остаток после возврата товара
MANUAL = "manual"
# Лоты за активность: пока аккаунт на проверке (needs_review), их не тратят
# (D-107, «заморозка при needs_review остаётся»).
ACTIVITY_LOTS = frozenset({LEGACY_ACTIVITY, "run", "capture", "stage"})

# Старый реестр: что шло в «статусные» (заработано действием или покупкой) и что
# их отменяло. Регистрация/бонус первого заказа, возврат списанного, ручные
# правки статусными не считаются (ТЗ §2: кроме BONUS_SIGNUP и отменённых).
LEGACY_STATUS_SOURCES = frozenset({
    "purchase", "runnerRun", "runnerTerritory", "runnerMilestone", "runnerDivision",
    "runnerSeason", "runnerCompetition",
})
LEGACY_STATUS_REVOKES = frozenset({
    "purchase_revoke", "runnerRunRevoked", "runnerTerritoryRevoked",
})
_LEGACY_EVENT = {
    "purchase": "accrue_purchase", "runnerRun": "accrue_run",
    "runnerTerritory": "accrue_capture", "runnerMilestone": "accrue_stage",
    "runnerDivision": "accrue_stage", "runnerSeason": "accrue_stage",
    "runnerCompetition": "accrue_stage", "registration": "accrue_signup",
    "redeem_refund": "redeem_return", "redeem": "redeem",
}
# Начисления старого кода, которые при включённой v1 прекращаются (решение
# координатора: вехи/медали, дивизион, сезон, бонус первого заказа, демо).
STOPPED_LEGACY_SOURCES = frozenset({
    "runnerMilestone", "runnerDivision", "runnerSeason",
})

_LEVEL_TEXT = {
    SILVER: ("Новый уровень: Серебро", "Вы достигли уровня «Серебро»."),
    GOLD: ("Новый уровень: Золото", "Вы достигли уровня «Золото»."),
    PLATINUM: ("Новый уровень: Платина", "Вы достигли уровня «Платина»."),
}


class RedeemError(Exception):
    pass


# ── мелочи ────────────────────────────────────────────────────────────────────

def legacy_award_allowed(source) -> bool:
    """Можно ли старому коду начислить баллы из этого источника (при включённой v1
    вехи/дивизион/сезон больше не начисляются)."""
    return not (source in STOPPED_LEGACY_SOURCES and config.enabled())


def add_months(dt, months: int):
    """Дата + N календарных месяцев по местному времени (31 янв + 1 = 28/29 фев)."""
    local = timezone.localtime(dt)
    y, m = divmod(local.month - 1 + int(months), 12)
    year, month = local.year + y, m + 1
    day = min(local.day, calendar.monthrange(year, month)[1])
    return local.replace(year=year, month=month, day=day)


def expires_for(accrued_at, level: int):
    return add_months(accrued_at, config.by_level("EXPIRY_MONTHS", level))


def delivery_kop(payload) -> int:
    from orders.money import to_kop

    try:
        return max(0, to_kop((payload or {}).get("deliveryCost") or 0))
    except (ValueError, AttributeError):
        return 0


def _rub(kop):
    if kop is None:
        return None
    return (Decimal(int(kop)) / 100).quantize(Decimal("0.01"))


def _floor(value: Decimal) -> int:
    return int(value.to_integral_value(rounding=ROUND_FLOOR))


def pseudonym(uid) -> str:
    """Постоянный случайный псевдоним человека для журнала (хранится в Account)."""
    from accounts.models import Account

    acc = Account.objects.filter(id=uid).only("id", "loyalty_pseudonym").first()
    if acc is None:
        # Служебный uid без аккаунта (удалён, тестовый) — связи с человеком нет.
        return "anon_" + secrets.token_hex(8)
    if not acc.loyalty_pseudonym:
        Account.objects.filter(id=uid, loyalty_pseudonym="").update(
            loyalty_pseudonym="lp_" + secrets.token_hex(12))
        acc.refresh_from_db(fields=["loyalty_pseudonym"])
    return acc.loyalty_pseudonym


def rule_version() -> str:
    """Версия правил: версия ТЗ + хэш слепка констант; сам слепок — в таблице."""
    snap = config.snapshot()
    raw = json.dumps(snap, sort_keys=True, ensure_ascii=False)
    version = f"{config.RULES_VERSION}:{hashlib.sha1(raw.encode()).hexdigest()[:10]}"
    LoyaltyRuleSnapshot.objects.get_or_create(version=version, defaults={"constants": snap})
    return version


def _reserve(bonuses: int) -> None:
    """reserve_rub += bonuses × RESERVE_PER_BONUS (со знаком)."""
    if not bonuses:
        return
    per = Decimal(str(config.get("RESERVE_PER_BONUS")))
    delta = (per * bonuses).quantize(Decimal("0.01"))
    LoyaltyReserve.objects.get_or_create(id=1)
    LoyaltyReserve.objects.filter(id=1).update(reserve_rub=F("reserve_rub") + delta)


def reserve_rub() -> Decimal:
    row = LoyaltyReserve.objects.filter(id=1).first()
    return row.reserve_rub if row else Decimal("0.00")


def _invalidate(uid):
    from common.cache import invalidate_user

    invalidate_user(uid)


def _notify(uid, title, body, kind="system"):
    if not config.enabled():
        return  # пока программа выключена, лоты — тень старого реестра: молчим
    try:
        from notifications.models import create_notification

        create_notification(uid, title, body, type=kind)
    except Exception:  # уведомление не часть операции
        log.exception("Уведомление лояльности не ушло")


# ── агрегаты кошелька ────────────────────────────────────────────────────────

def purchases_rub(uid, now=None) -> int:
    """Покупки за 365 дней (для Платины): денежная часть оплаченных и не
    возвращённых заказов — сумма минус бонусы (они уже вычтены из total) минус
    доставка минус проведённые возвраты. Тестовые заказы (оплата без денег) — нет."""
    from orders.models import Order

    now = now or timezone.now()
    since = now - timedelta(days=config.STATUS_WINDOW_DAYS)
    rows = (Order.objects.filter(user_id=uid, payment_status__in=("paid", "partially_refunded"),
                                 is_test=False, created_at__gt=since)
            .exclude(status="cancelled").prefetch_related("returns"))
    total = 0
    for order in rows:
        back = sum(r.amount_kop for r in order.returns.all() if r.status == "done")
        total += max(0, order.amount_kop - delivery_kop(order.payload) - back)
    return total // 100


def status_points(uid, now=None) -> int:
    now = now or timezone.now()
    since = now - timedelta(days=config.STATUS_WINDOW_DAYS)
    return LoyaltyLot.objects.filter(user_id=uid, accrued_at__gt=since).exclude(
        state=CANCELLED).aggregate(s=Sum("status_amount"))["s"] or 0


def level_target(status: int, purchases_fn) -> int:
    """Уровень по статусным (и покупкам — для Платины). `purchases_fn` зовётся,
    только если статусных хватает на Платину."""
    th = config.get("LEVEL_THRESHOLD")
    level = BASIC
    if status >= th[0]:
        level = SILVER
    if status >= th[1]:
        level = GOLD
    if status >= th[2] and purchases_fn() >= config.get("PLATINUM_MIN_SPEND"):
        level = PLATINUM
    return level


def _balances(uid):
    agg = LoyaltyLot.objects.filter(user_id=uid).aggregate(
        available=Sum("remaining", filter=Q(state=AVAILABLE)),
        held=Sum("remaining", filter=Q(state=HELD)),
    )
    return agg["available"] or 0, agg["held"] or 0


def _on_review(uid) -> bool:
    from accounts.models import Account

    return Account.objects.filter(id=uid, needs_review=True).exists()


def redeemable(uid) -> int:
    """Сколько можно списать: доступно минус замороженная активность (аккаунт на
    проверке), не меньше нуля."""
    available, _ = _balances(uid)
    frozen = 0
    if _on_review(uid):
        frozen = LoyaltyLot.objects.filter(
            user_id=uid, state=AVAILABLE, source__in=ACTIVITY_LOTS, remaining__gt=0,
        ).aggregate(s=Sum("remaining"))["s"] or 0
    return max(0, available - frozen)


def wallet(uid, now=None) -> dict:
    """Кошелёк v1: доступно, ожидает, статусные, покупки, уровень, ближайшие даты."""
    now = now or timezone.now()
    st = get_status(uid, now)
    available, held = _balances(uid)
    status = status_points(uid, now)
    frozen = _on_review(uid)
    lots = LoyaltyLot.objects.filter(user_id=uid)
    next_at, next_amount = None, 0
    nxt = lots.filter(state=HELD, available_at__isnull=False).order_by("available_at").first()
    if nxt is not None:
        day = timezone.localtime(nxt.available_at).date()
        next_at = nxt.available_at
        next_amount = sum(
            lot.remaining for lot in lots.filter(state=HELD, available_at__isnull=False)
            if timezone.localtime(lot.available_at).date() == day)
    exp = lots.filter(state=AVAILABLE, remaining__gt=0, expires_at__isnull=False).order_by(
        "expires_at").first()
    expiring_at, expiring_amount = None, 0
    if exp is not None:
        day = timezone.localtime(exp.expires_at).date()
        expiring_at = exp.expires_at
        expiring_amount = sum(
            lot.remaining for lot in lots.filter(state=AVAILABLE, remaining__gt=0,
                                                 expires_at__isnull=False)
            if timezone.localtime(lot.expires_at).date() == day)
    th = config.get("LEVEL_THRESHOLD")
    return {
        "available": available,
        "redeemable": redeemable(uid),
        "held": held,
        "frozen": frozen,
        "status_points": status,
        "purchases_rub": purchases_rub(uid, now),
        "level": st.level,
        "level_name": config.LEVELS[st.level],
        "level_until": st.level_until,
        "next_level_threshold": th[st.level] if st.level < PLATINUM else None,
        "platinum_min_spend": config.get("PLATINUM_MIN_SPEND"),
        "redeem_min": config.get("REDEEM_MIN"),
        "redeem_ceiling": config.redeem_ceiling(st.level),
        "next_at": next_at,
        "next_amount": next_amount,
        "expiring_at": expiring_at,
        "expiring_amount": expiring_amount,
    }


# ── журнал ───────────────────────────────────────────────────────────────────

def _event(uid, type_, amount, *, now, level_before, st=None, lot=None, source_ref="",
           order_total_kop=None, eligible_kop=None, cash_kop=None, partner_id="", note=""):
    st = st or LoyaltyStatus.objects.filter(user_id=uid).first()
    available, _ = _balances(uid)
    LoyaltyEvent.objects.create(
        user_pseudonym=pseudonym(uid),
        type=type_,
        amount=int(amount),
        balance_after=available,
        status_points_after=status_points(uid, now),
        level_at_event=level_before,
        level_after=st.level if st else level_before,
        lot_id=lot.pk if lot is not None else None,
        lot_expires_at=lot.expires_at if lot is not None else None,
        source_ref=str(source_ref or (lot.source_ref if lot is not None else ""))[:80],
        order_total=_rub(order_total_kop),
        eligible_total=_rub(eligible_kop),
        cash_part=_rub(cash_kop),
        partner_id=partner_id,
        rule_version=rule_version(),
        note=note[:300],
    )


# ── уровень ──────────────────────────────────────────────────────────────────

def get_status(uid, now=None) -> LoyaltyStatus:
    """Строка уровня человека; нет — перенос в v1 (под замком кошелька)."""
    st = LoyaltyStatus.objects.filter(user_id=uid).first()
    if st is not None:
        return st
    with transaction.atomic():
        lock_wallet(uid)
        return _ensure_status(uid, now or timezone.now())


def _ensure_status(uid, now) -> LoyaltyStatus:
    """Вызывать под замком кошелька."""
    st = LoyaltyStatus.objects.filter(user_id=uid).first()
    if st is None:
        migrate_user(uid, now=now, apply=True, _locked=True)
        st = LoyaltyStatus.objects.get(user_id=uid)
    return st


def _reexpire(uid, level):
    """Повышение: все активные лоты получают срок по новому уровню (от даты начисления)."""
    for lot in LoyaltyLot.objects.filter(user_id=uid, state__in=(HELD, AVAILABLE),
                                         remaining__gt=0, expires_at__isnull=False):
        new = expires_for(lot.accrued_at, level)
        if new != lot.expires_at:
            lot.expires_at = new
            lot.save(update_fields=["expires_at"])


def _check_level(uid, st, now):
    """Повышение (немедленно, перескок разрешён) и продление — при начислении."""
    target = level_target(status_points(uid, now), lambda: purchases_rub(uid, now))
    term = timedelta(days=config.STATUS_TERM_DAYS)
    if target > st.level:
        old = st.level
        st.level, st.level_until, st.level_since = target, now + term, now
        st.save(update_fields=["level", "level_until", "level_since", "updated_at"])
        _reexpire(uid, target)
        _event(uid, "level_up", 0, now=now, level_before=old, st=st)
        title, body = _LEVEL_TEXT[target]
        _notify(uid, title, body, "level")
    elif st.level > BASIC and target >= st.level:
        # Порог текущего уровня держится — срок уровня отсчитывается от сегодня.
        until = now + term
        if st.level_until is None or until > st.level_until:
            st.level_until = until
            st.save(update_fields=["level_until", "updated_at"])


def recheck_levels(now=None) -> dict:
    """Ежедневно: срок уровня прошёл и порог не держится — минус один уровень
    (не больше), новый срок +365 дней. Держится — срок продлевается."""
    now = now or timezone.now()
    stats = {"down": 0, "kept": 0}
    term = timedelta(days=config.STATUS_TERM_DAYS)
    for uid in LoyaltyStatus.objects.filter(level__gt=BASIC, level_until__lt=now).values_list(
            "user_id", flat=True):
        with transaction.atomic():
            lock_wallet(uid)
            st = LoyaltyStatus.objects.get(user_id=uid)
            if st.level == BASIC or (st.level_until and st.level_until >= now):
                continue
            target = level_target(status_points(uid, now), lambda: purchases_rub(uid, now))
            if target >= st.level:
                st.level_until = now + term
                st.save(update_fields=["level_until", "updated_at"])
                stats["kept"] += 1
                continue
            old = st.level
            st.level, st.level_until = old - 1, now + term
            st.save(update_fields=["level", "level_until", "updated_at"])
            _event(uid, "level_down", 0, now=now, level_before=old, st=st)
            _notify(uid, "Уровень изменился",
                    f"Ваш уровень теперь «{config.LEVEL_TITLES[st.level]}».", "level")
            stats["down"] += 1
        _invalidate(uid)
    return stats


# ── лоты ─────────────────────────────────────────────────────────────────────

def _create_lot(uid, st, amount, source, ref="", *, state, now, status, available_at=None,
                meta=None, accrued_at=None, expires=True):
    accrued_at = accrued_at or now
    return LoyaltyLot.objects.create(
        user_id=uid, amount=amount, remaining=amount, state=state, source=source,
        source_ref=str(ref or "")[:80], status_amount=amount if status else 0,
        accrued_at=accrued_at, available_at=available_at if state == HELD else (
            available_at or accrued_at),
        expires_at=expires_for(accrued_at, st.level) if expires else None,
        level_at_accrual=st.level, meta=meta or {},
    )


def _debit_fifo(uid, n, *, skip_frozen=False, first=None):
    """Снять n из доступных лотов: сначала `first` (лоты основания), потом по дате
    сгорания. Возвращает [(лот, сколько)] и недостачу."""
    parts = []
    if n <= 0:
        return parts, 0
    pool = list(first or [])
    qs = LoyaltyLot.objects.filter(user_id=uid, state=AVAILABLE, remaining__gt=0).order_by(
        F("expires_at").asc(nulls_last=True), "accrued_at", "id")
    if skip_frozen and _on_review(uid):
        qs = qs.exclude(source__in=ACTIVITY_LOTS)
    seen = {lot.pk for lot in pool}
    pool += [lot for lot in qs if lot.pk not in seen]
    left = n
    for lot in pool:
        if left <= 0:
            break
        take = min(left, lot.remaining)
        if take <= 0:
            continue
        lot.remaining -= take
        if lot.remaining == 0:
            lot.state = CANCELLED if lot.state == HELD else SPENT
        lot.save(update_fields=["remaining", "state"])
        parts.append((lot, take))
        left -= take
    return parts, left


def _add_debt(uid, st, n, now):
    """Недостача при возврате — баланс уходит в минус (ТЗ §4)."""
    if n <= 0:
        return None
    debt = LoyaltyLot.objects.filter(user_id=uid, source=DEBT, state=AVAILABLE,
                                     remaining__lt=0).first()
    if debt is None:
        return _create_lot(uid, st, -n, DEBT, state=AVAILABLE, now=now, status=False,
                           expires=False)
    debt.amount -= n
    debt.remaining -= n
    debt.save(update_fields=["amount", "remaining"])
    return debt


def _settle_debt(uid):
    """Долг гасится следующими доступными бонусами (баланс при этом не меняется)."""
    debts = list(LoyaltyLot.objects.filter(user_id=uid, source=DEBT, state=AVAILABLE,
                                           remaining__lt=0))
    for debt in debts:
        parts, left = _debit_fifo(uid, -debt.remaining)
        debt.remaining = -left
        if debt.remaining == 0:
            debt.state = SPENT
        debt.save(update_fields=["remaining", "state"])
        for lot, take in parts:
            meta = dict(lot.meta or {})
            meta["debt_paid"] = meta.get("debt_paid", 0) + take
            lot.meta = meta
            lot.save(update_fields=["meta"])


def _restore(lot, n, now):
    """Вернуть n бонусов в лот (с его датами). Если срок лота за это время прошёл,
    остаток сгорит ближайшей ежедневной задачей (`expire_lots`)."""
    lot.remaining += n
    if lot.state == SPENT:
        lot.state = AVAILABLE
    lot.save(update_fields=["remaining", "state"])


def accrue(uid, amount, source, ref="", *, event_type, status=True, held=False,
           available_at=None, now=None, note="", meta=None):
    """Начисление (лот). Для этапа 2 (бег, захват, этап, реферал, регистрация) и
    ручного начисления; покупка — `on_order_paid`."""
    now = now or timezone.now()
    amount = int(amount)
    if amount <= 0:
        return None
    with transaction.atomic():
        lock_wallet(uid)
        st = _ensure_status(uid, now)
        before = st.level
        lot = _create_lot(uid, st, amount, source, ref, state=HELD if held else AVAILABLE,
                          now=now, status=status, available_at=available_at, meta=meta)
        if not held:
            _settle_debt(uid)
        _reserve(amount)
        _event(uid, event_type, amount, now=now, level_before=before, st=st, lot=lot,
               note=note)
        _check_level(uid, st, now)
    _invalidate(uid)
    return lot


# ── покупка ──────────────────────────────────────────────────────────────────

def on_order_paid(order, now=None) -> None:
    """Заказ оплачен: заблокированные бонусы списываются окончательно; при
    включённой v1 — лот покупки held (идемпотентно по заказу).

    Начисление = floor(cash_part × RATE_PURCHASE[уровень на момент оплаты]),
    cash_part = сумма заказа − списанные бонусы − доставка. Тестовые заказы
    (оплата без денег, D-97) бонусов не приносят.
    """
    now = now or timezone.now()
    uid, oid = order.user_id, order.order_id
    with transaction.atomic():
        lock_wallet(uid)
        red = LoyaltyRedemption.objects.filter(user_id=uid, order_id=oid).first()
        if red is not None and red.state == LoyaltyRedemption.BLOCKED:
            red.state = LoyaltyRedemption.SPENT
            red.save(update_fields=["state", "updated_at"])
        if not config.enabled() or order.is_test:
            return
        if LoyaltyLot.objects.filter(user_id=uid, source=PURCHASE, source_ref=oid).exists():
            return
        st = _ensure_status(uid, now)
        before = st.level
        delivery = delivery_kop(order.payload)
        cash_kop = max(0, order.amount_kop - delivery)
        rate = Decimal(str(config.by_level("RATE_PURCHASE", st.level)))
        amount = _floor(Decimal(cash_kop) * rate / 100)
        order_total_kop = order.amount_kop + int(order.points_redeemed or 0) * 100
        if amount <= 0:
            return
        lot = _create_lot(uid, st, amount, PURCHASE, oid, state=HELD, now=now, status=True,
                          meta={"cashPartKop": cash_kop, "orderTotalKop": order_total_kop,
                                "deliveryKop": delivery, "revoked": 0})
        _reserve(amount)
        _event(uid, "accrue_purchase", amount, now=now, level_before=before, st=st, lot=lot,
               source_ref=oid, order_total_kop=order_total_kop,
               eligible_kop=red.eligible_kop if red else None, cash_kop=cash_kop)
        _check_level(uid, st, now)
    _invalidate(uid)


def _delivered_at(order, now):
    """Когда заказ получен; None — ещё нет. Статус «доставлен» без времени (отметка
    в админке) — считаем с момента, когда мы это увидели."""
    if order.onec_status == "delivered" and order.onec_status_at:
        return order.onec_status_at
    if order.status == "delivered":
        return order.onec_status_at or now
    return None


def release_holds(now=None) -> dict:
    """Выход из удержания. Лот покупки — не раньше max(оплата + HOLD_DAYS,
    получение + DELIVERY_RETURN_DAYS); не получен — держится (решение координатора).
    Лоты с известной датой (`available_at`) — по ней."""
    from orders.models import Order

    now = now or timezone.now()
    stats = {"released": 0, "waiting": 0}
    hold = timedelta(days=config.get("HOLD_DAYS"))
    window = timedelta(days=config.get("DELIVERY_RETURN_DAYS"))
    for lot in LoyaltyLot.objects.filter(state=HELD).order_by("id"):
        when = lot.available_at
        if when is None and lot.source == PURCHASE:
            order = Order.objects.filter(user_id=lot.user_id, order_id=lot.source_ref).first()
            got = _delivered_at(order, now) if order else None
            if got is None:
                stats["waiting"] += 1
                continue
            when = max(lot.accrued_at + hold, got + window)
            LoyaltyLot.objects.filter(pk=lot.pk, state=HELD).update(available_at=when)
        if when is None or when > now:
            stats["waiting"] += 1
            continue
        with transaction.atomic():
            lock_wallet(lot.user_id)
            lot = LoyaltyLot.objects.get(pk=lot.pk)
            if lot.state != HELD:
                continue
            lot.state = AVAILABLE
            lot.available_at = when
            lot.save(update_fields=["state", "available_at"])
            _settle_debt(lot.user_id)
            st = LoyaltyStatus.objects.filter(user_id=lot.user_id).first()
            level = st.level if st else 0
            _event(lot.user_id, "hold_release", lot.remaining, now=now, level_before=level,
                   st=st, lot=lot)
            if lot.source == PURCHASE:
                _notify(lot.user_id, "Бонусы доступны",
                        f"{lot.remaining} бонусов за покупку можно тратить в МАТА Store.")
        _invalidate(lot.user_id)
        stats["released"] += 1
    return stats


# ── списание при оформлении ──────────────────────────────────────────────────

def excluded_categories() -> set:
    """Коды групп 1С без списания — вместе со всеми подгруппами."""
    codes = set(config.get("EXCLUDED_CATEGORIES_1C"))
    if not codes:
        return set()
    from catalog.models import Category

    children = defaultdict(list)
    for cid, parent in Category.objects.values_list("id", "parent_id"):
        children[parent or ""].append(cid)
    out, stack = set(), list(codes)
    while stack:
        code = stack.pop()
        if code in out:
            continue
        out.add(code)
        stack.extend(children.get(code, []))
    return out


def eligibility(items) -> dict:
    """Какая часть корзины допускает списание (ТЗ §4).

    Цена — витрины (каталог). Не допускаются: группы 1С из EXCLUDED_CATEGORIES_1C
    (с подгруппами; сертификаты там же), уценка (old_price > price), товары не из
    каталога. Доставка не входит никогда.
    `unit_eligible_kop` — по единице товара в порядке позиций чека
    (`orders.receipt._lines`): по нему возврат делит списанные бонусы.
    """
    from catalog.models import Product
    from orders.money import to_kop
    from orders.pricing import CartError, parse_quantity

    items = items if isinstance(items, list) else []
    ids = {str(it.get("productId") or "").strip() for it in items if isinstance(it, dict)}
    products = {p.pk: p for p in Product.objects.filter(pk__in=ids - {""}).only(
        "id", "price", "old_price", "category_id")} if ids else {}
    excluded = excluded_categories()
    lines, units, eligible = [], [], 0
    for index, it in enumerate(items):
        if not isinstance(it, dict):
            continue
        pid = str(it.get("productId") or "").strip()
        try:
            qty = parse_quantity(it.get("quantity"))
        except CartError:
            qty = 1
        product = products.get(pid)
        reason = ""
        if product is None:
            reason = "not_in_catalog"
            price_kop = 0
        else:
            try:
                price_kop = to_kop(product.price)
            except ValueError:
                price_kop = 0
            if product.category_id in excluded:
                reason = "excluded_category"
            elif product.old_price and float(product.old_price) > float(product.price):
                reason = "markdown"
        line_kop = 0 if reason else price_kop * qty
        eligible += line_kop
        lines.append({"index": index, "productId": pid, "eligible": not reason,
                      "reason": reason, "eligibleKop": line_kop})
        # Позиции чека: единица товара с ценой > 0 (цена строки заказа).
        try:
            receipt_price = to_kop(it.get("price") if it.get("price") is not None else 0)
        except ValueError:
            receipt_price = 0
        if receipt_price > 0:
            units.extend([0 if reason else price_kop] * qty)
    return {"eligible_kop": eligible, "lines": lines, "unit_eligible_kop": units}


def quote(uid, items, now=None) -> dict:
    """Сколько можно списать в этом заказе: redeem_max = min(доступно,
    floor(eligible_total × REDEEM_CEILING[уровень])), потолок ≤ 0,30 кодом."""
    now = now or timezone.now()
    st = get_status(uid, now)
    elig = eligibility(items)
    ceiling = config.redeem_ceiling(st.level)
    cap = _floor(Decimal(elig["eligible_kop"]) * Decimal(str(ceiling)) / 100)
    can_spend = redeemable(uid)
    redeem_max = max(0, min(can_spend, cap))
    rmin = config.get("REDEEM_MIN")
    reason = ""
    if redeem_max < rmin:
        if can_spend < rmin:
            reason = f"Списать бонусы можно от {rmin}: сейчас доступно {can_spend}"
        else:
            reason = (f"В этом заказе можно списать до {redeem_max} бонусов — "
                      f"меньше минимума {rmin}")
    return {
        "level": st.level,
        "levelName": config.LEVELS[st.level],
        "available": can_spend,
        "eligibleTotal": float(_rub(elig["eligible_kop"])),
        "eligible_kop": elig["eligible_kop"],
        "ceiling": ceiling,
        "redeemMax": redeem_max,
        "redeemMin": rmin,
        "canRedeem": redeem_max >= rmin,
        "reason": reason,
        "lines": elig["lines"],
        "unit_eligible_kop": elig["unit_eligible_kop"],
    }


def block_for_order(uid, order_id, points, items, now=None) -> str:
    """Блок бонусов при создании заказа (ТЗ §4). Текст ошибки или "".

    Бонусы снимаются с лотов сразу (FIFO по дате сгорания, разбивка по лотам) —
    потратить их второй раз нельзя; при оплате списание становится окончательным,
    при отмене или истечении окна оплаты (15 мин, D-72) — возвращается в те же лоты.
    Повтор с той же суммой — успех без второго блока.
    """
    now = now or timezone.now()
    points = int(points or 0)
    if points <= 0:
        return ""
    if not order_id:
        return "Бонусы списываются только на заказ"
    with transaction.atomic():
        lock_wallet(uid)
        existing = LoyaltyRedemption.objects.filter(user_id=uid, order_id=order_id).first()
        if existing is not None:
            if existing.amount == points and existing.state != LoyaltyRedemption.RELEASED:
                return ""
            return "Бонусы по этому заказу уже списаны"
        st = _ensure_status(uid, now)
        q = quote(uid, items, now)
        if points < q["redeemMin"]:
            return f"Бонусами можно оплатить от {q['redeemMin']} бонусов"
        if points > q["redeemMax"]:
            if points > q["available"]:
                return f"Недостаточно бонусов: доступно {q['available']}"
            return (f"В этом заказе бонусами можно оплатить не больше {q['redeemMax']} "
                    f"({round(q['ceiling'] * 100)}% от суммы товаров, на которые "
                    "распространяется списание)")
        parts, short = _debit_fifo(uid, points, skip_frozen=True)
        if short:
            raise RedeemError("недостача при списании")  # не должно случиться: откат
        red = LoyaltyRedemption.objects.create(
            user_id=uid, order_id=order_id, amount=points, level_at=st.level,
            eligible_kop=q["eligible_kop"], ceiling=q["ceiling"],
            unit_eligible_kop=q["unit_eligible_kop"],
        )
        LoyaltyRedemptionPart.objects.bulk_create([
            LoyaltyRedemptionPart(redemption=red, lot=lot, amount=take) for lot, take in parts
        ])
        _reserve(-points)
        _event(uid, "redeem", -points, now=now, level_before=st.level, st=st,
               source_ref=order_id, eligible_kop=q["eligible_kop"])
    _invalidate(uid)
    return ""


def redemption_for(user_id, order_id):
    """Действующее списание v1 по заказу (не разблокированное) или None."""
    return LoyaltyRedemption.objects.filter(user_id=user_id, order_id=order_id).exclude(
        state=LoyaltyRedemption.RELEASED).first()


def has_redemption(user_id, order_id) -> bool:
    return LoyaltyRedemption.objects.filter(user_id=user_id, order_id=order_id).exists()


def release_for_order(order, now=None):
    """Отмена/истечение окна оплаты: заблокированные бонусы — обратно в свои лоты.
    None — по заказу нет списания v1 (работает старый реестр)."""
    now = now or timezone.now()
    uid = order.user_id
    if not has_redemption(uid, order.order_id):
        return None
    with transaction.atomic():
        lock_wallet(uid)
        red = LoyaltyRedemption.objects.filter(user_id=uid, order_id=order.order_id).first()
        if red.state != LoyaltyRedemption.BLOCKED:
            return 0
        n = 0
        for part in red.parts.select_related("lot"):
            back = part.amount - part.returned
            if back > 0:
                _restore(part.lot, back, now)
                part.returned += back
                part.save(update_fields=["returned"])
                n += back
        red.state = LoyaltyRedemption.RELEASED
        red.save(update_fields=["state", "updated_at"])
        _settle_debt(uid)
        st = LoyaltyStatus.objects.filter(user_id=uid).first()
        _reserve(n)
        _event(uid, "redeem_return", n, now=now, level_before=st.level if st else 0, st=st,
               source_ref=order.order_id, note="Оплата не прошла — бонусы разблокированы")
    _invalidate(uid)
    return n


# ── возврат товара ───────────────────────────────────────────────────────────

def points_share(order, chosen_indexes):
    """Сколько списанных бонусов приходится на возвращаемые позиции чека — по доле
    в eligible_total (ТЗ §4). None — у заказа нет списания v1."""
    red = redemption_for(order.user_id, order.order_id)
    if red is None:
        return None
    units = list(red.unit_eligible_kop or [])
    total = sum(units)
    if not total:
        return 0
    chosen = sum(units[i] for i in chosen_indexes if 0 <= int(i) < len(units))
    return red.amount * chosen // total


def return_redeemed(order, n, now=None):
    """Возврат товара: списанные бонусы — в исходные лоты пропорционально их долям,
    с прежними датами. None — у заказа нет списания v1."""
    now = now or timezone.now()
    uid = order.user_id
    if redemption_for(uid, order.order_id) is None:
        return None
    with transaction.atomic():
        lock_wallet(uid)
        red = redemption_for(uid, order.order_id)
        n = min(max(0, int(n)), red.amount - red.returned)
        if n <= 0:
            return 0
        parts = [p for p in red.parts.select_related("lot").order_by("id")
                 if p.amount - p.returned > 0]
        left_total = sum(p.amount - p.returned for p in parts)
        shares = [(p, n * (p.amount - p.returned) // left_total) for p in parts]
        rest = n - sum(s for _, s in shares)
        # Остаток от округления — лотам с наибольшей долей.
        order_by_size = sorted(range(len(shares)), key=lambda i: -(parts[i].amount
                                                                   - parts[i].returned))
        shares = [list(s) for s in shares]
        i = 0
        while rest > 0 and shares:
            idx = order_by_size[i % len(shares)]
            p, s = shares[idx]
            if s < p.amount - p.returned:
                shares[idx][1] += 1
                rest -= 1
            i += 1
        for p, s in shares:
            if s > 0:
                _restore(p.lot, s, now)
                p.returned += s
                p.save(update_fields=["returned"])
        red.returned += n
        red.save(update_fields=["returned", "updated_at"])
        _settle_debt(uid)
        st = LoyaltyStatus.objects.filter(user_id=uid).first()
        _reserve(n)
        _event(uid, "redeem_return", n, now=now, level_before=st.level if st else 0, st=st,
               source_ref=order.order_id, note="Возврат товара")
    _invalidate(uid)
    return n


def purchase_lot(order):
    return LoyaltyLot.objects.filter(user_id=order.user_id, source=PURCHASE,
                                     source_ref=order.order_id).first()


def revoke_purchase(order, n, now=None):
    """Возврат товара: начисленное за покупку. Лот held → отменяется (частично —
    уменьшается); уже available → доля списывается с баланса, при нехватке баланс
    уходит в минус. Статусные за эту покупку аннулируются (уровень — до плановой
    проверки). None — у заказа нет лота v1."""
    now = now or timezone.now()
    uid = order.user_id
    if purchase_lot(order) is None:
        return None
    with transaction.atomic():
        lock_wallet(uid)
        lot = purchase_lot(order)
        meta = dict(lot.meta or {})
        revoked = int(meta.get("revoked", 0))
        n = min(max(0, int(n)), lot.amount - revoked)
        if n <= 0:
            return 0
        st = _ensure_status(uid, now)
        if lot.state == HELD:
            lot.remaining = max(0, lot.remaining - n)
            if lot.remaining == 0:
                lot.state = CANCELLED
        else:
            take = min(n, max(0, lot.remaining))
            if take:
                lot.remaining -= take
                if lot.remaining == 0 and lot.state == AVAILABLE:
                    lot.state = SPENT
            rest = n - take
            if rest:
                lot.save(update_fields=["remaining", "state"])
                _parts, short = _debit_fifo(uid, rest)
                _add_debt(uid, st, short, now)
                lot.refresh_from_db()
        meta["revoked"] = revoked + n
        lot.meta = meta
        lot.status_amount = max(0, lot.status_amount - n)
        lot.save(update_fields=["remaining", "state", "status_amount", "meta"])
        _reserve(-n)
        _event(uid, "cancel", -n, now=now, level_before=st.level, st=st, lot=lot,
               source_ref=order.order_id, note="Возврат товара")
    _invalidate(uid)
    return n


# ── сгорание ─────────────────────────────────────────────────────────────────

def expire_lots(now=None) -> dict:
    """Ежедневно: лоты с expires_at раньше «сейчас» сгорают (остаток 0, событие)."""
    now = now or timezone.now()
    stats = {"expired": 0, "bonuses": 0}
    for lot_id, uid in LoyaltyLot.objects.filter(
            state=AVAILABLE, remaining__gt=0, expires_at__lt=now).values_list("id", "user_id"):
        with transaction.atomic():
            lock_wallet(uid)
            lot = LoyaltyLot.objects.get(pk=lot_id)
            if lot.state != AVAILABLE or lot.remaining <= 0 or lot.expires_at >= now:
                continue
            n = lot.remaining
            lot.remaining, lot.state = 0, EXPIRED
            lot.save(update_fields=["remaining", "state"])
            st = LoyaltyStatus.objects.filter(user_id=uid).first()
            _reserve(-n)
            _event(uid, "expire", -n, now=now, level_before=st.level if st else 0, st=st,
                   lot=lot)
        _invalidate(uid)
        stats["expired"] += 1
        stats["bonuses"] += n
    return stats


def warn_expiring(now=None) -> dict:
    """За EXPIRY_WARN_DAYS до сгорания — уведомление с суммой и датой, не чаще
    раза в неделю на человека."""
    now = now or timezone.now()
    soon = now + timedelta(days=config.get("EXPIRY_WARN_DAYS"))
    week_ago = now - timedelta(days=7)
    rows = (LoyaltyLot.objects.filter(state=AVAILABLE, remaining__gt=0, expires_at__gt=now,
                                      expires_at__lte=soon)
            .values("user_id").annotate(total=Sum("remaining"), first=Max("expires_at")))
    sent = 0
    for row in rows:
        uid = row["user_id"]
        st = LoyaltyStatus.objects.filter(user_id=uid).first()
        if st is None or (st.expiry_warned_at and st.expiry_warned_at > week_ago):
            continue
        nearest = LoyaltyLot.objects.filter(
            user_id=uid, state=AVAILABLE, remaining__gt=0, expires_at__gt=now,
            expires_at__lte=soon).order_by("expires_at").first()
        date = timezone.localtime(nearest.expires_at).strftime("%d.%m.%Y")
        _notify(uid, "Бонусы скоро сгорят",
                f"{row['total']} бонусов сгорят до {date}. Потратьте их в МАТА Store.")
        LoyaltyStatus.objects.filter(pk=st.pk).update(expiry_warned_at=now)
        sent += 1
    return {"warned": sent}


def daily(now=None) -> dict:
    """Ежедневная задача: удержание, сгорание, предупреждения, понижение уровней."""
    if not config.enabled():
        return {"enabled": False}
    now = now or timezone.now()
    return {
        "holds": release_holds(now),
        "expired": expire_lots(now),
        "warned": warn_expiring(now),
        "levels": recheck_levels(now),
    }


# ── перенос из старого реестра и зеркало ─────────────────────────────────────

def migrate_user(uid, now=None, apply=False, _locked=False) -> dict:
    """Перенос человека в v1 (ТЗ, решения координатора «Перенос»).

    - баланс старого реестра → лот `migration` available, срок — от даты переноса
      по уровню после переноса (отрицательный баланс → долг);
    - ещё не созревшие баллы за активность (D-107, 3 дня) → лот held до их срока;
    - статусные = начисления старого реестра за 365 дней (покупки, бег, захват,
      вехи, дивизион, сезон) минус их отмены (по дням, не ниже нуля); регистрация,
      бонус первого заказа, возврат списанного, ручные правки — не статусные.
      Хранятся лотами `legacy_history` (остаток 0) с датой начисления — окно 365
      дней «съедает» их само;
    - уровень — по новым порогам из этих статусных (Платина — ещё покупки ≥
      PLATINUM_MIN_SPEND за 365 дней по заказам); срок уровня +365 дней.
    Идемпотентно: у перенесённого (есть `LoyaltyStatus`) ничего не делает.
    """
    from .models import LoyaltyTransaction

    now = now or timezone.now()
    if not _locked and apply:
        with transaction.atomic():
            lock_wallet(uid)
            return migrate_user(uid, now=now, apply=True, _locked=True)
    if LoyaltyStatus.objects.filter(user_id=uid).exists():
        return {"user_id": uid, "skipped": "already"}
    txns = list(LoyaltyTransaction.objects.filter(user_id=uid).values_list(
        "amount", "source", "created_at", "available_at", "run_id", "order_id", "id"))
    total = sum(t[0] for t in txns)
    # Несозревшие баллы (D-107) — по основанию (забег/захват): отзыв по тому же
    # основанию после переноса снимет именно их.
    groups = defaultdict(lambda: [0, None])  # основание → [сумма, созревает]
    for amount, _s, _c, avail, run_id, order_id, tid in txns:
        if avail and avail > now:
            g = groups[run_id or order_id or tid]
            g[0] += amount
            g[1] = max(g[1], avail) if g[1] else avail
    maturing_lots = [(ref, amt, until) for ref, (amt, until) in groups.items() if amt > 0]
    maturing = sum(amt for _r, amt, _u in maturing_lots)
    since = now - timedelta(days=config.STATUS_WINDOW_DAYS)
    days = defaultdict(lambda: [0, None])  # местная дата → [статусные, последнее время]
    for amount, source, created, _v, _r, _o, _i in txns:
        if created <= since:
            continue
        day = timezone.localtime(created).date()
        if amount > 0 and source in LEGACY_STATUS_SOURCES:
            days[day][0] += amount
        elif amount < 0 and source in LEGACY_STATUS_REVOKES:
            days[day][0] += amount
        else:
            continue
        if days[day][1] is None or created > days[day][1]:
            days[day][1] = created
    history = [(d, pts, at) for d, (pts, at) in sorted(days.items()) if pts > 0]
    status = sum(pts for _d, pts, _at in history)
    level = level_target(status, lambda: purchases_rub(uid, now))
    available = total - maturing
    plan = {"user_id": uid, "balance": total, "available": available, "held": maturing,
            "status_points": status, "level": level, "level_name": config.LEVELS[level]}
    if not apply:
        return plan

    term = timedelta(days=config.STATUS_TERM_DAYS)
    st = LoyaltyStatus.objects.create(
        user_id=uid, level=level, level_until=now + term if level else None,
        level_since=now if level else None, migrated_at=now, legacy_balance=total)
    for day, pts, at in history:
        LoyaltyLot.objects.create(
            user_id=uid, amount=pts, remaining=0, state=SPENT, source=HISTORY,
            source_ref=f"legacy:{day.isoformat()}", status_amount=pts, accrued_at=at,
            available_at=at, expires_at=None, level_at_accrual=0)
    lot = None
    if available > 0:
        lot = _create_lot(uid, st, available, MIGRATION, "migration", state=AVAILABLE,
                          now=now, status=False)
    elif available < 0:
        lot = _add_debt(uid, st, -available, now)
    for ref, amt, until in maturing_lots:
        _create_lot(uid, st, amt, LEGACY_ACTIVITY, ref, state=HELD, now=now, status=False,
                    available_at=until, meta={"migrated": True})
    pseudonym(uid)
    _reserve(total)
    if total:
        _event(uid, "accrue_migration", total, now=now, level_before=BASIC, st=st, lot=lot,
               source_ref="migration", note="Перенос баланса из старого реестра")
    if level:
        _event(uid, "level_up", 0, now=now, level_before=BASIC, st=st,
               note="Уровень при переносе")
    return {**plan, "migrated": True}


def mirror_legacy(txn) -> None:
    """Новая запись старого реестра по перенесённому человеку → лоты.

    Плюс — лот (баллы за бег/захват созревают как раньше: held до available_at);
    минус — списание: сначала из лотов того же основания (забег/заказ), затем по
    дате сгорания, недостача — долг. Не перенесённых не трогаем: их запись войдёт
    в баланс при переносе.
    """
    uid = txn.user_id
    now = timezone.now()
    with transaction.atomic():
        lock_wallet(uid)
        st = LoyaltyStatus.objects.filter(user_id=uid).first()
        if st is None:
            return
        before = st.level
        ref = txn.run_id or txn.order_id or txn.id
        etype = _LEGACY_EVENT.get(txn.source)
        if txn.amount > 0:
            status = txn.source in LEGACY_STATUS_SOURCES
            source = LEGACY_ACTIVITY if txn.source.startswith("runner") else LEGACY
            held = bool(txn.available_at and txn.available_at > now)
            lot = _create_lot(uid, st, txn.amount, source, ref, state=HELD if held else AVAILABLE,
                              now=now, status=status,
                              available_at=txn.available_at if held else None,
                              meta={"legacyTxn": txn.id, "legacySource": txn.source})
            if not held:
                _settle_debt(uid)
            _reserve(txn.amount)
            _event(uid, etype or "accrue_manual", txn.amount, now=now, level_before=before,
                   st=st, lot=lot, note=f"Старый реестр: {txn.source}")
            _check_level(uid, st, now)
        elif txn.amount < 0:
            n = -txn.amount
            first = []
            if txn.source != "redeem" and (txn.run_id or txn.order_id):
                first = list(LoyaltyLot.objects.filter(
                    user_id=uid, source_ref=ref, remaining__gt=0,
                    state__in=(HELD, AVAILABLE)).order_by("id"))
            # Лоты основания могут быть и held (баллы ещё созревают) — их тоже снимаем.
            parts, short = _debit_fifo(uid, n, first=first)
            if txn.source in LEGACY_STATUS_REVOKES:
                for lot, take in parts:
                    if lot.source_ref == ref and lot.status_amount:
                        lot.status_amount = max(0, lot.status_amount - take)
                        lot.save(update_fields=["status_amount"])
            _add_debt(uid, st, short, now)
            _reserve(-n)
            _event(uid, etype or "cancel", -n, now=now, level_before=before, st=st,
                   source_ref=ref, note=f"Старый реестр: {txn.source}")
    _invalidate(uid)
