"""Возврат заказа — целиком или частями (D-73).

Правила (решение владельца 10.09.2026):
- деньги возвращаются по суммам из чека: скидка баллами разложена по позициям
  пропорционально (`receipt.allocate`), и чек возврата обязан с этим совпадать;
- потраченные на заказ баллы возвращаются, начисленные за него — снимаются, в той
  же доле, что и возвращённые вещи;
- доставка возвращается вместе с последней вещью заказа («Возврат и обмен», п. 4.3:
  первичная доставка из возврата не удерживается). Пока хоть одна вещь у покупателя,
  доставка ему пригодилась;
- если начисленные баллы уже потрачены, баланс уходит в минус — как и до частичных
  возвратов. Решение про минус владелец отложил (D-73, на паузе); деньгами из
  возврата не удерживаем.

Сумма всех возвратов по заказу ровно равна оплате, а баллы — ровно списанным и
начисленным: последний возврат забирает остаток, а не свою долю с округлением.
"""
from django.db import transaction

from .awards import (
    earned_for,
    redeemed_for,
    return_redeemed_points,
    revoke_earned_points,
)
from .models import Order, OrderReturn
from .payment import PaymentError, create_refund
from .receipt import allocate, refund_receipt

# Статусы оплаты, при которых ещё есть что возвращать.
RETURNABLE = ("paid", "partially_refunded")


class ReturnError(Exception):
    """Возврат оформить нельзя — текст для сотрудника."""


def _rows(order):
    try:
        return allocate(order.payload, order.total)
    except ValueError as e:
        raise ReturnError(f"Не удалось разложить заказ по позициям: {e}") from e


def _taken(order):
    """Позиции, которые уже вернули или возвращают прямо сейчас."""
    out = set()
    for ret in order.returns.filter(status__in=("pending", "done")):
        out.update(int(i) for i in ret.lines)
    return out


def return_plan(order):
    """Позиции заказа с суммами из чека и отметкой, что уже вернули."""
    taken = _taken(order)
    rows = _rows(order)
    for row in rows:
        row["returned"] = row["index"] in taken
    return rows


def _compute(order, indexes):
    """Сколько денег и баллов уйдёт покупателю при возврате этих позиций."""
    if order.payment_status not in RETURNABLE or not order.payment_id:
        raise ReturnError("Вернуть можно только заказ, оплата которого прошла через ЮKassa")
    if order.returns.filter(status="pending").exists():
        # Иначе два одновременных возврата посчитали бы «остаток» каждый по-своему
        # и вернули бы деньги дважды.
        raise ReturnError("По заказу уже идёт возврат — дождитесь результата")

    rows = _rows(order)
    goods = {row["index"] for row in rows if row["subject"] == "commodity"}
    taken = _taken(order)
    chosen = {int(i) for i in indexes}
    if not chosen:
        raise ReturnError("Отметьте, что возвращаем")
    if not chosen <= goods:
        raise ReturnError("В заказе нет такой позиции (доставка отдельно не возвращается)")
    if chosen & taken:
        raise ReturnError("Часть отмеченных вещей уже вернули")

    done = list(order.returns.filter(status="done"))
    total_kop = sum(row["paid"] for row in rows)
    completes = (taken | chosen) >= goods
    redeemed, earned = redeemed_for(order), earned_for(order)

    if completes:
        # Последние вещи: возвращаем остаток целиком — вместе с доставкой.
        lines = sorted(chosen | {row["index"] for row in rows if row["index"] not in goods})
        amount_kop = total_kop - sum(r.amount_kop for r in done)
        points_back = max(0, redeemed - sum(r.points_returned for r in done))
        points_off = max(0, earned - sum(r.points_revoked for r in done))
    else:
        lines = sorted(chosen)
        amount_kop = sum(row["paid"] for row in rows if row["index"] in chosen)
        gross_all = sum(row["gross"] for row in rows)
        gross_chosen = sum(row["gross"] for row in rows if row["index"] in chosen)
        # Скидка баллами разложена по всем позициям пропорционально цене — баллы
        # возвращаем в той же доле. Начисленные — в доле возвращённых денег.
        points_back = redeemed * gross_chosen // gross_all if gross_all else 0
        points_off = earned * amount_kop // total_kop if total_kop else 0

    return {
        "lines": lines,
        "amount_kop": amount_kop,
        "points_back": points_back,
        "points_off": points_off,
        "completes": completes,
    }


def preview(order, indexes):
    """Расчёт возврата без действий — чтобы сотрудник увидел суммы до нажатия."""
    return _compute(order, indexes)


def make_return(order_pk, indexes, by=""):
    """Провести возврат: сначала деньги через ЮKassa, потом баллы. Возвращает OrderReturn."""
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order_pk)
        plan = _compute(order, indexes)
        ret = OrderReturn.objects.create(
            order=order, lines=plan["lines"], amount_kop=plan["amount_kop"],
            status="pending", created_by=by[:150],
        )

    # Запрос в ЮKassa — вне транзакции: сеть не должна держать блокировку заказа.
    try:
        receipt = refund_receipt(order.payload, order.total, plan["lines"])
        refund = create_refund(
            order.payment_id,
            plan["amount_kop"] / 100,
            f"Возврат по заказу {order.order_id}",
            # Свой ключ у каждого возврата: ключ «платёж + сумма» склеил бы два
            # частичных возврата на равную сумму в один.
            key=f"order-return-{ret.pk}",
            receipt=receipt,
        )
        if refund.get("status") == "canceled":
            raise PaymentError("ЮKassa отклонила возврат")
    except (PaymentError, ValueError) as e:
        ret.status, ret.error = "failed", str(e)[:300]
        ret.save(update_fields=["status", "error"])
        raise ReturnError(f"Возврат не прошёл: {e}") from e

    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order.pk)
        ret.refund_id = refund.get("refundId") or ""
        ret.status = "done"
        ret.points_returned = return_redeemed_points(
            order, plan["points_back"], f"Возврат баллов: возврат товара по заказу №{order.order_id}"
        )
        ret.points_revoked = revoke_earned_points(
            order, plan["points_off"], f"Отмена начисления: возврат товара по заказу №{order.order_id}"
        )
        ret.save(update_fields=["refund_id", "status", "points_returned", "points_revoked"])
        if plan["completes"]:
            order.payment_status = "refunded"
            order.status = "cancelled"
            order.save(update_fields=["payment_status", "status"])
        else:
            order.payment_status = "partially_refunded"
            order.save(update_fields=["payment_status"])

    if not plan["completes"]:
        # Полный возврат покупатель и так увидит: смена статуса заказа шлёт уведомление.
        _notify_partial(order, ret)
    return ret


def _notify_partial(order, ret):
    try:
        from notifications.models import create_notification

        text = f"По заказу №{order.order_id} вернём {ret.amount_kop / 100:.2f} ₽"
        if ret.points_returned:
            text += f", на счёт вернутся {ret.points_returned} баллов"
        create_notification(order.user_id, "Возврат оформлен", text + ".", "order", order.order_id)
    except Exception:
        # Уведомление — не часть возврата: деньги и баллы уже проведены.
        pass
