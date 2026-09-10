"""Обратный поток обмена с 1С: заказы МАТА → 1С и статусы обратно (D-62; паспорт интеграции — `docs/INTEGRATION_1C.md` §7).

**Почему 1С забирает, а не мы отправляем.** Сервер 1С почти всегда стоит внутри
сети магазина, за NAT — постучаться к нему снаружи нельзя. Поэтому направление то
же, что и у остальных потоков обмена: 1С сама приходит к нам, тем же токеном.

**Почему выдача и подтверждение — два разных запроса.** Заказ снимается с очереди
только после явного `ack`, когда 1С уже создала документ у себя. Если связь
оборвалась на полпути, заказ просто придёт в следующей выборке. Отдать и сразу
забыть — значит однажды молча потерять заказ, а это деньги покупателя.

**Какие заказы отдаём.** Только оплату, подтверждённую ЮKassa (D-72): статус `paid`
и номер платежа ЮKassa. Ожидание оплаты, отмена, «оплачено» в режиме разработки без
настоящего платежа — на склад не уходят. Иначе кладовщик собирает то, за что никто
не заплатил.
"""
from django.utils import timezone

from catalog.models import Product
from orders.models import Order

# Статус 1С → наш статус заказа. Часть этапов 1С у нас не имеет пары: «принят» и
# «собран» — это внутренняя кухня склада, покупателю мы показываем их отдельной
# строкой, а общий статус заказа не трогаем.
STATUS_MAP = {
    "accepted": None,
    "assembled": None,
    "shipped": "shipped",
    "delivered": "delivered",
    "canceled": "cancelled",
    "cancelled": "cancelled",
}

# Что видит покупатель в уведомлении.
STATUS_TITLES = {
    "accepted": "Заказ принят",
    "assembled": "Заказ собран",
    "shipped": "Заказ отправлен",
    "delivered": "Заказ доставлен",
    "canceled": "Заказ отменён",
    "cancelled": "Заказ отменён",
}

MAX_ORDERS_PER_PULL = 200


def _article_index(payload: dict) -> dict:
    """`productId` наших заказов → артикул и id в 1С.

    В заказе лежит наш внутренний идентификатор товара, а 1С знает свой. Без этой
    подстановки складу пришлось бы сопоставлять позиции по названию.
    """
    ids = [
        str(i.get("productId") or "")
        for i in (payload.get("items") or [])
        if isinstance(i, dict)
    ]
    rows = Product.objects.filter(id__in=[i for i in ids if i]).values(
        "id", "article", "external_id"
    )
    return {r["id"]: r for r in rows}


def order_to_json(order: Order) -> dict:
    """Заказ в виде, описанном в ТЗ для 1С (`docs/INTEGRATION_1C.md` §7)."""
    payload = order.payload or {}
    checkout = payload.get("checkoutData") or {}
    index = _article_index(payload)

    items = []
    for raw in payload.get("items") or []:
        if not isinstance(raw, dict):
            continue
        pid = str(raw.get("productId") or "")
        known = index.get(pid) or {}
        items.append({
            "id": known.get("external_id") or "",
            "article": known.get("article") or "",
            "productId": pid,
            "name": raw.get("productName") or "",
            "size": raw.get("size") or "",
            "color": raw.get("color") or "",
            "qty": int(raw.get("quantity") or 1),
            "price": raw.get("price"),
        })

    address = ", ".join(
        str(checkout.get(k) or "").strip()
        for k in ("city", "street", "house", "apartment")
        if str(checkout.get(k) or "").strip()
    )
    return {
        "orderId": order.order_id,
        "createdAt": order.created_at.isoformat(),
        "customer": {
            "phone": checkout.get("phone") or "",
            "name": checkout.get("name") or "",
            "email": checkout.get("email") or "",
        },
        "items": items,
        "total": order.total,
        "deliveryCost": payload.get("deliveryCost"),
        "pointsRedeemed": order.points_redeemed,
        "payment": checkout.get("paymentType") or "",
        "paymentStatus": order.payment_status,
        "delivery": checkout.get("deliveryType") or "",
        "address": address,
        "postalCode": checkout.get("postalCode") or "",
    }


def pending_orders(limit: int = MAX_ORDERS_PER_PULL):
    """Очередь на выдачу: не забранные и готовые к сборке, самые старые первыми."""
    limit = max(1, min(int(limit or MAX_ORDERS_PER_PULL), MAX_ORDERS_PER_PULL))
    return list(
        Order.objects.filter(onec_taken_at__isnull=True, payment_status="paid")
        # Номер платежа ЮKassa — доказательство, что деньги прошли через неё.
        .exclude(payment_id="")
        .order_by("created_at")[:limit]
    )


def mark_taken(order_ids) -> dict:
    """Снять заказы с очереди. Повторный `ack` не ошибка — связь могла оборваться
    уже после записи, и 1С честно повторит."""
    wanted = [str(o).strip() for o in order_ids if str(o or "").strip()]
    if not wanted:
        return {"acked": 0, "unknown": []}
    rows = list(Order.objects.filter(order_id__in=wanted))
    found = {r.order_id for r in rows}
    fresh = [r for r in rows if r.onec_taken_at is None]
    now = timezone.now()
    for r in fresh:
        r.onec_taken_at = now
    if fresh:
        Order.objects.bulk_update(fresh, ["onec_taken_at"], batch_size=200)
    return {"acked": len(fresh), "unknown": sorted(set(wanted) - found)}


def apply_statuses(items) -> dict:
    """Статусы из 1С. Покупатель видит их в приложении и получает уведомление."""
    updated = 0
    errors = []
    wanted = {}
    for raw in items:
        if not isinstance(raw, dict):
            errors.append("элемент не объект")
            continue
        oid = str(raw.get("orderId") or "").strip()
        status = str(raw.get("status") or "").strip().lower()
        if not oid:
            errors.append("нет orderId")
            continue
        if status not in STATUS_MAP:
            errors.append(f"{oid}: неизвестный статус «{status}»")
            continue
        wanted[oid] = raw

    rows = {o.order_id: o for o in Order.objects.filter(order_id__in=list(wanted))}
    changed = []
    notify = []
    for oid, raw in wanted.items():
        order = rows.get(oid)
        if order is None:
            errors.append(f"{oid}: заказ не найден")
            continue
        status = str(raw["status"]).strip().lower()
        number = str(raw.get("number") or "").strip()[:64]

        # Тот же статус второй раз — не ошибка и не повод слать уведомление снова.
        if order.onec_status == status and (not number or order.onec_number == number):
            continue

        order.onec_status = status
        order.onec_status_at = timezone.now()
        if number:
            order.onec_number = number
        ours = STATUS_MAP[status]
        if ours:
            order.status = ours
        # Заказ, статус которого пришёл, точно у 1С — даже если ack потерялся.
        if order.onec_taken_at is None:
            order.onec_taken_at = timezone.now()
        changed.append(order)
        notify.append((order, status))

    if changed:
        Order.objects.bulk_update(
            changed,
            ["status", "onec_status", "onec_status_at", "onec_number", "onec_taken_at"],
            batch_size=200,
        )
        updated = len(changed)

    # Уведомляем сами: `bulk_update` не поднимает сигналы модели, а через них
    # обычно и уходит уведомление о смене статуса заказа (orders/signals.py).
    from notifications.models import create_notification

    for order, status in notify:
        create_notification(
            order.user_id,
            STATUS_TITLES.get(status, "Статус заказа изменён"),
            f"Заказ №{order.order_id}",
            type="order",
            order_id=order.order_id,
        )

    return {"received": len(items), "updated": updated, "errors": errors[:20]}
