"""Жизненный цикл оплаты заказа: оплачен, отменён, не оплачен вовремя (D-72).

Одни и те же переходы делают три места — вебхук ЮKassa, перепроверка статуса
покупателем и фоновая сверка неоплаченных заказов. Правило держим в одном месте.
"""
from datetime import timedelta

from django.utils import timezone

from .awards import accrue_purchase_points, refund_redeemed_points
from .models import Order

# Сколько ждём оплату. Не заплатил — заказ отменяется, списанные баллы возвращаются.
# 15 минут — решение владельца 10.09.2026 (30 показалось ему слишком долгим).
HOLD_MINUTES = 15

# Сколько заказов разбираем за один проход: сверка ходит в ЮKassa по каждому.
BATCH = 200


def mark_paid(order) -> None:
    """ЮKassa подтвердила оплату: фиксируем и начисляем баллы (идемпотентно)."""
    fields = []
    if order.payment_status != "paid":
        order.payment_status = "paid"
        fields.append("payment_status")
    if order.status == "pending":
        order.status = "paid"
        fields.append("status")
    if fields:
        order.save(update_fields=fields)
    accrue_purchase_points(order)


def mark_canceled(order) -> None:
    """Оплата не состоялась: заказ отменён, списанные баллы вернулись (идемпотентно)."""
    fields = []
    if order.payment_status != "canceled":
        order.payment_status = "canceled"
        fields.append("payment_status")
    if order.status == "pending":
        order.status = "cancelled"
        fields.append("status")
    if fields:
        order.save(update_fields=fields)
    refund_redeemed_points(order)


def expire_unpaid(now=None) -> dict:
    """Разобрать заказы, которые не оплатили за HOLD_MINUTES.

    Платежа в ЮKassa нет — отменяем. Платёж есть — решает не таймер, а ЮKassa:
    покупатель мог заплатить в последнюю секунду, а уведомление ещё в пути.
    Оплачен — проводим, отменён — отменяем, ещё идёт — не трогаем: ЮKassa закроет
    его сама и пришлёт уведомление.
    """
    from .payment import PaymentError, fetch_payment

    deadline = (now or timezone.now()) - timedelta(minutes=HOLD_MINUTES)
    stats = {"canceled": 0, "paid": 0, "waiting": 0, "errors": 0}
    rows = Order.objects.filter(
        payment_status="pending", created_at__lt=deadline
    ).order_by("created_at")[:BATCH]
    for order in rows:
        if not order.payment_id:
            mark_canceled(order)
            stats["canceled"] += 1
            continue
        try:
            info = fetch_payment(order.payment_id)
        except PaymentError:
            stats["errors"] += 1
            continue
        if info["status"] == "paid":
            mark_paid(order)
            stats["paid"] += 1
        elif info["status"] == "canceled":
            mark_canceled(order)
            stats["canceled"] += 1
        else:
            stats["waiting"] += 1
    return stats
