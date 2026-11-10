"""При создании заказа и смене его статуса — создаём уведомление пользователю.
Срабатывает и для правок статуса из админки, и из API (общий сигнал на модель)."""
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from notifications.models import create_notification

from .models import Order

_STATUS_LABEL = {
    "pending": "принят",
    "paid": "оплачен",
    "processing": "собирается",
    "shipped": "отправлен",
    "delivered": "доставлен",
    "cancelled": "отменён",
}

# О чём дублируем письмом (D-111): то, что покупатель ждёт и хранит. «Принят» —
# нет: заказ ещё ждёт оплату и может истечь сам.
_EMAIL_STATUSES = {"paid", "shipped", "delivered", "cancelled"}


@receiver(pre_save, sender=Order)
def _capture_old_status(sender, instance, **kwargs):
    if instance.pk:
        prev = Order.objects.filter(pk=instance.pk).only("status").first()
        instance._old_status = prev.status if prev else None
    else:
        instance._old_status = None


@receiver(post_save, sender=Order)
def _notify_order(sender, instance, created, **kwargs):
    if created:
        create_notification(
            instance.user_id,
            "Заказ оформлен",
            f"Заказ №{instance.order_id} принят в обработку",
            "order",
            instance.order_id,
        )
        return
    old = getattr(instance, "_old_status", None)
    if old and old != instance.status:
        label = _STATUS_LABEL.get(instance.status, instance.status)
        # «Курьер и время» важнее сухого статуса: человек ждёт не слово
        # «отправлен», а кто и когда привезёт.
        note = (instance.courier_note or "").strip()
        if instance.status == "shipped" and note:
            title, body = "Заказ в пути", f"Заказ №{instance.order_id}: {note}"
        else:
            title = f"Заказ {label}"
            body = f"Заказ №{instance.order_id}: статус изменён на «{label}»"
        email_to = ""
        if instance.status in _EMAIL_STATUSES:
            from notifications.email import recipient_for

            email_to = recipient_for(instance.user_id, instance)
        create_notification(instance.user_id, title, body, "order", instance.order_id,
                            email_to=email_to)
