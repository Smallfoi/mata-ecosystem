"""Отмена заказа покупателем — пока заказ не передан курьеру (D-122).

Решение владельца 10.11.2026: «до этапа передачи заказа курьеру можно отменить».
Отмена — не возврат: товар покупателю не приезжал, осматривать нечего, поэтому
деньги возвращаются сразу и целиком (существующим возвратом по чеку, D-73:
вместе с доставкой, баллы назад).

Два случая:
- 1С заказ ещё не забрала — отменяем сразу. Пока идёт возврат, заказ помечен
  `cancel_requested_at` и в очередь 1С не попадает (integrations/onec_orders.py).
- 1С уже забрала (склад мог начать сборку) — это запрос: склад подтверждает в
  админке, что заказ не передан курьеру, и тогда деньги уходят. Иначе — отказ с
  пояснением: заказ уже в пути, после получения его можно вернуть.
"""
from django.db import transaction
from django.utils import timezone

from .models import Order
from .returns import ReturnError, make_return, return_plan

# Заказ уже у курьера или у покупателя — отменять поздно, только возврат.
TOO_LATE_ONEC = ("shipped", "delivered", "canceled", "cancelled")
TOO_LATE_STATUS = ("shipped", "delivered", "cancelled")


class CancelError(Exception):
    def __init__(self, detail, status=400):
        super().__init__(detail)
        self.detail = detail
        self.status = status


def _blocker(order) -> str:
    """Почему отменить нельзя; пустая строка — можно."""
    if order.payment_status != "paid" or not order.payment_id:
        return "Отменить можно оплаченный заказ"
    if order.onec_status in TOO_LATE_ONEC or order.status in TOO_LATE_STATUS:
        return ("Заказ уже передан курьеру — отменить его нельзя. После получения его "
                "можно вернуть.")
    if order.returns.exists():
        return "По заказу уже оформлен возврат"
    return ""


def cancel_state(order) -> dict:
    """Для экрана заказа: можно ли отменить и почему нет."""
    requested = order.cancel_requested_at is not None
    blocker = "" if requested else _blocker(order)
    return {
        "canCancel": not requested and not blocker,
        "cancelRequested": requested,
        "cancelNote": ("Запрос на отмену принят — склад проверяет, что заказ ещё не "
                       "передан курьеру" if requested else blocker),
    }


def _goods(order) -> list:
    try:
        return [row["index"] for row in return_plan(order)
                if row["subject"] == "commodity" and not row["returned"]]
    except ReturnError as e:
        raise CancelError(str(e)) from e


def _refund_all(order, by):
    """Вернуть всё: деньги, доставку, баллы. Ошибка — снимаем пометку отмены."""
    try:
        return make_return(order.pk, _goods(order), by=by)
    except (ReturnError, CancelError) as e:
        Order.objects.filter(pk=order.pk).update(cancel_requested_at=None)
        raise CancelError(f"Отменить не удалось: {e}") from e


def cancel_order(order, user_id):
    """Покупатель отменяет заказ. Возвращает {"status": canceled|requested}."""
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order.pk)
        if order.cancel_requested_at is not None:
            raise CancelError("Запрос на отмену уже принят", 409)
        blocker = _blocker(order)
        if blocker:
            raise CancelError(blocker, 409)
        order.cancel_requested_at = timezone.now()
        order.save(update_fields=["cancel_requested_at"])
        taken = order.onec_taken_at is not None

    if not taken:
        ret = _refund_all(order, by=f"покупатель {user_id}")
        _notify(order, "Заказ отменён",
                f"Заказ {order.order_id} отменён. Вернём {ret.amount_kop / 100:.2f} ₽ тем же "
                "способом, которым платили, — обычно за 1–3 дня, по закону до 10 дней.")
        return {"status": "canceled"}

    _notify(order, "Запрос на отмену принят",
            f"Заказ {order.order_id}: склад проверит, что заказ ещё не передан курьеру, и "
            "отменит его. Деньги вернутся сразу после подтверждения.")
    _alert_staff(order)
    return {"status": "requested"}


def confirm_cancel(order, by=""):
    """Склад подтвердил: заказ не у курьера — отменяем и возвращаем деньги."""
    order = Order.objects.get(pk=order.pk)
    if order.cancel_requested_at is None:
        raise CancelError("Покупатель не просил отменить этот заказ")
    if order.onec_status in TOO_LATE_ONEC[:2] or order.status in TOO_LATE_STATUS[:2]:
        raise CancelError("Заказ уже отгружен — отменить нельзя, отклоните запрос")
    ret = _refund_all(order, by=by)
    _notify(order, "Заказ отменён",
            f"Заказ {order.order_id} отменён. Вернём {ret.amount_kop / 100:.2f} ₽ тем же "
            "способом, которым платили, — обычно за 1–3 дня, по закону до 10 дней.")
    return ret


def decline_cancel(order, by=""):
    """Склад: заказ уже передан курьеру — отменить нельзя."""
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order.pk)
        if order.cancel_requested_at is None:
            raise CancelError("Покупатель не просил отменить этот заказ")
        order.cancel_requested_at = None
        order.save(update_fields=["cancel_requested_at"])
    _notify(order, "Заказ отменить не удалось",
            f"Заказ {order.order_id} уже передан курьеру. После получения его можно "
            "вернуть: «Профиль» → заказ → «Оформить возврат».")
    return order


def _notify(order, title, body):
    try:
        from notifications.email import recipient_for
        from notifications.models import create_notification

        create_notification(order.user_id, title, body, "order", order.order_id,
                            email_to=recipient_for(order.user_id, order))
    except Exception:
        pass


def _alert_staff(order):
    try:
        from notifications.email import send_email

        from .return_requests import staff_recipients

        text = (f"Покупатель просит отменить заказ {order.order_id}. Заказ уже в 1С"
                f"{' (№ ' + order.onec_number + ')' if order.onec_number else ''}.\n\n"
                "Если заказ ещё не передан курьеру — остановите сборку и подтвердите отмену "
                "в админке (Заказы → заказ → «Подтвердить отмену»): деньги уйдут покупателю "
                "сразу. Если уже передан — отклоните запрос.")
        for to in staff_recipients():
            send_email(to, f"Отмена заказа {order.order_id}", text)
    except Exception:
        pass
