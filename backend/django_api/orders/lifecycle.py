"""Жизненный цикл оплаты заказа: оплачен, отменён, не оплачен вовремя (D-72).

Одни и те же переходы делают три места — вебхук ЮKassa, перепроверка статуса
покупателем и фоновая сверка неоплаченных заказов. Правило держим в одном месте.
"""
import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .awards import accrue_purchase_points, refund_redeemed_points
from .models import Order
from .payment_receipt import WAITING, expects_receipt

log = logging.getLogger(__name__)

# Сколько ждём оплату. Не заплатил — заказ отменяется, списанные баллы возвращаются.
# 15 минут — решение владельца 10.09.2026 (30 показалось ему слишком долгим).
HOLD_MINUTES = 15

# Сколько заказов разбираем за один проход: сверка ходит в ЮKassa по каждому.
BATCH = 200

# Статусы оплаты, из которых заказ ещё может стать оплаченным или отменённым.
# «none» — заказы до D-72 (оплата не требовалась).
AWAITING = ("pending", "none")


def payment_started(order) -> bool:
    """Оплата заказа уже начата: платёж создан или исход оплаты известен.

    С этого момента состав и сумма заказа заморожены (аудит B01): провайдер
    списывает именно ту сумму, которую мы ему назвали, и чек построен по тому
    составу, что был в заказе.
    """
    return bool(order.payment_id) or order.payment_status not in AWAITING


def _sync(order, locked) -> None:
    """Вернуть вызывающему актуальные поля: переходы делаются на заблокированной копии."""
    order.payment_status = locked.payment_status
    order.status = locked.status


def mark_paid(order) -> None:
    """ЮKassa подтвердила оплату: фиксируем и начисляем баллы (идемпотентно).

    Допустимый переход один — «ждёт оплату» → «оплачен» (аудит B05). Повтор того же
    подтверждения (ЮKassa повторяет уведомления, покупатель жмёт «проверить», фоновая
    сверка) ничего не меняет. После возврата (частичного или полного) и после
    отмены «оплачено» не ставится: иначе возврат «забывается» — вещи можно вернуть
    ещё раз, а заказ снова уходит в 1С на сборку.
    """
    with transaction.atomic():
        locked = Order.objects.select_for_update().get(pk=order.pk)
        state = locked.payment_status
        if state in AWAITING:
            locked.payment_status = "paid"
            locked.paid_at = timezone.now()
            fields = ["payment_status", "paid_at"]
            if locked.status == "pending":
                locked.status = "paid"
                fields.append("status")
            if expects_receipt(locked):
                # Касса пробивает чек не мгновенно: ждём его номер для 1С
                # (`orders/payment_receipt.py`, опрос раз в минуту).
                locked.receipt = {"status": WAITING}
                fields.append("receipt")
            locked.save(update_fields=fields)
        elif state != "paid":
            if state == "canceled":
                # Деньги пришли по уже отменённому заказу (например, отменил
                # сотрудник). В сборку его не возвращаем — деньги вернуть вручную.
                log.error("Оплата пришла по отменённому заказу %s (платёж %s) — "
                          "нужен возврат вручную", locked.order_id, locked.payment_id)
            _sync(order, locked)
            return
        # «paid» — в том числе повтор: начисление идемпотентно и добьёт баллы,
        # если в прошлый раз оно упало.
        accrue_purchase_points(locked)
    _sync(order, locked)


def mark_canceled(order) -> None:
    """Оплата не состоялась: заказ отменён, списанные баллы вернулись (идемпотентно).

    Отменить можно только неоплаченный заказ (аудит B05): запоздалое «платёж
    отменён» не отменяет оплаченный или возвращённый заказ.
    """
    with transaction.atomic():
        locked = Order.objects.select_for_update().get(pk=order.pk)
        state = locked.payment_status
        if state in AWAITING:
            locked.payment_status = "canceled"
            fields = ["payment_status"]
            if locked.status == "pending":
                locked.status = "cancelled"
                fields.append("status")
            locked.save(update_fields=fields)
        elif state != "canceled":
            log.warning("Отмена платежа по заказу %s в состоянии «%s» — пропущена",
                        locked.order_id, state)
            _sync(order, locked)
            return
        refund_redeemed_points(locked)
    _sync(order, locked)


def apply_payment_info(order, info) -> str:
    """Применить к заказу статус платежа ПО ДАННЫМ провайдера.

    Единая точка для вебхука, перепроверки покупателем, фоновой сверки и ответа
    на создание платежа. «Оплачено» — только если платёж совпал с заказом
    (сумма, валюта, reference, аудит B01). Возвращает текст расхождения или "".
    """
    from .payment import payment_mismatch

    if info.get("status") == "paid":
        problem = payment_mismatch(order, info)
        if problem:
            log.error("Платёж не засчитан заказу %s: %s", order.order_id, problem)
            return problem
        mark_paid(order)
    elif info.get("status") == "canceled":
        mark_canceled(order)
    return ""


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
        if order.is_test:
            # Тестовый заказ (D-97): в ЮKassa такого платежа нет, спрашивать её
            # про номер «TEST-…» бессмысленно. Не оплатили вовремя — отменяем.
            mark_canceled(order)
            stats["canceled"] += 1
            continue
        if not order.payment_id:
            mark_canceled(order)
            stats["canceled"] += 1
            continue
        try:
            info = fetch_payment(order.payment_id)
        except PaymentError:
            stats["errors"] += 1
            continue
        if apply_payment_info(order, info):
            stats["errors"] += 1
        elif info["status"] == "paid":
            stats["paid"] += 1
        elif info["status"] == "canceled":
            stats["canceled"] += 1
        else:
            stats["waiting"] += 1
    return stats
