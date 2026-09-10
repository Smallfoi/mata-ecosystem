"""Страница «Возврат по заказу» (D-73).

Сотрудник отмечает, какие вещи вернул покупатель, видит, сколько денег и баллов
уйдёт обратно, и проводит возврат. Деньги — по суммам из чека (скидка баллами
разложена по позициям), баллы — в той же доле, доставка — вместе с последней вещью.

Уровни вкладки «Заказы»: «смотреть» — видеть заказ и расчёт; «редактировать» —
проводить возврат. Это деньги покупателя, поэтому не на уровне «смотреть».
"""
from django.contrib import admin
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.utils import timezone

from orders.awards import earned_for, redeemed_for
from orders.models import Order
from orders.returns import RETURNABLE, ReturnError, make_return, preview, return_plan
from staff.access import can, tab_required
from staff.models import LEVEL_EDIT, StaffAudit

PAYMENT_LABELS = {
    "pending": "ждёт оплату",
    "paid": "оплачен",
    "partially_refunded": "возвращён частично",
    "refunded": "возвращён",
    "canceled": "отменён",
}


def _rub(kop):
    return f"{kop / 100:,.2f}".replace(",", " ")


def _chosen(request):
    return sorted({int(x) for x in request.POST.getlist("line") if str(x).isdigit()})


@staff_member_required
@tab_required("orders")
def order_return(request, pk):
    order = get_object_or_404(Order, pk=pk)
    may_edit = can(request.user, "orders", LEVEL_EDIT)
    chosen, plan, error = [], None, ""

    if request.method == "POST":
        chosen = _chosen(request)
        if request.POST.get("action") == "confirm":
            if not may_edit:
                raise PermissionDenied(
                    "Проводить возврат может сотрудник с правом редактировать заказы"
                )
            try:
                ret = make_return(order.pk, chosen, by=request.user.get_username())
            except ReturnError as e:
                error = str(e)
            else:
                StaffAudit.write(
                    request,
                    f"возврат по заказу {order.order_id}: {_rub(ret.amount_kop)} ₽, "
                    f"баллов +{ret.points_returned} / −{ret.points_revoked}",
                )
                request.session["order_return_note"] = (
                    f"Возврат проведён: {_rub(ret.amount_kop)} ₽. Баллов возвращено "
                    f"{ret.points_returned}, снято начисленных {ret.points_revoked}."
                )
                # POST → redirect → GET: обновление страницы не повторит возврат.
                return redirect(request.path)
        else:
            try:
                plan = preview(order, chosen)
            except ReturnError as e:
                error = str(e)

    order.refresh_from_db()
    try:
        rows = return_plan(order)
    except ReturnError as e:
        rows, error = [], error or str(e)
    for row in rows:
        row["gross_rub"] = _rub(row["gross"])
        row["paid_rub"] = _rub(row["paid"])
        row["is_delivery"] = row["subject"] != "commodity"
        row["checked"] = row["index"] in chosen
    if plan:
        plan["amount_rub"] = _rub(plan["amount_kop"])

    returns = [
        {
            "when": timezone.localtime(r.created_at).strftime("%d.%m.%Y %H:%M"),
            "amount": _rub(r.amount_kop),
            "back": r.points_returned,
            "off": r.points_revoked,
            "status": r.get_status_display(),
            "by": r.created_by,
            "error": r.error,
        }
        for r in order.returns.all()
    ]

    ctx = {
        **admin.site.each_context(request),
        "title": f"Возврат по заказу {order.order_id}",
        "order": order,
        "rows": rows,
        "plan": plan,
        "chosen": chosen,
        "error": error,
        "note": request.session.pop("order_return_note", ""),
        "may_edit": may_edit,
        "returnable": order.payment_status in RETURNABLE and bool(order.payment_id),
        "returns": returns,
        "paid_rub": _rub(round(float(order.total or 0) * 100)),
        "payment_label": PAYMENT_LABELS.get(order.payment_status, order.payment_status),
        "redeemed": redeemed_for(order),
        "earned": earned_for(order),
    }
    return TemplateResponse(request, "admin/order_return.html", ctx)
