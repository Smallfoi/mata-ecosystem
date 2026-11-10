"""Помощники тестов заказов.

С D-120 номер заказа выдаёт сервер, а тест знает только черновой номер, с которым
оформлял заказ через API. `by_ref` находит заказ по любому из двух.
"""
from django.db.models import Q


def by_ref(ref):
    return Q(order_id=ref) | Q(client_ref=ref)


def number(ref):
    """Настоящий номер заказа, оформленного в тесте с черновым номером `ref`."""
    from orders.models import Order

    return Order.objects.get(by_ref(ref)).order_id
