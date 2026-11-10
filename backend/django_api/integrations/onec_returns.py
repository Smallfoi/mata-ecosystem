"""Возвраты и отмены → 1С (D-123; паспорт интеграции — `docs/INTEGRATION_1C.md` §7.4).

Тот же порядок, что у заказов (onec_orders.py): 1С забирает очередь сама и
подтверждает приём — сервер 1С за NAT, а потерянный возврат — это расхождение
кассы и склада.

**Что попадает в очередь.** Возврат, деньги по которому ЮKassa уже вернула
(`done`), по заказу, который 1С у себя создавала. Один возврат — один документ в
1С, номер `<номер заказа>-В<n>` (у заявки покупателя тот же номер).

- `type: "return"` — вещи были у покупателя и вернулись: сотрудник пробивает чек
  возврата на кассе и возвращает коды «Честного знака» в оборот (это умеет 1С).
- `type: "cancel"` — заказ отменён до передачи курьеру: вещи со склада не уходили,
  чек продажи не пробивался — документ заказа в 1С отменить, чек не нужен.

Возврат по заказу, которого 1С не видела (отменён раньше, чем 1С его забрала), в
очередь не идёт: отменять в 1С нечего.
"""
from django.utils import timezone

from orders.models import OrderReturn
from orders.money import kop_to_float

from .onec_orders import _article_index, _price

MAX_RETURNS_PER_PULL = 200


def _units(payload: dict) -> list:
    """Позиции чека → строки заказа: та же раскладка, что в `orders/receipt._lines`
    (каждая единица товара — своя позиция, доставка — последней)."""
    out = []
    for raw in payload.get("items") or []:
        if not isinstance(raw, dict):
            continue
        try:
            qty = max(1, int(raw.get("quantity") or 1))
        except (TypeError, ValueError):
            qty = 1
        price = raw.get("price")
        try:
            positive = float(price or 0) > 0
        except (TypeError, ValueError):
            positive = False
        if not positive:
            continue
        out.extend([raw] * qty)
    return out


def _reasons(ret) -> dict:
    """Индекс позиции → причина покупателя (если возврат по заявке)."""
    from orders.return_requests import REASONS

    req = getattr(ret, "request", None)
    if req is None:
        return {}
    return {int(line["index"]): (line.get("reason") or "", REASONS.get(line.get("reason"), ""))
            for line in req.lines}


def return_to_json(ret: OrderReturn) -> dict:
    """Возврат в виде, описанном в паспорте для 1С (§7.4)."""
    from orders.receipt import allocate
    from orders.money import kop_to_rub

    order = ret.order
    payload = order.payload or {}
    checkout = payload.get("checkoutData") or {}
    index = _article_index(payload)
    units = _units(payload)
    try:
        paid = {row["index"]: row["paid"] for row in allocate(payload, kop_to_rub(order.amount_kop))}
    except ValueError:
        paid = {}
    reasons = _reasons(ret)

    # Одинаковые вещи (тот же товар, размер, цвет) — одной строкой с количеством.
    items, by_key, delivery_kop = [], {}, 0
    for i in sorted(int(x) for x in ret.lines):
        if i >= len(units):
            delivery_kop += paid.get(i, 0)
            continue
        raw = units[i]
        pid = str(raw.get("productId") or "")
        reason, reason_label = reasons.get(i, ("", ""))
        key = (pid, raw.get("size") or "", raw.get("color") or "", reason)
        if key in by_key:
            row = by_key[key]
            row["qty"] += 1
            row["_refund_kop"] += paid.get(i, 0)
            continue
        known = index.get(pid) or {}
        row = {
            "id": known.get("external_id") or "",
            "article": known.get("article") or "",
            "barcodes": known.get("barcodes") or [],
            "productId": pid,
            "name": raw.get("productName") or "",
            "size": raw.get("size") or "",
            "color": raw.get("color") or "",
            "qty": 1,
            "price": _price(raw.get("price")),
            "reason": reason,
            "reasonLabel": reason_label,
            "_refund_kop": paid.get(i, 0),
        }
        by_key[key] = row
        items.append(row)
    for row in items:
        # Сколько денег вернули за строку: из чека, со скидкой баллами по позиции.
        row["refund"] = kop_to_float(row.pop("_refund_kop"))

    return {
        "returnId": ret.number,
        "type": ret.kind,
        "orderId": order.order_id,
        # Ваш номер документа заказа, если вы его присылали в статусе (§7.3).
        "orderDocument": order.onec_number,
        "createdAt": ret.created_at.isoformat(),
        "customer": {
            "phone": checkout.get("phone") or "",
            "name": checkout.get("name") or "",
            "email": checkout.get("email") or "",
        },
        "items": items,
        # Доставка возвращается вместе с последней вещью заказа (правила возврата §4.5).
        "deliveryRefund": kop_to_float(delivery_kop),
        "amount": kop_to_float(ret.amount_kop),
        "pointsReturned": ret.points_returned,
        "pointsRevoked": ret.points_revoked,
        "refundId": ret.refund_id,
        "test": order.is_test,
    }


def pending_returns(limit: int = MAX_RETURNS_PER_PULL):
    """Очередь: проведённые возвраты по заказам, которые 1С забирала, — старые первыми."""
    limit = max(1, min(int(limit or MAX_RETURNS_PER_PULL), MAX_RETURNS_PER_PULL))
    return list(
        OrderReturn.objects.select_related("order")
        .filter(status="done", onec_taken_at__isnull=True,
                order__onec_taken_at__isnull=False)
        .order_by("created_at")[:limit]
    )


def _by_number(numbers) -> dict:
    """Номер возврата → запись. Номер «<заказ>-В<n>» разбираем на заказ и n."""
    out = {}
    for number in numbers:
        order_id, sep, tail = number.rpartition("-В")
        if not sep:
            continue
        qs = OrderReturn.objects.select_related("order").filter(order__order_id=order_id)
        if tail.startswith("-"):  # старый вид «<заказ>-В-<pk>» без номера в заказе
            try:
                ret = qs.filter(pk=int(tail[1:]), seq__isnull=True).first()
            except ValueError:
                ret = None
        else:
            try:
                ret = qs.filter(seq=int(tail)).first()
            except ValueError:
                ret = None
        if ret is not None:
            out[number] = ret
    return out


def mark_taken(return_ids, documents=None) -> dict:
    """Снять возвраты с очереди. Повторный `ack` не ошибка. `documents` — по желанию:
    {номер возврата: номер документа в 1С} — попадёт в карточку заказа у владельца."""
    wanted = list(dict.fromkeys(str(r).strip() for r in (return_ids or []) if str(r or "").strip()))
    docs = documents if isinstance(documents, dict) else {}
    found = _by_number(wanted)
    now = timezone.now()
    acked = 0
    for number, ret in found.items():
        fields = []
        doc = str(docs.get(number) or "").strip()[:64]
        if doc and ret.onec_number != doc:
            ret.onec_number = doc
            fields.append("onec_number")
        if ret.onec_taken_at is None:
            ret.onec_taken_at = now
            fields.append("onec_taken_at")
            acked += 1
        if fields:
            ret.save(update_fields=fields)
    unknown = [n for n in wanted if n not in found]
    return {"acked": acked, "unknown": unknown}
