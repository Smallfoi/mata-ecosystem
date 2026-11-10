"""Один номер заказа для 1С — и он уникален (D-120).

До D-120 номер (`SS-xxxxx`) придумывало приложение, и у двух покупателей он мог
совпасть; поэтому в выдаче был второй, серверный номер `serverId` (аудит B06).
Теперь номер выдаёт сервер: `МАТА-` + 8 случайных цифр, уникален во всей базе.
В 1С уходит только `orderId`; по нему 1С подтверждает приём и шлёт статусы.
`serverId` из выдачи убран, но в ack/статусах пока принимается — чтобы обмен,
уже написанный под него, не сломался в день перехода.
"""
from unittest import mock

from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings

from catalog.models import Product
from common.testutils import ApiTestCase
from notifications.models import Notification
from orders.models import Order
from orders.numbers import new_order_number

TOKEN = "test-1c-token"
PULL = "/v1/integrations/1c/orders"
ACK = "/v1/integrations/1c/orders/ack"
STATUS = "/v1/integrations/1c/orders/status"


def _paid(number, *, user, client_ref=""):
    return Order.objects.create(
        user_id=user, order_id=number, client_ref=client_ref, total=11990,
        status="paid", payment_status="paid", payment_id=f"yk-{number}",
        payload={"id": number, "items": [{"productId": "p1", "productName": "Кроссовки",
                                          "quantity": 1, "price": 11990}],
                 "checkoutData": {"phone": "+79148278470"}},
    )


@override_settings(INTEGRATION_1C_TOKEN=TOKEN)
class OneCSingleNumberTests(TestCase):
    def setUp(self):
        Product.objects.create(id="p1", name="Кроссовки", category_id="shoes",
                               price=11990, article="AR-X1", external_id="GUID-1")
        # Два покупателя оформили заказ с одним и тем же черновым номером —
        # настоящие номера у них разные.
        self.a = _paid("МАТА-11111111", user="u_a", client_ref="SS-1")
        self.b = _paid("МАТА-22222222", user="u_b", client_ref="SS-1")
        Notification.objects.all().delete()

    def _post(self, url, payload):
        return self.client.post(url, payload, content_type="application/json",
                                HTTP_AUTHORIZATION=f"Bearer {TOKEN}")

    def _pull(self):
        return self.client.get(PULL, HTTP_AUTHORIZATION=f"Bearer {TOKEN}").json()["orders"]

    def _refresh(self):
        self.a.refresh_from_db()
        self.b.refresh_from_db()

    # ── выдача ──────────────────────────────────────────────────────────────

    def test_pull_gives_one_number_and_no_server_id(self):
        orders = self._pull()
        self.assertEqual(sorted(o["orderId"] for o in orders),
                         ["МАТА-11111111", "МАТА-22222222"])
        for o in orders:
            self.assertNotIn("serverId", o)
            # Черновой номер приложения в 1С не уходит.
            self.assertNotIn("SS-1", str(o))

    # ── ack ─────────────────────────────────────────────────────────────────

    def test_ack_by_number_takes_only_that_order(self):
        body = self._post(ACK, {"orderIds": ["МАТА-11111111"]}).json()
        self.assertEqual(body, {"acked": 1, "unknown": [], "ambiguous": [],
                                "unknownServerIds": []})
        self._refresh()
        self.assertIsNotNone(self.a.onec_taken_at)
        self.assertIsNone(self.b.onec_taken_at)
        self.assertEqual([o["orderId"] for o in self._pull()], ["МАТА-22222222"])

    def test_ack_unknown_number_reported(self):
        body = self._post(ACK, {"orderIds": ["МАТА-99999999", "SS-1"]}).json()
        self.assertEqual(body["acked"], 0)
        # Черновой номер — не номер заказа для 1С.
        self.assertEqual(body["unknown"], ["SS-1", "МАТА-99999999"])

    def test_old_ack_by_server_id_still_accepted(self):
        body = self._post(ACK, {"serverIds": [self.b.pk]}).json()
        self.assertEqual(body["acked"], 1)
        self._refresh()
        self.assertIsNone(self.a.onec_taken_at)
        self.assertIsNotNone(self.b.onec_taken_at)

    # ── статусы ─────────────────────────────────────────────────────────────

    def test_status_by_number_moves_only_that_order(self):
        body = self._post(STATUS, {"orders": [
            {"orderId": "МАТА-11111111", "status": "shipped", "number": "Д-1"},
            {"orderId": "МАТА-22222222", "status": "delivered"},
        ]}).json()
        self.assertEqual((body["updated"], body["errors"]), (2, []))
        self._refresh()
        self.assertEqual((self.a.status, self.a.onec_status, self.a.onec_number),
                         ("shipped", "shipped", "Д-1"))
        self.assertEqual((self.b.status, self.b.onec_status), ("delivered", "delivered"))
        self.assertEqual(Notification.objects.filter(user_id="u_a").count(), 1)
        self.assertEqual(Notification.objects.filter(user_id="u_b").count(), 1)

    def test_status_unknown_number_reported(self):
        body = self._post(STATUS, {"orders": [{"orderId": "SS-1", "status": "shipped"}]}).json()
        self.assertEqual(body["updated"], 0)
        self.assertEqual(len(body["errors"]), 1)
        self._refresh()
        self.assertEqual((self.a.onec_status, self.b.onec_status), ("", ""))

    def test_old_status_by_server_id_still_accepted(self):
        body = self._post(STATUS, {"orders": [{"serverId": self.a.pk, "status": "shipped"}]}).json()
        self.assertEqual(body["updated"], 1)
        self._refresh()
        self.assertEqual(self.a.onec_status, "shipped")

    def test_old_server_id_and_number_must_agree(self):
        body = self._post(STATUS, {"orders": [
            {"serverId": self.a.pk, "orderId": "МАТА-22222222", "status": "shipped"},
        ]}).json()
        self.assertEqual(body["updated"], 0)
        self.assertEqual(len(body["errors"]), 1)


class OrderNumberTests(TestCase):
    def test_database_refuses_duplicate_number(self):
        _paid("МАТА-33333333", user="u_a")
        with self.assertRaises(IntegrityError), transaction.atomic():
            _paid("МАТА-33333333", user="u_b")

    def test_format_is_prefix_and_eight_digits(self):
        for _ in range(50):
            self.assertRegex(new_order_number(), r"^МАТА-[1-9]\d{7}$")

    def test_taken_number_is_skipped(self):
        _paid("МАТА-44444444", user="u_a")
        seq = iter(["МАТА-44444444", "МАТА-44444444", "МАТА-55555555"])
        with mock.patch("orders.numbers.random_number", side_effect=lambda: next(seq)):
            self.assertEqual(new_order_number(), "МАТА-55555555")

    def test_numbers_do_not_follow_order_count(self):
        """Номер ничего не говорит о числе заказов: подряд выданные не идут подряд."""
        numbers = [int(new_order_number()[5:]) for _ in range(20)]
        steps = {b - a for a, b in zip(numbers, numbers[1:])}
        self.assertGreater(len(steps), 1)
        self.assertNotEqual(steps, {1})


class ServerIssuesNumberApiTests(ApiTestCase):
    """Приложение присылает черновой номер, сервер отвечает настоящим."""

    phone = "+79990002120"

    def _order(self, ref):
        return self.api_post("/v1/orders", {"id": ref, "total": 100, "items": []})

    def test_server_number_replaces_draft(self):
        r = self._order("SS-77")
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertRegex(body["id"], r"^МАТА-\d{8}$")
        self.assertEqual(body["clientRef"], "SS-77")
        self.assertEqual(Order.objects.get(order_id=body["id"]).client_ref, "SS-77")

    def test_resubmit_of_draft_returns_same_order(self):
        first = self._order("SS-78").json()["id"]
        again = self._order("SS-78").json()["id"]
        self.assertEqual(first, again)
        self.assertEqual(Order.objects.filter(client_ref="SS-78").count(), 1)

    def test_resubmit_with_server_number_returns_same_order(self):
        first = self._order("SS-79").json()["id"]
        again = self._order(first).json()["id"]
        self.assertEqual(first, again)
        self.assertEqual(Order.objects.filter(user_id=self.uid).count(), 1)

    def test_old_build_finds_order_by_draft_number(self):
        """Старая сборка знает только черновой номер — оплата и статус находят заказ."""
        number = self._order("SS-80").json()["id"]
        r = self.api_get("/v1/orders/SS-80/payment")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["orderId"], number)

    def test_draft_of_another_user_is_not_found(self):
        _paid("МАТА-66666666", user="u_other", client_ref="SS-81")
        r = self.api_get("/v1/orders/SS-81/payment")
        self.assertEqual(r.status_code, 404)
