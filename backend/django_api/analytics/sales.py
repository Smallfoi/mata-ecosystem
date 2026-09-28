"""Статистика продаж без покупателя (решение владельца 28.09.2026).

При оплате заказа его строки копируются в `SaleLine`: товар, размер, цвет,
количество, цена, дата — и ничего о человеке. Заказ потом может быть удалён
вместе с аккаунтом, статистика остаётся. Возврат помечает строки `refunded`.
"""
import logging

log = logging.getLogger(__name__)

# Оплата прошла (в том числе потом частично/полностью возвращена) — продажа была.
SOLD = ("paid", "partially_refunded", "refunded")


def record(order) -> int:
    """Записать (или обновить отметку возврата) строки оплаченного заказа. Повтор
    безопасен. Сбой статистики не должен ломать оплату — ошибки глотаем в лог."""
    try:
        return _record(order)
    except Exception:  # noqa: BLE001 — статистика не критична
        log.exception("sales: не удалось записать заказ %s", getattr(order, "pk", "?"))
        return 0


def _record(order) -> int:
    from catalog.models import Product

    from .models import SaleLine

    if order.pk is None or order.is_test or order.payment_status not in SOLD:
        return 0
    refunded = order.payment_status == "refunded"
    if SaleLine.objects.filter(order_pk=order.pk).exists():
        SaleLine.objects.filter(order_pk=order.pk).update(refunded=refunded)
        return 0

    items = [i for i in ((order.payload or {}).get("items") or []) if isinstance(i, dict)]
    ids = {str(i.get("productId") or "") for i in items} - {""}
    products = {p.id: p for p in Product.objects.filter(id__in=ids)}
    rows = []
    for n, item in enumerate(items):
        pid = str(item.get("productId") or "")
        p = products.get(pid)
        try:
            qty = max(1, int(item.get("quantity") or 1))
        except (TypeError, ValueError):
            qty = 1
        try:
            price = float(item.get("price") or 0)
        except (TypeError, ValueError):
            price = 0.0
        rows.append(SaleLine(
            order_pk=order.pk, line=n, sold_at=order.created_at,
            product_id=pid[:80],
            article=((p.article if p else "") or "")[:80],
            model_key=((p.shop_model_key if p else "") or "")[:200],
            name=str(item.get("productName") or (p.name if p else ""))[:300],
            brand=str(item.get("productBrand") or (p.brand if p else ""))[:120],
            category_id=((p.category_id if p else "") or "")[:80],
            size=str(item.get("size") or "")[:40],
            color=str(item.get("color") or "")[:80],
            quantity=qty, price=price, refunded=refunded,
        ))
    SaleLine.objects.bulk_create(rows, ignore_conflicts=True)
    return len(rows)


def on_order_saved(sender, instance, **kwargs):
    if instance.payment_status in SOLD:
        record(instance)
