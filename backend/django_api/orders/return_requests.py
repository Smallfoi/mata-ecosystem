"""Заявки покупателей на возврат (D-112).

Сценарий собран по Спортмастеру, adidas, Nike и Street Beat (их онлайн-заявка +
приёмка в магазине) и по закону (ЗоЗПП ст. 18, 22, 26.1; КС РФ 7-П от 17.02.2026):

1. Покупатель сам оформляет заявку в приложении: вещи, причина по каждой, способ
   сдачи — принесёт в магазин или пришлёт посылкой за свой счёт. Посылку закон
   отклонять не разрешает (КС 7-П), но доставка и риск в пути — на покупателе.
2. У заявки срок «сдать товар до» (BRING_DAYS). Не успел — заявка истекает, но
   новую можно подать, пока не кончился срок возврата.
3. Сотрудник отмечает «товар получен» и осматривает его в магазине: срок, вид,
   ярлыки, упаковка, «Честный знак». Решение — одобрить или отказать с причиной.
   Отказ по заявленному браку — только по итогам проверки качества, не из-за
   ярлыков, упаковки или кода маркировки.
4. Одобрено — деньги уходят существующим возвратом по строкам чека (D-73).
   Брак подтверждён — компенсируем и расходы покупателя на доставку до магазина
   (выплачиваются отдельно: возврат ЮKassa не может превысить оплату).
"""
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import Order, ReturnRequest
from .returns import RETURNABLE, ReturnError, make_return, return_plan

# Срок возврата вещи без брака — со дня получения (решение владельца, D-73).
# ВНИМАНИЕ (ст. 26.1 п. 4): 7 дней законны, только если памятка о возврате вручена
# письменно при доставке; иначе срок — 3 месяца.
RETURN_DAYS = 7
# Брак — в пределах двух лет (ст. 19 ЗоЗПП, если гарантийный срок не установлен).
DEFECT_DAYS = 730
# Сколько дней действует заявка, чтобы принести или отправить вещь.
BRING_DAYS = 7

REASONS = {
    "size": "Не подошёл размер",
    "style": "Не подошёл цвет или фасон",
    "defect": "Брак или дефект",
    "not_as_described": "Не соответствует описанию",
    "wrong_item": "Пришёл не тот товар",
    "other": "Другое",
}
# Причины, по которым вещь — не товар надлежащего качества: срок как у брака.
QUALITY = {"defect", "wrong_item", "not_as_described"}


class RequestError(Exception):
    """Заявку оформить/изменить нельзя — текст для покупателя или сотрудника."""

    def __init__(self, detail, status=400):
        super().__init__(detail)
        self.detail = detail
        self.status = status


def received_at(order):
    """Когда покупатель получил заказ. Точной даты нет (самовывоз, курьер) —
    берём самую позднюю известную: отправку/доставку из 1С или оформление."""
    base = order.created_at
    if order.onec_status in ("shipped", "delivered") and order.onec_status_at:
        base = max(base, order.onec_status_at)
    return base


def _windows(order, now=None):
    now = now or timezone.now()
    got = received_at(order)
    return {
        "standardUntil": got + timedelta(days=RETURN_DAYS),
        "defectUntil": got + timedelta(days=DEFECT_DAYS),
        "standardOpen": now <= got + timedelta(days=RETURN_DAYS),
        "defectOpen": now <= got + timedelta(days=DEFECT_DAYS),
    }


def _busy(order):
    """Позиции, уже заявленные в активных заявках."""
    out = set()
    for req in order.return_requests.filter(status__in=ReturnRequest.ACTIVE):
        out.update(int(line["index"]) for line in req.lines)
    return out


def options(order):
    """Что из заказа можно вернуть и до какого срока — для экрана заявки."""
    base = {"canReturn": False, "lines": [], "reasons": REASONS,
            "returnDays": RETURN_DAYS, "bringDays": BRING_DAYS}
    if order.payment_status not in RETURNABLE or not order.payment_id:
        return {**base, "reason": "Вернуть можно оплаченный заказ"}
    try:
        rows = return_plan(order)
    except ReturnError as e:
        return {**base, "reason": str(e)}
    busy = _busy(order)
    win = _windows(order)
    lines = [{
        "index": row["index"],
        "name": row["name"],
        "paid": row["paid"] / 100,
        "available": not row["returned"] and row["index"] not in busy,
        "status": ("returned" if row["returned"] else
                   "requested" if row["index"] in busy else "available"),
    } for row in rows if row["subject"] == "commodity"]
    can = win["defectOpen"] and any(line["available"] for line in lines)
    return {
        **base,
        "canReturn": can,
        "reason": "" if can else "Сейчас вернуть нечего",
        "lines": lines,
        "standardUntil": win["standardUntil"].isoformat(),
        "standardOpen": win["standardOpen"],
        "defectUntil": win["defectUntil"].isoformat(),
        "store": _store_info(),
    }


def _store_info() -> dict:
    """Куда нести: способ «самовывоз» из «Магазин → Доставка» (ведёт владелец)."""
    from .models import ShippingOption

    pickup = ShippingOption.objects.filter(kind=ShippingOption.PICKUP).first()
    return {"name": pickup.name if pickup else "Магазин МАТА",
            "description": pickup.description if pickup else ""}


def _parse_lines(raw_lines, available, win):
    lines, seen = [], set()
    for raw in raw_lines:
        if not isinstance(raw, dict):
            raise RequestError("Некорректная позиция")
        try:
            index = int(raw.get("index"))
        except (TypeError, ValueError):
            raise RequestError("Некорректная позиция") from None
        if index in seen:
            continue
        seen.add(index)
        if index not in available:
            raise RequestError("Эту вещь уже вернули или по ней есть заявка", 409)
        reason = str(raw.get("reason") or "")
        if reason not in REASONS:
            raise RequestError("Укажите причину возврата")
        comment = str(raw.get("comment") or "").strip()[:500]
        if reason in ("defect", "other") and len(comment) < 5:
            raise RequestError("Опишите, что не так с вещью")
        if reason in QUALITY:
            if not win["defectOpen"]:
                raise RequestError("Срок предъявления претензии по качеству истёк")
        elif not win["standardOpen"]:
            raise RequestError(
                f"Вещь без брака можно вернуть в течение {RETURN_DAYS} дней со дня "
                "получения — этот срок истёк. Если есть брак, выберите причину «Брак».")
        lines.append({"index": index, "reason": reason, "comment": comment})
    return lines


def create(order, user_id, raw_lines, method):
    """Оформить заявку покупателя. Бросает RequestError."""
    if method not in (ReturnRequest.STORE, ReturnRequest.PARCEL):
        raise RequestError("Выберите, как сдадите товар")
    if not isinstance(raw_lines, list) or not raw_lines:
        raise RequestError("Отметьте, что возвращаете")
    with transaction.atomic():
        # Блокировка заказа: две одновременные заявки не заявят одну вещь дважды.
        order = Order.objects.select_for_update().get(pk=order.pk)
        opts = options(order)
        if not opts["lines"]:
            raise RequestError(opts["reason"] or "Этот заказ вернуть нельзя")
        available = {line["index"] for line in opts["lines"] if line["available"]}
        lines = _parse_lines(raw_lines, available, _windows(order))
        req = ReturnRequest.objects.create(
            order=order, user_id=user_id, lines=lines, method=method,
            defect_claimed=any(line["reason"] in QUALITY for line in lines),
            bring_until=timezone.now() + timedelta(days=BRING_DAYS),
        )
    how = ("принесите вещи в магазин МАТА" if method == ReturnRequest.STORE
           else "отправьте вещи посылкой в магазин МАТА")
    _notify(req, "Заявка на возврат принята",
            f"Заявка {req.number}: {how} до {timezone.localtime(req.bring_until):%d.%m}. "
            "Вещи — с ярлыками и в упаковке.")
    return req


def cancel(req):
    with transaction.atomic():
        req = ReturnRequest.objects.select_for_update().get(pk=req.pk)
        if req.status != ReturnRequest.AWAITING:
            raise RequestError("Заявку уже нельзя отменить: товар получен магазином", 409)
        req.status = ReturnRequest.CANCELED
        req.save(update_fields=["status"])
    return req


def mark_received(req, by=""):
    with transaction.atomic():
        req = ReturnRequest.objects.select_for_update().get(pk=req.pk)
        if req.status not in (ReturnRequest.AWAITING, ReturnRequest.EXPIRED):
            raise RequestError("Товар по этой заявке уже принят или решение вынесено")
        req.status = ReturnRequest.RECEIVED
        req.received_at = timezone.now()
        req.save(update_fields=["status", "received_at"])
    _notify(req, "Товар получен", f"Заявка {req.number}: вещи у нас, проверяем. "
                                  "Решение сообщим в приложении.")
    return req


def approve(req, by=""):
    """Одобрить: вернуть деньги по строкам заявки (D-73). Бросает RequestError."""
    req = ReturnRequest.objects.get(pk=req.pk)
    if req.status != ReturnRequest.RECEIVED:
        raise RequestError("Одобрить можно только заявку с полученным товаром")
    try:
        ret = make_return(req.order_id, [line["index"] for line in req.lines], by=by)
    except ReturnError as e:
        raise RequestError(str(e)) from e
    with transaction.atomic():
        req = ReturnRequest.objects.select_for_update().get(pk=req.pk)
        req.status = ReturnRequest.APPROVED
        req.order_return = ret
        req.decided_at = timezone.now()
        req.decided_by = by[:150]
        req.save(update_fields=["status", "order_return", "decided_at", "decided_by"])
    text = (f"Заявка {req.number} одобрена: вернём {ret.amount_kop / 100:.2f} ₽ тем же "
            "способом, которым платили, — обычно за 1–3 дня, по закону до 10 дней.")
    if req.defect_confirmed and req.customer_shipping_kop:
        text += (f" Расходы на доставку {req.customer_shipping_kop / 100:.2f} ₽ "
                 "компенсируем отдельно.")
    _notify(req, "Возврат одобрен", text)
    return req


def reject(req, note, by=""):
    note = str(note or "").strip()
    if len(note) < 5:
        raise RequestError("Напишите покупателю причину отказа")
    with transaction.atomic():
        req = ReturnRequest.objects.select_for_update().get(pk=req.pk)
        if req.status != ReturnRequest.RECEIVED:
            raise RequestError("Отказать можно только после осмотра полученного товара")
        req.status = ReturnRequest.REJECTED
        req.decision_note = note[:500]
        req.decided_at = timezone.now()
        req.decided_by = by[:150]
        req.save(update_fields=["status", "decision_note", "decided_at", "decided_by"])
    _notify(req, "В возврате отказано", f"Заявка {req.number}: {note}")
    return req


def expire_stale(now=None):
    """Заявки, по которым товар так и не сдали, — в «истекла» (beat)."""
    now = now or timezone.now()
    stale = list(ReturnRequest.objects.select_related("order").filter(
        status=ReturnRequest.AWAITING, bring_until__lt=now))
    for req in stale:
        req.status = ReturnRequest.EXPIRED
        req.save(update_fields=["status"])
        _notify(req, "Заявка на возврат истекла",
                f"Заявка {req.number}: товар не сдан в срок. Если срок возврата ещё "
                "не прошёл, оформите новую заявку.")
    return len(stale)


def to_json(req) -> dict:
    return {
        "id": req.pk,
        "number": req.number,
        "orderId": req.order.order_id,
        "status": req.status,
        "statusLabel": req.get_status_display(),
        "method": req.method,
        "lines": req.lines,
        "bringUntil": req.bring_until.isoformat(),
        "decisionNote": req.decision_note,
        "refundRub": (req.order_return.amount_kop / 100) if req.order_return else None,
        "createdAt": req.created_at.isoformat(),
    }


def _notify(req, title, body):
    try:
        from notifications.models import create_notification

        create_notification(req.user_id, title, body, "order", req.order.order_id)
    except Exception:
        # Уведомление — не часть заявки: решение уже записано.
        pass
