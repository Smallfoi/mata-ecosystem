"""Заказ в API отражает актуальное состояние сервера (аудит B08, серверная часть).

Раньше `/v1/orders` возвращал payload, присланный приложением при оформлении:
оплата, отгрузка из 1С, отмена по таймеру меняли колонки модели, а покупатель
продолжал видеть «ожидает». Теперь поверх payload сервер кладёт свои поля.

Совместимость: старые сборки Store знают статусы `pending | processing | shipped |
delivered | cancelled` и неизвестный статус читают как `pending`. Поэтому в
`status` серверное «оплачен» (`paid`) отдаётся как `processing`, а сырой статус —
в новом поле `serverStatus`.
"""
from django.test import override_settings

from common.testutils import ApiTestCase
from orders.models import Order


class OrderStateInApiTests(ApiTestCase):
    phone = "+79990002811"

    def _create(self, oid="SS-ST1", status="pending"):
        r = self.api_post("/v1/orders", {"id": oid, "total": 500, "items": [],
                                         "status": status, "subtotal": 500,
                                         "deliveryCost": 0,
                                         "checkoutData": {"name": "Тест"}})
        self.assertEqual(r.status_code, 200)
        return Order.objects.get(user_id=self.uid, order_id=oid)

    def _listed(self, oid):
        return next(o for o in self.api_get("/v1/orders").json() if o["id"] == oid)

    def test_payload_fields_are_kept(self):
        self._create()
        o = self._listed("SS-ST1")
        self.assertEqual(o["checkoutData"], {"name": "Тест"})
        self.assertEqual(o["subtotal"], 500)
        self.assertEqual(o["status"], "pending")
        self.assertEqual(o["paymentStatus"], "pending")

    def test_paid_order_shows_as_processing_for_old_clients(self):
        order = self._create()
        self.api_post("/v1/orders/SS-ST1/pay", {})   # dev: оплата сразу проходит
        order.refresh_from_db()
        self.assertEqual(order.status, "paid")
        o = self._listed("SS-ST1")
        self.assertEqual(o["status"], "processing")
        self.assertEqual(o["serverStatus"], "paid")
        self.assertEqual(o["paymentStatus"], "paid")
        self.assertEqual(o["serverId"], order.pk)

    @override_settings(INTEGRATION_1C_TOKEN="t-1c")
    def test_status_from_1c_is_visible_in_api(self):
        order = self._create()
        Order.objects.filter(pk=order.pk).update(
            status="paid", payment_status="paid", payment_id="yk-1")
        r = self.client.post(
            "/v1/integrations/1c/orders/status",
            {"orders": [{"serverId": order.pk, "status": "shipped", "number": "Д-77"}]},
            content_type="application/json", HTTP_AUTHORIZATION="Bearer t-1c")
        self.assertEqual(r.json()["updated"], 1)

        o = self._listed("SS-ST1")
        self.assertEqual(o["status"], "shipped")
        self.assertEqual(o["serverStatus"], "shipped")
        self.assertEqual(o["onecStatus"], "shipped")
        self.assertEqual(o["onecNumber"], "Д-77")
        self.assertTrue(o["onecStatusAt"])

    def test_warehouse_stage_keeps_status_but_is_exposed(self):
        order = self._create()
        Order.objects.filter(pk=order.pk).update(
            status="paid", payment_status="paid", onec_status="assembled")
        o = self._listed("SS-ST1")
        self.assertEqual(o["status"], "processing")
        self.assertEqual(o["onecStatus"], "assembled")

    def test_cancel_by_server_is_visible(self):
        order = self._create()
        Order.objects.filter(pk=order.pk).update(status="cancelled", payment_status="canceled")
        o = self._listed("SS-ST1")
        self.assertEqual(o["status"], "cancelled")
        self.assertEqual(o["paymentStatus"], "canceled")

    def test_courier_note_is_exposed(self):
        order = self._create()
        Order.objects.filter(pk=order.pk).update(courier_note="Иван, +7 900, к 18:00")
        self.assertEqual(self._listed("SS-ST1")["courierNote"], "Иван, +7 900, к 18:00")

    def test_to_json_does_not_mutate_stored_payload(self):
        order = self._create()
        Order.objects.filter(pk=order.pk).update(status="shipped")
        order.refresh_from_db()
        order.to_json()
        self.assertNotIn("serverStatus", order.payload)
        self.assertEqual(order.payload["status"], "pending")

    def test_unknown_server_status_falls_back_to_payload_status(self):
        order = self._create(status="processing")
        Order.objects.filter(pk=order.pk).update(status="weird")
        o = self._listed("SS-ST1")
        self.assertEqual(o["status"], "processing")
        self.assertEqual(o["serverStatus"], "weird")
