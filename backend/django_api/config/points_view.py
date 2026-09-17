"""«Баллы» в админке: клиенты с операциями за выбранные дни, по клику — их начисления.

Раньше раздел был построчным журналом `LoyaltyTransaction`: человек повторялся на каждой
операции, а даты сверху давали только готовые ссылки по месяцам и дням. Владелец ищет
иначе: выбирает день в календаре, видит, кому и сколько начислено именно тогда, и
открывает человека — за что. Журнал остался: в нём ручные корректировки и выгрузка CSV.

Дни считаем в якутском времени (TIME_ZONE): «5 сентября» — это сутки по Якутску, а не по UTC.
"""
from datetime import datetime, time, timedelta
from urllib.parse import urlencode

from django.contrib import admin
from django.contrib.admin.views.decorators import staff_member_required
from django.core.paginator import Paginator
from django.db.models import Case, Count, IntegerField, Max, Q, Sum, When
from django.http import Http404
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils import timezone

from accounts.models import Account
from loyalty.models import LoyaltyTransaction
from staff.access import can, tab_required
from staff.models import LEVEL_EDIT

PER_PAGE = 50

# Коды источников → как их называет человек. Совпадает с подписями в приложениях;
# незнакомый код показываем как есть, чтобы новая механика не пропала из вида.
SOURCE_LABELS = {
    "runnerRun": "Пробежка",
    "runnerRunRevoked": "Пробежка отменена",
    "runnerTerritory": "Захват территории",
    "runnerCompetition": "Соревнование",
    "runnerDivision": "Награда дивизиона",
    "runnerSeason": "Награда сезона",
    "runnerMilestone": "Веха",
    "registration": "Бонус за регистрацию",
    "purchase": "Покупка",
    "purchase_revoke": "Возврат покупки: начисление снято",
    "redeem": "Оплата баллами",
    "redeem_refund": "Возврат оплаты баллами",
    "review": "Отзыв с фото",
    "birthday": "День рождения",
    "referral": "Приглашение друга",
}


def source_label(code: str) -> str:
    return SOURCE_LABELS.get(code, code or "—")


def _earned():
    return Sum(Case(When(amount__gt=0, then="amount"), default=0, output_field=IntegerField()))


def _spent():
    return Sum(Case(When(amount__lt=0, then="amount"), default=0, output_field=IntegerField()))


def _parse_date(raw):
    try:
        return datetime.strptime((raw or "").strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def _fmt(day):
    return day.strftime("%d.%m.%Y")


def _period(request):
    """Выбранные дни. Одна дата — ровно этот день; ничего — вся история."""
    d_from = _parse_date(request.GET.get("date_from"))
    d_to = _parse_date(request.GET.get("date_to")) or d_from
    d_from = d_from or d_to
    if d_from is None:
        return None
    if d_to < d_from:
        d_from, d_to = d_to, d_from
    tz = timezone.get_current_timezone()
    return {
        "from": d_from,
        "to": d_to,
        "start": timezone.make_aware(datetime.combine(d_from, time.min), tz),
        "end": timezone.make_aware(datetime.combine(d_to + timedelta(days=1), time.min), tz),
        "label": _fmt(d_from) if d_from == d_to else f"{_fmt(d_from)} — {_fmt(d_to)}",
        "query": urlencode({"date_from": d_from.isoformat(), "date_to": d_to.isoformat()}),
    }


def _quick_ranges():
    today = timezone.localdate()

    def q(a, b):
        return urlencode({"date_from": a.isoformat(), "date_to": b.isoformat()})

    yesterday = today - timedelta(days=1)
    return [
        ("Сегодня", q(today, today)),
        ("Вчера", q(yesterday, yesterday)),
        ("7 дней", q(today - timedelta(days=6), today)),
        ("30 дней", q(today - timedelta(days=29), today)),
    ]


def _local(dt):
    return timezone.localtime(dt).strftime("%d.%m.%Y %H:%M") if dt else "—"


def _client_name(account, user_id):
    if account is None:
        return "Аккаунт удалён"
    return account.name or account.phone or account.email or user_id


@staff_member_required
@tab_required("loyalty")
def points_clients(request):
    period = _period(request)
    q = (request.GET.get("q") or "").strip()
    sort = request.GET.get("sort") or "last"

    txns = LoyaltyTransaction.objects.all()
    if period:
        txns = txns.filter(created_at__gte=period["start"], created_at__lt=period["end"])
    if q:
        found = Account.objects.filter(
            Q(name__icontains=q) | Q(phone__icontains=q) | Q(email__icontains=q)
        ).values("id")
        txns = txns.filter(Q(user_id__in=found) | Q(user_id=q))

    order = {"earned": ["-earned", "-last"], "ops": ["-ops", "-last"]}.get(sort, ["-last"])
    grouped = (txns.values("user_id")
               .annotate(earned=_earned(), spent=_spent(), ops=Count("id"), last=Max("created_at"))
               .order_by(*order))
    totals = txns.aggregate(earned=_earned(), spent=_spent(), ops=Count("id"),
                            clients=Count("user_id", distinct=True))

    page = Paginator(grouped, PER_PAGE).get_page(request.GET.get("page"))
    ids = [r["user_id"] for r in page.object_list]
    accounts = Account.objects.in_bulk(ids)
    balances = dict(LoyaltyTransaction.objects.filter(user_id__in=ids)
                    .values("user_id").annotate(b=Sum("amount")).values_list("user_id", "b"))

    keep = {}
    if period:
        keep["date_from"] = period["from"].isoformat()
        keep["date_to"] = period["to"].isoformat()
    if q:
        keep["q"] = q
    rows = []
    for r in page.object_list:
        acc = accounts.get(r["user_id"])
        url = reverse("points_client", args=[r["user_id"]])
        rows.append({
            "name": _client_name(acc, r["user_id"]),
            "deleted": acc is None,
            "phone": (acc.phone if acc else "") or "—",
            "earned": r["earned"] or 0,
            "spent": abs(r["spent"] or 0),
            "ops": r["ops"],
            "last": _local(r["last"]),
            "balance": balances.get(r["user_id"], 0),
            "url": f"{url}?{period['query']}" if period else url,
        })

    context = {
        **admin.site.each_context(request),
        "title": "Баллы",
        "period": period,
        "date_from": period["from"].isoformat() if period else "",
        "date_to": period["to"].isoformat() if period else "",
        "q": q,
        "sort": sort,
        "rows": rows,
        "page": page,
        "totals": {"earned": totals["earned"] or 0, "spent": abs(totals["spent"] or 0),
                   "ops": totals["ops"], "clients": totals["clients"]},
        "quick": _quick_ranges(),
        "keep": urlencode(keep),
        "keep_sort": urlencode({**keep, "sort": sort}),
        "journal_url": reverse("admin:loyalty_loyaltytransaction_changelist"),
    }
    return TemplateResponse(request, "admin/points_clients.html", context)


@staff_member_required
@tab_required("loyalty")
def points_client(request, user_id):
    period = _period(request)
    account = Account.objects.filter(id=user_id).first()
    history = LoyaltyTransaction.objects.filter(user_id=user_id)
    if account is None and not history.exists():
        raise Http404("Клиент не найден")

    balance = history.aggregate(s=Sum("amount"))["s"] or 0
    before = 0
    txns = history
    if period:
        before = history.filter(created_at__lt=period["start"]).aggregate(s=Sum("amount"))["s"] or 0
        txns = history.filter(created_at__gte=period["start"], created_at__lt=period["end"])

    show_orders = can(request.user, "orders")
    rows, running = [], before
    for t in txns.order_by("created_at", "id"):
        running += t.amount
        order_url = ""
        if t.order_id and show_orders:
            order_url = reverse("admin:orders_order_changelist") + "?" + urlencode({"q": t.order_id})
        rows.append({
            "when": _local(t.created_at),
            "amount": t.amount,
            "label": source_label(t.source),
            "description": t.description,
            "order_id": t.order_id or "",
            "order_url": order_url,
            "run_id": t.run_id or "",
            "balance_after": running,
        })
    rows.reverse()  # свежие сверху; «баланс после» посчитан в хронологическом порядке

    adjust_url = ""
    if can(request.user, "loyalty", LEVEL_EDIT):
        adjust_url = (reverse("admin:loyalty_loyaltytransaction_add") + "?"
                      + urlencode({"user_id": user_id}))

    context = {
        **admin.site.each_context(request),
        "title": f"Баллы: {_client_name(account, user_id)}",
        "account": account,
        "name": _client_name(account, user_id),
        "period": period,
        "balance": balance,
        "earned": sum(r["amount"] for r in rows if r["amount"] > 0),
        "spent": abs(sum(r["amount"] for r in rows if r["amount"] < 0)),
        "rows": rows,
        "back_url": reverse("points_clients") + (f"?{period['query']}" if period else ""),
        "all_url": reverse("points_client", args=[user_id]),
        "adjust_url": adjust_url,
    }
    return TemplateResponse(request, "admin/points_client.html", context)
