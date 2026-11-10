"""Заявки покупателей на возврат (D-112, D-122): покупатель оформляет, магазин осматривает
и решает по каждой вещи; отмена заказа до передачи курьеру.

Покупка как в tests_returns: куртка (позиция 0), две футболки (1, 2), доставка (3).
"""
import os
import tempfile
from datetime import timedelta
from io import BytesIO
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone

from common.testutils import ApiTestCase, verify_admin
from loyalty.models import add_txn
from orders import cancel as oc
from orders import return_requests as rr
from orders.models import Order, ReturnPhoto, ReturnRequest
from orders.tests_returns import _YK, PAYLOAD, _refund_ok


def _png(name="p.png"):
    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (16, 16), (200, 40, 40)).save(buf, "PNG")
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/png")


def _delivered(**extra):
    """Заказ получен покупателем: 1С прислала «доставлен»."""
    return {"onec_status": "delivered", "onec_status_at": timezone.now(), **extra}


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class ReturnRequestApiTests(ApiTestCase):
    phone = "+79990011201"

    def setUp(self):
        super().setUp()
        self.order = Order.objects.create(
            user_id=self.uid, order_id="SS-RR", total=4400, points_redeemed=900,
            payment_status="paid", payment_id="pay_rr", status="paid",
            payload=dict(PAYLOAD, id="SS-RR"), **_delivered(),
        )
        add_txn(self.uid, 2000, "runnerRun", "Баллы за бег")
        add_txn(self.uid, -900, "redeem", "Оплата баллами", "SS-RR")

    def _create(self, lines, method="store", photos=None):
        return self.api_post("/v1/orders/SS-RR/return-requests",
                             {"lines": lines, "method": method, "photos": photos or []})

    def test_old_app_without_photo_support_can_still_claim_defect(self):
        """Сборки до D-122 поле photos не шлют — брак без снимка не блокируем."""
        r = self.api_post("/v1/orders/SS-RR/return-requests",
                          {"lines": [{"index": 0, "reason": "defect",
                                      "comment": "отклеилась подошва"}],
                           "method": "store"})
        self.assertEqual(r.status_code, 201, r.content)

    def _options(self):
        r = self.client.get("/v1/orders/SS-RR/return-options",
                            HTTP_AUTHORIZATION=f"Bearer {self.token}")
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()

    def _photo(self):
        r = self.client.post("/v1/return-photos", {"image": _png()},
                             HTTP_AUTHORIZATION=f"Bearer {self.token}")
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()["id"]

    def test_options_list_goods_only(self):
        body = self._options()
        self.assertTrue(body["canReturn"])
        self.assertEqual([line["index"] for line in body["lines"]], [0, 1, 2])
        self.assertIn("size", body["reasons"])
        # Получен — отменять поздно, только возврат.
        self.assertFalse(body["canCancel"])

    def test_request_number_built_from_order_number(self):
        first = self._create([{"index": 1, "reason": "size"}])
        self.assertEqual(first.json()["number"], "SS-RR-В1")
        second = self._create([{"index": 2, "reason": "style"}])
        self.assertEqual(second.json()["number"], "SS-RR-В2")

    def test_customer_creates_request_and_line_becomes_busy(self):
        r = self._create([{"index": 1, "reason": "size"}])
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["status"], "awaiting")
        again = self._create([{"index": 1, "reason": "style"}])
        self.assertEqual(again.status_code, 409)

    def test_parcel_is_accepted_by_law(self):
        """КС 7-П: дистанционно купленное можно вернуть посылкой — не отклоняем."""
        r = self._create([{"index": 0, "reason": "size"}], method="parcel")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["method"], "parcel")
        self.assertTrue(r.json()["needsTrack"])

    def test_defect_needs_description_and_photo(self):
        self.assertEqual(self._create([{"index": 0, "reason": "defect"}]).status_code, 400)
        no_photo = self._create([{"index": 0, "reason": "defect",
                                  "comment": "отклеилась подошва"}])
        self.assertEqual(no_photo.status_code, 400)
        self.assertIn("фото", no_photo.json()["detail"])
        # Отказ откатил заявку целиком — вещь не «занята».
        self.assertFalse(ReturnRequest.objects.exists())
        r = self._create([{"index": 0, "reason": "defect", "comment": "отклеилась подошва"}],
                         photos=[self._photo()])
        self.assertEqual(r.status_code, 201, r.content)
        req = ReturnRequest.objects.get(pk=r.json()["id"])
        self.assertTrue(req.defect_claimed)
        self.assertEqual(req.photos.count(), 1)
        self.assertEqual(len(r.json()["photos"]), 1)

    def test_cannot_attach_someone_elses_photo(self):
        alien = ReturnPhoto.objects.create(user_id="u_other", image="returns/x.png")
        r = self._create([{"index": 0, "reason": "defect", "comment": "дырка на шве"}],
                         photos=[alien.pk])
        self.assertEqual(r.status_code, 400)

    def test_window_closed_for_good_item_but_open_for_defect(self):
        Order.objects.filter(pk=self.order.pk).update(
            onec_status_at=timezone.now() - timedelta(days=rr.RETURN_DAYS + 1))
        body = self._options()
        self.assertTrue(body["canReturn"])
        self.assertFalse(body["standardOpen"])
        self.assertIn("26.1", body["standardNote"])
        refused = self._create([{"index": 1, "reason": "size"}])
        self.assertEqual(refused.status_code, 400)
        self.assertIn("истёк", refused.json()["detail"])
        r = self._create([{"index": 1, "reason": "defect", "comment": "дырка на шве"}],
                         photos=[self._photo()])
        self.assertEqual(r.status_code, 201, r.content)

    def test_everything_closed_after_two_years(self):
        Order.objects.filter(pk=self.order.pk).update(
            onec_status_at=timezone.now() - timedelta(days=rr.DEFECT_DAYS + 1))
        body = self._options()
        self.assertFalse(body["canReturn"])
        self.assertIn("истёк", body["reason"])

    def test_shipped_order_window_counts_transit(self):
        """Отгружен, «доставлен» не пришёл: срок не сгорает, пока заказ едет."""
        Order.objects.filter(pk=self.order.pk).update(
            onec_status="shipped",
            onec_status_at=timezone.now() - timedelta(days=rr.RETURN_DAYS + 3))
        self.assertTrue(self._options()["standardOpen"])

    def test_not_received_order_offers_cancel_not_return(self):
        Order.objects.filter(pk=self.order.pk).update(onec_status="", onec_status_at=None)
        body = self._options()
        self.assertFalse(body["canReturn"])
        self.assertTrue(body["canCancel"])
        self.assertEqual(self._create([{"index": 1, "reason": "size"}]).status_code, 400)

    def test_unpaid_order_cannot_be_returned(self):
        Order.objects.filter(pk=self.order.pk).update(payment_status="pending")
        self.assertEqual(self._create([{"index": 1, "reason": "size"}]).status_code, 400)

    def test_cancel_only_before_item_sent(self):
        rid = self._create([{"index": 1, "reason": "size"}]).json()["id"]
        r = self.api_post(f"/v1/return-requests/{rid}/cancel", {})
        self.assertEqual(r.json()["status"], "canceled")
        # Отменили — вещь снова можно заявить.
        self.assertEqual(self._create([{"index": 1, "reason": "size"}]).status_code, 201)

    def test_parcel_track_number_keeps_request_alive(self):
        rid = self._create([{"index": 1, "reason": "size"}], method="parcel").json()["id"]
        self.assertEqual(self.api_post(f"/v1/return-requests/{rid}/sent",
                                       {"trackNumber": "1"}).status_code, 400)
        r = self.api_post(f"/v1/return-requests/{rid}/sent", {"trackNumber": "RA123456789RU"})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["status"], "sent")
        self.assertEqual(r.json()["trackNumber"], "RA123456789RU")
        # Посылка в пути — не истекает и не отменяется.
        ReturnRequest.objects.filter(pk=rid).update(
            bring_until=timezone.now() - timedelta(days=1))
        self.assertEqual(rr.expire_stale(), 0)
        self.assertEqual(self.api_post(f"/v1/return-requests/{rid}/cancel", {}).status_code, 409)

    def test_track_number_only_for_parcel(self):
        rid = self._create([{"index": 1, "reason": "size"}]).json()["id"]
        r = self.api_post(f"/v1/return-requests/{rid}/sent", {"trackNumber": "RA123456789RU"})
        self.assertEqual(r.status_code, 400)

    def test_other_user_cannot_see_order(self):
        other = Order.objects.create(user_id="u_other", order_id="SS-OT", total=1,
                                     payment_status="paid", payment_id="p")
        r = self.api_post("/v1/orders/SS-OT/return-requests",
                          {"lines": [{"index": 0, "reason": "size"}], "method": "store"})
        self.assertEqual(r.status_code, 404)
        self.assertFalse(other.return_requests.exists())

    def test_loose_photos_are_cleaned_up(self):
        pid = self._photo()
        ReturnPhoto.objects.filter(pk=pid).update(created_at=timezone.now() - timedelta(days=2))
        rr.expire_stale()
        self.assertFalse(ReturnPhoto.objects.filter(pk=pid).exists())


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class ReturnRequestFlowTests(ApiTestCase):
    """Сторона магазина: получили → осмотрели → решение по каждой вещи."""
    phone = "+79990011202"

    def setUp(self):
        super().setUp()
        self.order = Order.objects.create(
            user_id=self.uid, order_id="SS-RF", total=4400, points_redeemed=900,
            payment_status="paid", payment_id="pay_rf", status="paid",
            payload=dict(PAYLOAD, id="SS-RF"), **_delivered(),
        )
        add_txn(self.uid, 2000, "runnerRun", "Баллы за бег")
        add_txn(self.uid, -900, "redeem", "Оплата баллами", "SS-RF")
        self.req = rr.create(self.order, self.uid, [{"index": 1, "reason": "size"}], "store")

    def _refunding(self):
        return mock.patch.dict(os.environ, _YK), \
            mock.patch("orders.payment._http", side_effect=_refund_ok)

    def test_cannot_decide_before_item_is_received(self):
        with self.assertRaises(rr.RequestError):
            rr.approve(self.req, "staff")
        with self.assertRaises(rr.RequestError):
            rr.reject(self.req, "Следы носки", "staff")

    def test_approve_refunds_exactly_the_requested_line(self):
        rr.mark_received(self.req, "staff")
        env, http = self._refunding()
        with env, http:
            req = rr.approve(self.req, "staff")
        self.assertEqual(req.status, ReturnRequest.APPROVED)
        self.assertEqual(req.order_return.lines, [1])
        self.assertEqual(req.order_return.status, "done")
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, "partially_refunded")

    def test_reject_needs_reason_shown_to_customer(self):
        rr.mark_received(self.req, "staff")
        with self.assertRaises(rr.RequestError):
            rr.reject(self.req, "", "staff")
        req = rr.reject(self.req, "Сняты фабричные ярлыки, следы носки", "staff")
        self.assertEqual(req.status, ReturnRequest.REJECTED)
        self.assertEqual(self.order.returns.count(), 0)
        self.assertTrue(rr.to_json(req)["needsGoodsBack"])

    def test_partial_decision_refunds_only_accepted_items(self):
        req = rr.create(self.order, self.uid, [{"index": 0, "reason": "size"},
                                               {"index": 2, "reason": "style"}], "store")
        rr.mark_received(req, "staff")
        env, http = self._refunding()
        with env, http:
            req = rr.decide(req, {0: {"decision": "accept"},
                                  2: {"decision": "reject", "reasons": ["worn", "no_tags"]}},
                            by="staff")
        self.assertEqual(req.status, ReturnRequest.PARTIAL)
        self.assertEqual(req.order_return.lines, [0])
        body = rr.to_json(req)
        rejected = [line for line in body["lines"] if line["decision"] == "reject"]
        self.assertEqual(rejected[0]["rejectReasonLabels"][0], rr.REJECT_REASONS["worn"])

    def test_every_item_needs_a_decision_and_reasons(self):
        rr.mark_received(self.req, "staff")
        with self.assertRaises(rr.RequestError):
            rr.decide(self.req, {}, by="staff")
        with self.assertRaises(rr.RequestError):
            rr.decide(self.req, {1: {"decision": "reject"}}, by="staff")
        with self.assertRaises(rr.RequestError):  # «Другое» без пояснения
            rr.decide(self.req, {1: {"decision": "reject", "reasons": ["other"]}}, by="staff")

    def test_defect_cannot_be_refused_for_tags_or_marking(self):
        """Ст. 18: по заявленному браку отказ — только по проверке качества."""
        req = rr.create(self.order, self.uid,
                        [{"index": 0, "reason": "defect", "comment": "шов разошёлся"}],
                        "store", [rr.upload_photo(self.uid, _png()).pk])
        rr.mark_received(req, "staff")
        with self.assertRaises(rr.RequestError):
            rr.decide(req, {0: {"decision": "reject", "reasons": ["no_tags"]}}, by="staff")
        done = rr.decide(req, {0: {"decision": "reject", "reasons": ["not_defect"]}},
                         by="staff")
        self.assertEqual(done.status, ReturnRequest.REJECTED)

    def test_customer_chooses_how_to_get_rejected_items_back(self):
        rr.mark_received(self.req, "staff")
        rr.reject(self.req, "Следы носки на подошве", "staff")
        r = self.api_post(f"/v1/return-requests/{self.req.pk}/goods-back", {"way": "teleport"})
        self.assertEqual(r.status_code, 400)
        r = self.api_post(f"/v1/return-requests/{self.req.pk}/goods-back", {"way": "ship"})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["goodsBack"], "ship")
        self.assertEqual(rr.needs_attention(), 1)
        rr.mark_goods_back_done(self.req, "staff")
        self.assertEqual(rr.needs_attention(), 0)

    def test_unbrought_request_expires(self):
        ReturnRequest.objects.filter(pk=self.req.pk).update(
            bring_until=timezone.now() - timedelta(minutes=1))
        self.assertEqual(rr.expire_stale(), 1)
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, ReturnRequest.EXPIRED)
        # Покупатель всё же пришёл — магазин может принять товар по истёкшей заявке.
        rr.mark_received(self.req, "staff")

    def test_staff_page_decides(self):
        from django.contrib.auth import get_user_model

        admin = get_user_model().objects.create_superuser("boss", "boss@example.ru", "pw")
        self.client.force_login(admin)
        verify_admin(self.client, admin)
        url = f"/admin/return-request/{self.req.pk}/"
        self.assertEqual(self.client.get(url).status_code, 200)
        self.client.post(url, {"action": "received"})
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, ReturnRequest.RECEIVED)
        env, http = self._refunding()
        with env, http:
            self.client.post(url, {"action": "decide", "decision_1": "accept"})
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, ReturnRequest.APPROVED)


class OrderCancelTests(ApiTestCase):
    """Отмена до передачи курьеру: сразу, если 1С ещё не забрала; иначе — через склад."""
    phone = "+79990011203"

    def setUp(self):
        super().setUp()
        self.order = Order.objects.create(
            user_id=self.uid, order_id="SS-OC", total=4400, points_redeemed=900,
            payment_status="paid", payment_id="pay_oc", status="paid",
            payload=dict(PAYLOAD, id="SS-OC"),
        )
        add_txn(self.uid, 2000, "runnerRun", "Баллы за бег")
        add_txn(self.uid, -900, "redeem", "Оплата баллами", "SS-OC")

    def _cancel(self):
        with mock.patch.dict(os.environ, _YK), \
                mock.patch("orders.payment._http", side_effect=_refund_ok):
            return self.api_post("/v1/orders/SS-OC/cancel", {})

    def test_cancel_before_1c_refunds_everything_at_once(self):
        r = self._cancel()
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["status"], "canceled")
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, "refunded")
        self.assertEqual(self.order.status, "cancelled")

    def test_cancelling_order_never_reaches_1c_queue(self):
        from integrations.onec_orders import pending_orders

        Order.objects.filter(pk=self.order.pk).update(cancel_requested_at=timezone.now())
        self.assertNotIn(self.order.pk, [o.pk for o in pending_orders()])

    def test_taken_by_1c_becomes_request_for_staff(self):
        Order.objects.filter(pk=self.order.pk).update(onec_taken_at=timezone.now(),
                                                      onec_status="assembled")
        r = self._cancel()
        self.assertEqual(r.json()["status"], "requested")
        self.assertTrue(r.json()["cancelRequested"])
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, "paid")  # деньги — после склада
        with mock.patch.dict(os.environ, _YK), \
                mock.patch("orders.payment._http", side_effect=_refund_ok):
            oc.confirm_cancel(self.order, "staff")
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, "refunded")

    def test_staff_declines_when_already_with_courier(self):
        Order.objects.filter(pk=self.order.pk).update(onec_taken_at=timezone.now())
        self._cancel()
        Order.objects.filter(pk=self.order.pk).update(onec_status="shipped")
        with self.assertRaises(oc.CancelError):
            oc.confirm_cancel(self.order, "staff")
        oc.decline_cancel(self.order, "staff")
        self.order.refresh_from_db()
        self.assertIsNone(self.order.cancel_requested_at)

    def test_too_late_after_courier(self):
        Order.objects.filter(pk=self.order.pk).update(onec_status="shipped")
        r = self._cancel()
        self.assertEqual(r.status_code, 409)
        self.assertIn("курьеру", r.json()["detail"])
