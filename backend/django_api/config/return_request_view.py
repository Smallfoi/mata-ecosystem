"""Страница заявки на возврат в админке (D-112, D-123).

Сотрудник склада видит заявку целиком: что вернули и почему, фото покупателя,
как сдаёт (магазин / посылка, трек-номер). Когда вещи пришли — «Товар получен»,
после осмотра — решение ПО КАЖДОЙ ВЕЩИ: принять или отказать с причинами,
пояснение и фото осмотра. «Вынести решение» возвращает деньги за принятые вещи
(ЮKassa, без её чека — чек возврата пробивает касса в 1С) и сообщает покупателю.

Права: «смотреть» — видеть заявку; «редактировать» — отмечать получение,
решать и загружать фото. Это деньги покупателя.
"""
from django.contrib import admin
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.utils import timezone

from orders import return_requests as rr
from orders.models import ReturnPhoto, ReturnRequest
from orders.returns import ReturnError, return_plan
from staff.access import can, tab_required
from staff.models import LEVEL_EDIT, StaffAudit


def _rub(kop):
    return f"{kop / 100:,.2f}".replace(",", " ")


def _local(dt):
    return timezone.localtime(dt).strftime("%d.%m.%Y %H:%M") if dt else ""


def _decisions(request, req) -> dict:
    out = {}
    for line in req.lines:
        i = int(line["index"])
        out[i] = {"decision": request.POST.get(f"decision_{i}", ""),
                  "reasons": request.POST.getlist(f"reasons_{i}")}
    return out


def _kop(value) -> int:
    try:
        return max(0, int(round(float(str(value).replace(",", ".")) * 100)))
    except (TypeError, ValueError):
        return 0


@staff_member_required
@tab_required("orders")
def return_request_page(request, pk):
    req = get_object_or_404(ReturnRequest.objects.select_related("order"), pk=pk)
    may_edit = can(request.user, "orders", LEVEL_EDIT)
    who = request.user.get_username()
    error = ""
    posted = {}

    if request.method == "POST":
        if not may_edit:
            raise PermissionDenied("Решать по возврату может сотрудник с правом "
                                   "редактировать заказы")
        action = request.POST.get("action")
        try:
            if action == "received":
                rr.mark_received(req, who)
                StaffAudit.write(request, f"возврат {req.number}: товар получен")
                request.session["rr_note"] = "Отмечено: товар получен. Осмотрите вещи и вынесите решение."
            elif action == "photo":
                files = request.FILES.getlist("photos")
                if not files:
                    raise rr.RequestError("Выберите фото")
                for f in files:
                    rr.upload_photo("", f, kind=ReturnPhoto.INSPECTION, request=req)
                request.session["rr_note"] = f"Фото осмотра добавлено: {len(files)}"
            elif action == "decide":
                posted = _decisions(request, req)
                if req.defect_claimed:
                    confirmed = request.POST.get("defect_confirmed")
                    req.defect_confirmed = (True if confirmed == "yes" else
                                            False if confirmed == "no" else None)
                    req.customer_shipping_kop = _kop(request.POST.get("shipping_rub"))
                    req.save(update_fields=["defect_confirmed", "customer_shipping_kop"])
                done = rr.decide(req, posted, request.POST.get("note", ""), who)
                StaffAudit.write(request, f"возврат {done.number}: {done.get_status_display()}")
                money = (f" Деньги: {_rub(done.order_return.amount_kop)} ₽ "
                         f"({done.order_return.get_status_display().lower()})."
                         if done.order_return else "")
                request.session["rr_note"] = (
                    f"Решение вынесено: {done.get_status_display()}.{money} Покупателю "
                    "отправлено уведомление. Чек возврата пробейте на кассе в 1С.")
            elif action == "goods_back_done":
                rr.mark_goods_back_done(req, who)
                StaffAudit.write(request, f"возврат {req.number}: вещи отданы покупателю")
                request.session["rr_note"] = "Отмечено: вещи отданы или отправлены покупателю."
            else:
                raise rr.RequestError("Неизвестное действие")
        except rr.RequestError as e:
            error = e.detail
        else:
            # POST → redirect → GET: обновление страницы не повторит действие.
            return redirect(request.path)

    req.refresh_from_db()
    try:
        names = {row["index"]: (row["name"], row["paid"]) for row in return_plan(req.order)}
    except ReturnError:
        names = {}
    lines = []
    for line in req.lines:
        i = int(line["index"])
        name, paid = names.get(i, (f"позиция {i}", 0))
        sent = posted.get(i, {})
        defect = line.get("reason") in rr.QUALITY
        lines.append({
            "index": i,
            "name": name,
            "paid": _rub(paid),
            "reason": rr.REASONS.get(line.get("reason"), line.get("reason")),
            "comment": line.get("comment") or "",
            "defect": defect,
            "decision": line.get("decision") or sent.get("decision", ""),
            "reject_labels": [rr.REJECT_REASONS.get(r, r) for r in line.get("rejectReasons") or []],
            "chosen": set(sent.get("reasons") or []),
            # По браку ярлыки/упаковка/код — не основание (ст. 18): этих галочек нет.
            "reasons": [(code, label) for code, label in rr.REJECT_REASONS.items()
                        if not (defect and code in rr.NOT_FOR_DEFECT)],
        })

    ctx = {
        **admin.site.each_context(request),
        "title": f"Возврат {req.number}",
        "req": req,
        "lines": lines,
        "error": error,
        "note": request.session.pop("rr_note", ""),
        "may_edit": may_edit,
        "customer_photos": rr.photo_urls(req),
        "inspection_photos": rr.photo_urls(req, ReturnPhoto.INSPECTION),
        "created": _local(req.created_at),
        "bring_until": _local(req.bring_until),
        "sent_at": _local(req.sent_at),
        "received": _local(req.received_at),
        "decided": _local(req.decided_at),
        "refund": _rub(req.order_return.amount_kop) if req.order_return else "",
        "can_receive": req.status in (ReturnRequest.AWAITING, ReturnRequest.SENT,
                                      ReturnRequest.EXPIRED),
        "can_decide": req.status == ReturnRequest.RECEIVED,
        "needs_goods_back": (req.status in (ReturnRequest.REJECTED, ReturnRequest.PARTIAL)
                             and not req.goods_back_done),
        "max_photos": rr.MAX_PHOTOS,
        "shipping_rub": (f"{req.customer_shipping_kop / 100:.2f}"
                         if req.customer_shipping_kop else ""),
    }
    return TemplateResponse(request, "admin/orders/return_request.html", ctx)
