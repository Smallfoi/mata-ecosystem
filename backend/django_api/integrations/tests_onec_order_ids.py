"""Номера заказов для 1С однозначны (аудит B06).

Номер заказа (`SS-xxxxx`) придумывает приложение, и уникален он только вместе с
пользователем: у двух покупателей может оказаться один и тот же номер. Раньше
`ack` и статусы из 1С искали заказ по одному номеру — подтверждение одного
заказа снимало с очереди чужой, а статус «отгружен» уходил не тому покупателю.

Теперь у каждого заказа есть серверный `serverId`, он приходит в выдаче, и 1С
подтверждает/двигает заказ по нему. Старый путь «по номеру» сохранён: пока номер
однозначен, всё работает как раньше; неоднозначный номер ничего не трогает, а
возвращается в ответе и пишется в журнал обмена.
"""
from django.test import TestCase, override_settings

from catalog.models import Product
from integrations.models import OneCExchange
from notifications.models import Notification
from orders.models import Order

TOKEN = "test-1c-token"
PULL = "/v1/integrations/1c/orders"
ACK = "/v1/integrations/1c/orders/ack"
STATUS = "/v1/integrations/1c/orders/status"


@override_settings(INTEGRATION_1C_TOKEN=TOKEN)
class OneCOrderIdentityTests(TestCase):
    def setUp(self):
        Product.objects.create(id="p1", name="Кроссовки", category_id="shoes",
                               price=11990, article="AR-X1", external_id="GUID-1")
        # Два покупателя, один и тот же клиентский номер.
        self.a = self._order("SS-1", user="u_a")
        self.b = self._order("SS-1", user="u_b")
        Notification.objects.all().delete()

    def _order(self, oid, *, user, paid=True):
        return Order.objects.create(
            user_id=user, order_id=oid, total=11990,
            status="paid" if paid else "pending",
            payment_status="paid" if paid else "pending",
            payment_id=f"yk-{user}-{oid}" if paid else "",
            payload={"id": oid, "items": [{"productId": "p1", "productName": "Кроссовки",
                                           "quantity": 1, "price": 11990}],
                     "checkoutData": {"phone": "+79148278470"}},
        )

    def _post(self, url, payload):
        return self.client.post(url, payload, content_type="application/json",
                                HTTP_AUTHORIZATION=f"Bearer {TOKEN}")

    def _refresh(self):
        self.a.refresh_from_db()
        self.b.refresh_from_db()

    # ── выдача ──────────────────────────────────────────────────────────────

    def test_pull_gives_global_server_id(self):
        orders = self.client.get(PULL, HTTP_AUTHORIZATION=f"Bearer {TOKEN}").json()["orders"]
        ids = sorted(o["serverId"] for o in orders)
        self.assertEqual(ids, sorted([self.a.pk, self.b.pk]))
        # Короткий номер остаётся — для отображения и старой 1С.
        self.assertEqual({o["orderId"] for o in orders}, {"SS-1"})

    # ── ack ─────────────────────────────────────────────────────────────────

    def test_ack_by_server_id_takes_only_that_order(self):
        body = self._post(ACK, {"serverIds": [self.a.pk]}).json()
        self.assertEqual(body["acked"], 1)
        self._refresh()
        self.assertIsNotNone(self.a.onec_taken_at)
        self.assertIsNone(self.b.onec_taken_at)
        # Второй заказ с тем же номером остаётся в очереди.
        queue = self.client.get(PULL, HTTP_AUTHORIZATION=f"Bearer {TOKEN}").json()["orders"]
        self.assertEqual([o["serverId"] for o in queue], [self.b.pk])

    def test_ack_by_server_id_as_string_works(self):
        body = self._post(ACK, {"serverIds": [str(self.b.pk)]}).json()
        self.assertEqual(body["acked"], 1)
        self._refresh()
        self.assertIsNone(self.a.onec_taken_at)
        self.assertIsNotNone(self.b.onec_taken_at)

    def test_ack_unknown_server_id_reported(self):
        body = self._post(ACK, {"serverIds": [999999, "abc"]}).json()
        self.assertEqual(body["acked"], 0)
        self.assertEqual(body["unknownServerIds"], ["999999", "abc"])

    def test_ambiguous_number_in_ack_touches_nothing(self):
        r = self._post(ACK, {"orderIds": ["SS-1"]})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["acked"], 0)
        self.assertEqual(body["ambiguous"], ["SS-1"])
        self.assertEqual(body["unknown"], [])
        self._refresh()
        self.assertIsNone(self.a.onec_taken_at)
        self.assertIsNone(self.b.onec_taken_at)
        entry = OneCExchange.objects.filter(operation="orders").latest("id")
        self.assertEqual(entry.status, "partial")
        self.assertTrue(any("SS-1" in e and "serverId" in e for e in entry.errors))

    def test_number_is_unambiguous_when_only_one_order_was_given_to_1c(self):
        """Чужой неоплаченный заказ с тем же номером 1С никогда не видела —
        старый ack по номеру должен подтвердить именно оплаченный и не тронуть чужой."""
        other = self._order("SS-2", user="u_a", paid=False)
        mine = self._order("SS-2", user="u_b")
        body = self._post(ACK, {"orderIds": ["SS-2"]}).json()
        self.assertEqual(body["acked"], 1)
        self.assertEqual(body["ambiguous"], [])
        other.refresh_from_db()
        mine.refresh_from_db()
        self.assertIsNotNone(mine.onec_taken_at)
        self.assertIsNone(other.onec_taken_at)

    def test_old_ack_by_unique_number_still_works(self):
        solo = self._order("SS-9", user="u_a")
        body = self._post(ACK, {"orderIds": ["SS-9"]}).json()
        self.assertEqual(body, {"acked": 1, "unknown": [], "ambiguous": [],
                                "unknownServerIds": []})
        solo.refresh_from_db()
        self.assertIsNotNone(solo.onec_taken_at)

    # ── статусы ─────────────────────────────────────────────────────────────

    def test_status_by_server_id_moves_only_that_order(self):
        body = self._post(STATUS, {"orders": [
            {"serverId": self.a.pk, "orderId": "SS-1", "status": "shipped", "number": "Д-1"},
            {"serverId": self.b.pk, "status": "delivered"},
        ]}).json()
        self.assertEqual(body["updated"], 2)
        self.assertEqual(body["errors"], [])
        self._refresh()
        self.assertEqual((self.a.status, self.a.onec_status, self.a.onec_number),
                         ("shipped", "shipped", "Д-1"))
        self.assertEqual((self.b.status, self.b.onec_status, self.b.onec_number),
                         ("delivered", "delivered", ""))
        # Уведомление ушло каждому своё.
        self.assertEqual(Notification.objects.filter(user_id="u_a").count(), 1)
        self.assertEqual(Notification.objects.filter(user_id="u_b").count(), 1)

    def test_ambiguous_number_in_status_touches_nothing(self):
        body = self._post(STATUS, {"orders": [{"orderId": "SS-1", "status": "shipped"}]}).json()
        self.assertEqual(body["updated"], 0)
        self.assertEqual(body["ambiguous"], ["SS-1"])
        self.assertTrue(any("SS-1" in e and "serverId" in e for e in body["errors"]))
        self._refresh()
        self.assertEqual((self.a.status, self.b.status), ("paid", "paid"))
        self.assertEqual((self.a.onec_status, self.b.onec_status), ("", ""))
        self.assertEqual(Notification.objects.count(), 0)
        entry = OneCExchange.objects.filter(operation="order-status").latest("id")
        self.assertEqual(entry.status, "partial")

    def test_status_server_id_and_number_must_agree(self):
        other = self._order("SS-7", user="u_a")
        body = self._post(STATUS, {"orders": [
            {"serverId": other.pk, "orderId": "SS-1", "status": "shipped"},
        ]}).json()
        self.assertEqual(body["updated"], 0)
        self.assertEqual(len(body["errors"]), 1)
        other.refresh_from_db()
        self.assertEqual(other.onec_status, "")

    def test_status_unknown_server_id_reported(self):
        body = self._post(STATUS, {"orders": [{"serverId": 999999, "status": "shipped"}]}).json()
        self.assertEqual(body["updated"], 0)
        self.assertEqual(len(body["errors"]), 1)
        self.assertIn("999999", body["errors"][0])

    def test_old_status_by_unique_number_still_works(self):
        solo = self._order("SS-9", user="u_a")
        body = self._post(STATUS, {"orders": [{"orderId": "SS-9", "status": "shipped"}]}).json()
        self.assertEqual(body["updated"], 1)
        solo.refresh_from_db()
        self.assertEqual(solo.status, "shipped")
