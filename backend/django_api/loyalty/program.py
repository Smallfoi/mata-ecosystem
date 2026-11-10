"""Сводки и операции раздела админки «Программа лояльности» (без HTTP).

Здесь — то, что нужно и странице, и команде: перенос всех участников в v1
(`migrate_all` — та же логика, что `manage.py loyalty_migrate_v1`), цифры обзора,
карточка участника и ответ «почему этот товар не оплачивается бонусами».
Просмотр ничего не меняет: карточка не переносит человека в v1 (в отличие от
`v1.wallet`, который переносит лениво).
"""
from collections import Counter, defaultdict
from datetime import datetime, time, timedelta

from django.db.models import Count, Q, Sum
from django.utils import timezone

from . import config, v1
from .models import LoyaltyTransaction
from .models_v1 import LoyaltyEvent, LoyaltyLot, LoyaltyStatus

ACCRUE_TYPES = ("accrue_purchase", "accrue_run", "accrue_capture", "accrue_stage",
                "accrue_referral", "accrue_signup", "accrue_manual")


# ── перенос ──────────────────────────────────────────────────────────────────

def _all_uids():
    from accounts.models import Account

    return sorted(set(Account.objects.values_list("id", flat=True))
                  | set(LoyaltyTransaction.objects.values_list("user_id", flat=True).distinct()))


def migration_status() -> dict:
    done = set(LoyaltyStatus.objects.values_list("user_id", flat=True))
    pending = [u for u in _all_uids() if u and u not in done]
    return {"migrated": len(done), "pending": len(pending)}


def migrate_all(apply=False, user=None, now=None, on_user=None) -> dict:
    """Перенос в v1 всех (или одного) участников. Сухой прогон по умолчанию.

    Идемпотентно: перенесённых пропускает. `on_user(uid, plan)` — строка по
    каждому перенесённому (команда печатает её с --verbose-users)."""
    now = now or timezone.now()
    uids = [user] if user else _all_uids()
    done = set(LoyaltyStatus.objects.values_list("user_id", flat=True))
    levels = Counter()
    out = {"apply": bool(apply), "moved": 0, "skipped": 0, "total": 0, "held": 0,
           "negative": 0}
    for uid in uids:
        if not uid:
            continue
        if uid in done:
            out["skipped"] += 1
            continue
        plan = v1.migrate_user(uid, now=now, apply=apply)
        if plan.get("skipped"):
            out["skipped"] += 1
            continue
        out["moved"] += 1
        levels[plan["level_name"]] += 1
        out["total"] += plan["balance"]
        out["held"] += plan["held"]
        out["negative"] += plan["balance"] < 0
        if on_user:
            on_user(uid, plan)
    if apply and not user:
        # Псевдонимы — всем аккаунтам, даже без баллов (журнал и аналитика).
        from accounts.models import Account

        for uid in Account.objects.filter(loyalty_pseudonym="").values_list("id", flat=True):
            v1.pseudonym(uid)
    out["levels"] = [(name, title, levels.get(name, 0))
                     for name, title in zip(config.LEVELS, config.LEVEL_TITLES)]
    return out


# ── обзор ────────────────────────────────────────────────────────────────────

def month_start(now=None):
    """Начало текущего календарного месяца по местному времени (Якутск)."""
    local = timezone.localtime(now or timezone.now())
    first = datetime.combine(local.date().replace(day=1), time.min)
    return timezone.make_aware(first, timezone.get_current_timezone())


def overview(now=None) -> dict:
    now = now or timezone.now()
    by_level = dict(LoyaltyStatus.objects.values("level").annotate(n=Count("id"))
                    .values_list("level", "n"))
    lots = LoyaltyLot.objects.aggregate(
        available=Sum("remaining", filter=Q(state=v1.AVAILABLE, remaining__gt=0)),
        held=Sum("remaining", filter=Q(state=v1.HELD)),
        debt=Sum("remaining", filter=Q(state=v1.AVAILABLE, remaining__lt=0)),
    )
    since = month_start(now)
    month = LoyaltyEvent.objects.filter(created_at__gte=since).aggregate(
        accrued=Sum("amount", filter=Q(type__in=ACCRUE_TYPES, amount__gt=0)),
        redeemed=Sum("amount", filter=Q(type="redeem")),
        returned=Sum("amount", filter=Q(type="redeem_return")),
        expired=Sum("amount", filter=Q(type="expire")),
    )
    return {
        "levels": [{"title": title, "count": by_level.get(i, 0)}
                   for i, title in enumerate(config.LEVEL_TITLES)],
        "participants": sum(by_level.values()),
        "available": lots["available"] or 0,
        "held": lots["held"] or 0,
        "debt": -(lots["debt"] or 0),
        "reserve_rub": v1.reserve_rub(),
        "month_label": timezone.localtime(since).strftime("%m.%Y"),
        "month_accrued": month["accrued"] or 0,
        "month_redeemed": max(0, -(month["redeemed"] or 0) - (month["returned"] or 0)),
        "month_expired": -(month["expired"] or 0),
    }


# ── участник ─────────────────────────────────────────────────────────────────

def member(uid, now=None) -> dict:
    """Карточка участника для админки. Ничего не пишет: не перенесённого в v1
    показывает по плану переноса (сухой прогон)."""
    from accounts.models import Account

    now = now or timezone.now()
    acc = Account.objects.filter(id=uid).first()
    st = LoyaltyStatus.objects.filter(user_id=uid).first()
    out = {"uid": uid, "account": acc, "migrated": st is not None, "status": st}
    if st is None:
        out["plan"] = v1.migrate_user(uid, now=now, apply=False)
        out["level_title"] = config.LEVEL_TITLES[out["plan"]["level"]]
        out["lots"], out["events"] = [], []
        return out
    agg = LoyaltyLot.objects.filter(user_id=uid).aggregate(
        available=Sum("remaining", filter=Q(state=v1.AVAILABLE, remaining__gt=0)),
        held=Sum("remaining", filter=Q(state=v1.HELD)),
        debt=Sum("remaining", filter=Q(state=v1.AVAILABLE, remaining__lt=0)),
    )
    th = config.get("LEVEL_THRESHOLD")
    out.update({
        "level_title": config.LEVEL_TITLES[st.level],
        "available": agg["available"] or 0,
        "held": agg["held"] or 0,
        "debt": -(agg["debt"] or 0),
        "redeemable": v1.redeemable(uid),
        "status_points": v1.status_points(uid, now),
        "purchases_rub": v1.purchases_rub(uid, now),
        "next_threshold": th[st.level] if st.level < v1.PLATINUM else None,
        "lots": list(LoyaltyLot.objects.filter(user_id=uid).exclude(source=v1.HISTORY)
                     .filter(Q(remaining__gt=0) | Q(state=v1.HELD) | Q(remaining__lt=0)
                             | Q(accrued_at__gte=now - timedelta(days=90)))
                     .order_by("-accrued_at")[:60]),
        "events": (list(LoyaltyEvent.objects.filter(user_pseudonym=acc.loyalty_pseudonym)
                        .order_by("-created_at")[:40])
                   if acc and acc.loyalty_pseudonym else []),
    })
    return out


def find_accounts(q, limit=20):
    from accounts.models import Account

    q = (q or "").strip()
    if not q:
        return []
    digits = "".join(ch for ch in q if ch.isdigit())
    cond = Q(id=q) | Q(name__icontains=q) | Q(email__icontains=q)
    if len(digits) >= 4:
        cond |= Q(phone__contains=digits[-10:])
    return list(Account.objects.filter(cond).order_by("name")[:limit])


# ── «Товары в программе» ─────────────────────────────────────────────────────

def category_tree():
    """Категории каталога деревом (порядок обхода, глубина) с числом товаров:
    своих и вместе с подкатегориями."""
    from catalog.models import Category, Product

    cats = list(Category.objects.all().order_by("sort", "name"))
    own = dict(Product.objects.values("category_id").annotate(n=Count("id"))
               .values_list("category_id", "n"))
    ids = {c.id for c in cats}
    children = defaultdict(list)
    roots = []
    for c in cats:
        if c.parent_id and c.parent_id in ids and c.parent_id != c.id:
            children[c.parent_id].append(c)
        else:
            roots.append(c)
    rows, seen = [], set()

    def walk(c, depth, parents):
        if c.id in seen:
            return 0
        seen.add(c.id)
        row = {"id": c.id, "name": c.name, "depth": depth, "own": own.get(c.id, 0),
               "parents": list(parents), "indent": "— " * depth}
        rows.append(row)
        total = row["own"] + sum(walk(k, depth + 1, parents + [c.id]) for k in children[c.id])
        row["total"] = total
        return total

    for c in roots:
        walk(c, 0, [])
    return rows


def brand_counts():
    from catalog.models import Product

    counts = defaultdict(int)
    names = {}
    for brand, n in (Product.objects.exclude(brand="").values("brand")
                     .annotate(n=Count("id")).values_list("brand", "n")):
        key = v1._brand_key(brand)
        counts[key] += n
        names.setdefault(key, " ".join(brand.split()))
    return sorted(({"name": names[k], "key": k, "count": counts[k]} for k in counts),
                  key=lambda r: r["name"].casefold())


def product_totals():
    """Сколько опубликованных товаров сейчас можно оплатить бонусами / исключено
    и за сколько начисляются бонусы."""
    from catalog.models import Product

    rules = v1.exclusion_rules()
    out = Counter()
    for p in Product.objects.filter(is_published=True).only(
            "id", "price", "old_price", "category_id", "brand"):
        out["total"] += 1
        reason = v1.redeem_reason(p, rules)
        out["redeem_ok" if not reason else "redeem_off"] += 1
        if reason:
            out[reason] += 1
        out["accrual_off" if v1.accrual_reason(p, rules) else "accrual_ok"] += 1
    return out


def explain_product(product) -> dict:
    """Почему товар оплачивается / не оплачивается бонусами и даёт ли бонусы —
    по шагам, понятным владельцу."""
    from catalog.models import Category

    rules = v1.exclusion_rules()
    cats = {c.id: c for c in Category.objects.all()}
    path, seen, cur = [], set(), cats.get(product.category_id)
    while cur is not None and cur.id not in seen:
        seen.add(cur.id)
        path.append(cur)
        cur = cats.get(cur.parent_id) if cur.parent_id else None
    path.reverse()
    redeem = v1.redeem_reason(product, rules)
    accrual = v1.accrual_reason(product, rules)

    def which(codes, key):
        explicit = set(config.get(key))
        return [c.name for c in path if c.id in explicit] if codes else []

    detail = ""
    if redeem == "excluded_category":
        names = which(True, "EXCLUDED_CATEGORIES_1C")
        detail = "исключена категория «" + "», «".join(names) + "»" if names else ""
    elif redeem == "excluded_brand":
        detail = f"исключён бренд «{product.brand}»"
    elif redeem == "markdown":
        detail = f"старая цена {product.old_price:g} ₽ больше цены {product.price:g} ₽"
    accrual_detail = ""
    if accrual == "no_accrual_category":
        names = which(True, "NO_ACCRUAL_CATEGORIES_1C")
        accrual_detail = "категория «" + "», «".join(names) + "»" if names else ""
    elif accrual == "no_accrual_brand":
        accrual_detail = f"бренд «{product.brand}»"
    return {
        "product": product,
        "category_path": " / ".join(c.name for c in path) or (product.category_id or "—"),
        "redeem_ok": not redeem,
        "redeem_reason": redeem,
        "redeem_text": v1.REASON_TEXT.get(redeem, ""),
        "redeem_detail": detail,
        "accrual_ok": not accrual,
        "accrual_reason": accrual,
        "accrual_text": v1.REASON_TEXT.get(accrual, ""),
        "accrual_detail": accrual_detail,
    }
