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
from orders.money import kop_to_float, to_kop

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


def _price(value):
    """Цена строки — числом с копейками (Decimal, ROUND_HALF_UP → float, как было
    в контракте). Не число (заказы до серверного снимка) — как есть."""
    try:
        return kop_to_float(to_kop(value)) if value not in (None, "") else value
    except ValueError:
        return value


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
            "price": _price(raw.get("price")),
        })

    address = ", ".join(
        str(checkout.get(k) or "").strip()
        for k in ("city", "street", "house", "apartment")
        if str(checkout.get(k) or "").strip()
    )
    return {
        "orderId": order.order_id,
        # Глобальный номер заказа на сервере (аудит B06): `orderId` уникален только
        # вместе с покупателем. ack и статусы — по нему.
        "serverId": order.pk,
        "createdAt": order.created_at.isoformat(),
        "customer": {
            "phone": checkout.get("phone") or "",
            "name": checkout.get("name") or "",
            "email": checkout.get("email") or "",
        },
        "items": items,
        # Из копеек (аудит B09): то же число, что в платеже и чеке.
        "total": kop_to_float(order.amount_kop),
        "deliveryCost": payload.get("deliveryCost"),
        "pointsRedeemed": order.points_redeemed,
        "payment": checkout.get("paymentType") or "",
        "paymentStatus": order.payment_status,
        # Тестовый заказ: оплачен симуляцией, денег не было. В 1С его можно
        # принять и провести весь путь, но продажей считать нельзя (D-97).
        "test": order.is_test,
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


def _given_to_1c(order: Order) -> bool:
    """Мог ли этот заказ вообще попасть в 1С: уже забран или стоит в очереди."""
    if order.onec_taken_at is not None:
        return True
    return order.payment_status == "paid" and bool(order.payment_id)


def _parse_server_id(value):
    try:
        pk = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return pk if pk > 0 else None


def _resolve_numbers(numbers) -> tuple[dict, list, list]:
    """Короткие номера заказов (`orderId`) → заказы (аудит B06).

    Номер придумывает приложение, уникален он только вместе с пользователем. Если
    под номером один заказ — берём его (старый контракт 1С). Если несколько —
    смотрим, какой из них 1С вообще могла получить (оплачен ЮKassa или уже забран);
    один такой — он. Иначе номер неоднозначен: не трогаем ни один заказ, а просим
    1С прислать `serverId`.

    Возвращает (номер → заказ, неизвестные, неоднозначные).
    """
    numbers = list(dict.fromkeys(numbers))
    by_number: dict = {}
    for row in Order.objects.filter(order_id__in=numbers):
        by_number.setdefault(row.order_id, []).append(row)
    found, unknown, ambiguous = {}, [], []
    for number in numbers:
        rows = by_number.get(number) or []
        if not rows:
            unknown.append(number)
            continue
        if len(rows) > 1:
            rows = [r for r in rows if _given_to_1c(r)]
        if len(rows) == 1:
            found[number] = rows[0]
        else:
            ambiguous.append(number)
    return found, unknown, ambiguous


def _ambiguous_error(number: str) -> str:
    return (f"{number}: номер неоднозначен (есть у нескольких покупателей) — "
            f"пришлите serverId из выдачи заказов")


def mark_taken(order_ids, server_ids=None) -> dict:
    """Снять заказы с очереди. Повторный `ack` не ошибка — связь могла оборваться
    уже после записи, и 1С честно повторит.

    `server_ids` — глобальные номера заказов (`serverId` из выдачи), однозначные.
    `order_ids` — короткие номера (старый контракт): неоднозначный номер не снимает
    с очереди ни один заказ и возвращается в `ambiguous`.
    """
    wanted = [str(o).strip() for o in (order_ids or []) if str(o or "").strip()]
    raw_pks = [str(o).strip() for o in (server_ids or []) if str(o or "").strip()]
    pks = {p for p in (_parse_server_id(v) for v in raw_pks) if p}

    rows = {}
    unknown, ambiguous = [], []
    if wanted:
        found, unknown, ambiguous = _resolve_numbers(wanted)
        rows.update({r.pk: r for r in found.values()})
    unknown_pks = []
    if raw_pks:
        by_pk = {r.pk: r for r in Order.objects.filter(pk__in=pks)}
        rows.update(by_pk)
        unknown_pks = [v for v in dict.fromkeys(raw_pks)
                       if _parse_server_id(v) not in by_pk]

    fresh = [r for r in rows.values() if r.onec_taken_at is None]
    now = timezone.now()
    for r in fresh:
        r.onec_taken_at = now
    if fresh:
        Order.objects.bulk_update(fresh, ["onec_taken_at"], batch_size=200)
    return {"acked": len(fresh), "unknown": sorted(unknown),
            "ambiguous": sorted(ambiguous), "unknownServerIds": unknown_pks}


def apply_statuses(items) -> dict:
    """Статусы из 1С. Покупатель видит их в приложении и получает уведомление.

    Заказ ищем по `serverId` (однозначно), а если его нет — по `orderId` (старый
    контракт). Неоднозначный номер ничего не меняет и возвращается в `ambiguous`.
    """
    updated = 0
    errors = []
    parsed = []  # (label, pk | None, number, raw)
    for raw in items:
        if not isinstance(raw, dict):
            errors.append("элемент не объект")
            continue
        oid = str(raw.get("orderId") or "").strip()
        sid_raw = raw.get("serverId")
        has_sid = sid_raw not in (None, "")
        status = str(raw.get("status") or "").strip().lower()
        label = oid or (f"serverId {sid_raw}" if has_sid else "")
        if not oid and not has_sid:
            errors.append("нет orderId")
            continue
        pk = None
        if has_sid:
            pk = _parse_server_id(sid_raw)
            if pk is None:
                errors.append(f"{label}: неверный serverId «{sid_raw}»")
                continue
        if status not in STATUS_MAP:
            errors.append(f"{label}: неизвестный статус «{status}»")
            continue
        parsed.append((label, pk, oid, raw))

    by_pk = {o.pk: o for o in Order.objects.filter(
        pk__in=[pk for _, pk, _, _ in parsed if pk])}
    found, unknown, ambiguous = _resolve_numbers(
        [oid for _, pk, oid, _ in parsed if pk is None])
    unknown, ambiguous = set(unknown), set(ambiguous)

    wanted = {}  # pk → (order, raw); последний статус по заказу побеждает
    for label, pk, oid, raw in parsed:
        if pk is not None:
            order = by_pk.get(pk)
            if order is None:
                errors.append(f"{label}: заказ не найден (serverId {pk})")
                continue
            if oid and order.order_id != oid:
                errors.append(f"{label}: serverId {pk} — это заказ {order.order_id}, "
                              f"а не {oid}; статус не применён")
                continue
        else:
            if oid in ambiguous:
                errors.append(_ambiguous_error(oid))
                continue
            order = found.get(oid)
            if order is None or oid in unknown:
                errors.append(f"{oid}: заказ не найден")
                continue
        wanted[order.pk] = (order, raw)

    changed = []
    notify = []
    for order, raw in wanted.values():
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

    return {"received": len(items), "updated": updated, "errors": errors[:20],
            "ambiguous": sorted(ambiguous)}
