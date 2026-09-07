"""Данные для главной админки (KPI + график). Подключается через
UNFOLD['DASHBOARD_CALLBACK'] и используется в templates/admin/index.html.
Аналитика экосистемы (S-11): магазин + бег + территории + конверсия Квартал→Store."""
from datetime import timedelta

from django.db import connection
from django.db.models import Sum
from django.utils import timezone


def _errors_tile():
    """Плитка «Ошибки» на главной (D-32).

    Смысл плитки не в цифре, а в том, чтобы владелец увидел проблему, НЕ заходя
    специально в трекер. Открытая админка — это то, что перед глазами каждый день;
    отдельную вкладку открывают, когда уже что-то заподозрили.

    Трекер — внешняя система: он может быть не настроен, лежать или тормозить.
    Поэтому любой сбой превращается в тихий прочерк, а не в упавшую главную
    страницу. Дашборд важнее наблюдаемости.
    """
    from common import glitchtip

    if not glitchtip.is_configured():
        return {"title": "Ошибки", "value": "—", "icon": "bug_report"}
    try:
        issues, error = glitchtip.fetch_issues(query="is:unresolved")
        if error:
            return {"title": "Ошибки", "value": "нет связи", "icon": "bug_report"}
        summary = glitchtip.summarize(issues)
        return {"title": "Ошибки без разбора", "value": summary["errors"],
                "icon": "bug_report"}
    except Exception:
        return {"title": "Ошибки", "value": "—", "icon": "bug_report"}


def dashboard_callback(request, context):
    from accounts.models import Account
    from catalog.models import Product
    from clubs.models import Club
    from loyalty.models import LoyaltyTransaction
    from orders.models import Order
    from runs.models import Run
    from shoes.models import ShoeAsset
    from territories.views import HOLD_HOURS

    now = timezone.now()
    today = now.date()
    week_ago = now - timedelta(days=7)

    def _sum(qs, field="amount"):
        return qs.aggregate(s=Sum(field))["s"] or 0

    orders_total = Order.objects.count()
    orders_today = Order.objects.filter(created_at__date=today).count()
    revenue = _sum(Order.objects.all(), "total")
    revenue_week = _sum(Order.objects.filter(created_at__gte=week_ago), "total")
    users = Account.objects.count()
    products = Product.objects.count()
    clubs = Club.objects.count()
    shoes_active = ShoeAsset.objects.filter(status="active").count()
    points_earned = _sum(LoyaltyTransaction.objects.filter(amount__gt=0))
    points_spent = -_sum(LoyaltyTransaction.objects.filter(amount__lt=0))

    # ── Бег (по начислениям за бег, D-11: км = Σ(runnerRun)/10) + синк забегов ──
    run_txns = LoyaltyTransaction.objects.filter(source="runnerRun")
    run_km_total = round(_sum(run_txns) / 10.0, 1)
    runs_synced = Run.objects.count()
    runs_week = Run.objects.filter(finished_at__gte=week_ago).count()

    # ── Анти-чит (S-04): аккаунты на ревью + помеченные забеги ──
    accounts_review = Account.objects.filter(needs_review=True).count()
    runs_flagged = Run.objects.filter(flagged=True).count()

    # ── Активность за неделю (WAU): уник. юзеры с начислением или заказом ──
    wau = len(
        set(
            LoyaltyTransaction.objects.filter(created_at__gte=week_ago)
            .values_list("user_id", flat=True)
        )
        | set(
            Order.objects.filter(created_at__gte=week_ago)
            .values_list("user_id", flat=True)
        )
    )

    # ── Конверсия Квартал→Store: бегуны, которые ещё и покупают ──
    runners = set(run_txns.values_list("user_id", flat=True))
    buyers = set(Order.objects.values_list("user_id", flat=True))
    converted = len(runners & buyers)
    conversion_pct = round(converted / len(runners) * 100) if runners else 0

    # ── Территории (PostGIS): активные (живой слой) + суммарная площадь ──
    # Единственный raw-PostGIS-запрос на дашборде: изолируем try/except, чтобы
    # сбой расширения/таблицы territories не ронял всю главную страницу админки.
    terr_count, terr_km2 = 0, 0
    try:
        with connection.cursor() as cur:
            cur.execute(
                "SELECT count(*), COALESCE(SUM(ST_Area(geom::geography)),0) "
                "FROM territories WHERE captured_at > now() - make_interval(hours => %s)",
                [HOLD_HOURS],
            )
            terr_count, terr_area = cur.fetchone()
        terr_km2 = round((terr_area or 0) / 1_000_000, 2)
    except Exception:
        terr_count, terr_km2 = 0, 0

    # Заказы по дням за последнюю неделю — для столбчатого графика.
    daily = []
    for i in range(6, -1, -1):
        d = (now - timedelta(days=i)).date()
        daily.append({"label": d.strftime("%d.%m"),
                      "value": Order.objects.filter(created_at__date=d).count()})
    peak = max([x["value"] for x in daily] + [1])
    for x in daily:
        x["pct"] = round(x["value"] / peak * 100)

    context.update({
        "kpis": [
            {"title": "Заказов всего", "value": orders_total,
             "sub": f"+{orders_today} сегодня", "icon": "shopping_cart"},
            {"title": "Выручка, ₽", "value": int(revenue),
             "sub": f"+{int(revenue_week)} за неделю", "icon": "payments"},
            {"title": "Пользователей", "value": users,
             "sub": f"{wau} активны за неделю", "icon": "group"},
            {"title": "Баллы экосистемы", "value": points_earned,
             "sub": f"−{points_spent} потрачено", "icon": "loyalty"},
        ],
        "extra_stats": [
            _errors_tile(),
            {"title": "Аккаунтов на проверке", "value": accounts_review,
             "icon": "gpp_maybe"},
            {"title": "Забегов помечено (чит)", "value": runs_flagged,
             "icon": "flag"},
            {"title": "Конверсия Квартал→Store", "value": f"{conversion_pct}%",
             "icon": "sync_alt"},
            {"title": "Км пробежек всего", "value": run_km_total,
             "icon": "directions_run"},
            {"title": "Забегов синхронизировано", "value": runs_synced,
             "icon": "timeline"},
            {"title": "Территорий активно", "value": terr_count,
             "icon": "map"},
            {"title": "Площадь территорий, км²", "value": terr_km2,
             "icon": "crop_square"},
            {"title": "Клубы", "value": clubs, "icon": "groups"},
            {"title": "Кроссовки в трекере", "value": shoes_active,
             "icon": "directions_walk"},
            {"title": "Товаров", "value": products, "icon": "inventory_2"},
        ],
        "orders_daily": daily,
    })
    return context
