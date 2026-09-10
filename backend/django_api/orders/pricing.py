"""Серверная проверка суммы заказа (D-37).

Клиент присылает `total` сам, и раньше сервер его принимал на веру: и списывал по нему
деньги через ЮKassa, и начислял по нему баллы. Значит корзину на 50 000 ₽ можно было
оформить с `total: 1` — заплатить рубль и получить товар. Здесь сумма пересчитывается
по ЦЕНАМ КАТАЛОГА и клиентская сравнивается с полученным минимумом.

Почему минимум, а не жёсткое равенство: сверху к товарам добавляется доставка, которую
считает клиент, и правил доставки у бэкенда пока нет. Занизить сумму нельзя, завысить —
проблема покупателя, а не магазина.
"""

# Списанные баллы уменьшают сумму: 1 балл = 1 ₽ (правила лояльности, Часть 11.5).
_POINT_RUB = 1.0
# Допуск на округление копеек при пересчёте на клиенте.
_EPSILON = 1.0


def _redeemed_rub(user_id, order_id) -> float:
    """Сколько баллов РЕАЛЬНО списано за этот заказ — по реестру, а не по словам клиента."""
    from loyalty.models import LoyaltyTransaction

    txn = LoyaltyTransaction.objects.filter(
        user_id=user_id, order_id=order_id, source="redeem"
    ).first()
    return abs(txn.amount) * _POINT_RUB if txn else 0.0


def minimum_total(items, user_id, order_id):
    """Минимально допустимая сумма заказа или None, если сверить не с чем.

    None возвращается, когда ни одну позицию не удалось найти в каталоге (например,
    товар сняли с публикации) — тогда проверять нечего и заказ не блокируем.
    """
    from catalog.models import Product

    goods, matched = 0.0, 0
    for it in items or []:
        pid = str(it.get("productId") or "").strip()
        if not pid:
            continue
        product = Product.objects.filter(pk=pid).only("price").first()
        if not product:
            continue
        qty = max(1, int(it.get("quantity") or 1))
        goods += float(product.price) * qty
        matched += 1
    if not matched:
        return None
    return max(0.0, goods - _redeemed_rub(user_id, order_id))


def all_items_known(items) -> bool:
    """Все позиции заказа есть в каталоге — значит сумму есть с чем сверить.

    Нужна, когда приём оплаты включён (D-72): заказ из позиций не из каталога
    сверить нельзя, и его оплатили бы любой суммой — хоть рублём.
    """
    from catalog.models import Product

    ids = [str(it.get("productId") or "").strip() for it in (items or [])]
    if not ids or not all(ids):
        return False
    return Product.objects.filter(pk__in=set(ids)).count() == len(set(ids))


def total_is_acceptable(total, items, user_id, order_id) -> bool:
    """Не занижена ли присланная клиентом сумма относительно каталога."""
    minimum = minimum_total(items, user_id, order_id)
    if minimum is None:
        return True
    return float(total) >= minimum - _EPSILON
