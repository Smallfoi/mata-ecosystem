"""Письма покупателю о заказе (D-111): канал рядом с лентой и пушем."""
import os
from unittest import mock

from django.core import mail
from django.test import TestCase

from notifications.email import real_address, recipient_for
from notifications.models import Notification
from orders.models import Order

_ON = {"EMAIL_PROVIDER": "smtp"}


def _inline(to, subject, text):
    from notifications.email import send_email

    return send_email(to, subject, text)


@mock.patch("notifications.tasks.send_email_task.delay", side_effect=_inline)
class EmailChannelTests(TestCase):
    """Очередь Celery подменена прямым вызовом: письмо проверяем, а не брокер."""

    def _order(self, email="buyer@example.ru", user_id="u_mail"):
        return Order.objects.create(
            user_id=user_id, order_id="SS-M1", total=1000,
            payload={"checkoutData": {"email": email}},
        )

    def test_fake_addresses_are_skipped(self, _delay):
        self.assertEqual(real_address("runner_79990000000@kvartal.local"), "")
        self.assertEqual(real_address("not-an-email"), "")
        self.assertEqual(real_address(" buyer@example.ru "), "buyer@example.ru")

    def test_recipient_prefers_checkout_email(self, _delay):
        self.assertEqual(recipient_for("u_mail", self._order()), "buyer@example.ru")

    @mock.patch.dict(os.environ, _ON)
    def test_paid_order_is_emailed(self, _delay):
        order = self._order()
        order.status = "paid"
        order.save()
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["buyer@example.ru"])
        self.assertEqual(mail.outbox[0].subject, "Заказ оплачен")
        # Лента тоже получила уведомление — и с русским статусом, а не «paid».
        self.assertTrue(Notification.objects.filter(title="Заказ оплачен").exists())

    @mock.patch.dict(os.environ, _ON)
    def test_new_unpaid_order_is_not_emailed(self, _delay):
        self._order()
        self.assertEqual(len(mail.outbox), 0)

    @mock.patch.dict(os.environ, _ON)
    def test_synthetic_account_email_gets_nothing(self, _delay):
        order = self._order(email="runner_7999@kvartal.local")
        order.status = "shipped"
        order.save()
        self.assertEqual(len(mail.outbox), 0)
        self.assertTrue(Notification.objects.filter(order_id="SS-M1").exists())

    @mock.patch.dict(os.environ, {"EMAIL_PROVIDER": ""})
    def test_disabled_provider_sends_nothing(self, _delay):
        order = self._order()
        order.status = "paid"
        order.save()
        self.assertEqual(len(mail.outbox), 0)
