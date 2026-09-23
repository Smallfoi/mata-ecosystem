"""Доставка по городу своими силами (D-92): «Передан курьеру».

Курьера заказывают вручную — Яндекс, inDrive или свой. Магазину нужно одно:
записать, кто везёт и когда, и чтобы покупатель это УЗНАЛ.

Отдельно закрываем найденную дыру: действия смены статуса в админке меняли
статус через `queryset.update()`, а это идёт мимо сигналов — уведомление
покупателю не уходило. В базе «Отправлен», человек не в курсе.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase

from common.testutils import login_admin
from notifications.models import Notification
from orders.models import Order
from staff.models import StaffAudit

LIST = "/admin/orders/order/"


class HandToCourierTests(TestCase):
    def setUp(self):
        get_user_model().objects.create_superuser("owner_cur", "c@t.dev", "OwnerPass!2026")
        login_admin(self.client, "owner_cur", "OwnerPass!2026")
        self.order = Order.objects.create(
            user_id="u_cur", order_id="SS-CUR", total=5000, status="paid",
            payment_status="paid", payload={"id": "SS-CUR", "items": []},
        )
        Notification.objects.all().delete()   # уведомление о создании заказа не мешает

    def _action(self, data):
        return self.client.post(LIST, {
            "action": "hand_to_courier", "index": "0", "select_across": "0",
            "_selected_action": [str(self.order.pk)], **data,
        })

    def test_form_asks_what_to_tell_the_buyer(self):
        r = self._action({})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Что увидит покупатель")

    def test_hands_over_and_notifies(self):
        note = "Курьер Яндекса, привезёт сегодня до 18:00"
        self._action({"apply": "1", "note": note})

        order = Order.objects.get(pk=self.order.pk)
        self.assertEqual(order.status, "shipped")
        self.assertEqual(order.courier_note, note)

        n = Notification.objects.get(user_id="u_cur")
        self.assertEqual(n.title, "Заказ в пути")
        self.assertIn(note, n.body)
        self.assertIn("SS-CUR", n.body)

    def test_empty_note_is_refused(self):
        self._action({"apply": "1", "note": "   "})
        self.assertEqual(Order.objects.get(pk=self.order.pk).status, "paid")
        self.assertFalse(Notification.objects.filter(user_id="u_cur").exists())

    def test_written_to_audit(self):
        self._action({"apply": "1", "note": "Свой курьер, через час"})
        self.assertTrue(StaffAudit.objects.filter(action__contains="передано курьеру").exists())

    def test_plain_status_action_also_notifies(self):
        """Дыра, из-за которой покупатель не узнавал об отправке."""
        self.client.post(LIST, {
            "action": "mark_delivered", "index": "0", "select_across": "0",
            "_selected_action": [str(self.order.pk)],
        })
        self.assertEqual(Order.objects.get(pk=self.order.pk).status, "delivered")
        n = Notification.objects.get(user_id="u_cur")
        self.assertEqual(n.title, "Заказ доставлен")

    def test_status_action_is_idempotent(self):
        """Повторное нажатие не шлёт второе уведомление — статус уже тот же."""
        self.client.post(LIST, {"action": "mark_paid", "index": "0", "select_across": "0",
                                "_selected_action": [str(self.order.pk)]})
        self.assertEqual(Notification.objects.filter(user_id="u_cur").count(), 0)
