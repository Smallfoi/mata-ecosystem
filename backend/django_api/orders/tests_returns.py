"""Возврат заказа целиком и частями (D-73).

Покупка в тестах: куртка 3000 ₽, две футболки по 1000 ₽, доставка 300 ₽ — всего
5300 ₽. Списано 900 баллов, оплачено деньгами 4400 ₽, начислено за покупку 440 баллов.
"""
import os
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase

from common.testutils import verify_admin
from loyalty.models import add_txn, balance_of
from orders.models import Order, OrderReturn
from orders.payment import PaymentError
from orders.receipt import allocate
from orders.returns import ReturnError, make_return
from staff.models import LEVEL_EDIT, LEVEL_VIEW, StaffProfile, TabPermission

UID = "u_ret"
_YK = {"YOOKASSA_SHOP_ID": "654321", "YOOKASSA_SECRET_KEY": "test_secret_key"}

PAYLOAD = {
    "id": "SS-R",
    "deliveryCost": 300,
    "items": [
        {"productName": "Куртка", "price": 3000, "quantity": 1},
        {"productName": "Футболка", "price": 1000, "quantity": 2},
    ],
    "checkoutData": {"phone": "+79148278470", "email": "buyer@example.test"},
}


def _refund_ok(method, url, payload=None, headers=None):
    return {"id": "rf_" + headers["Idempotence-Key"][:8], "status": "succeeded"}


def _paid_order(order_id="SS-R", payload=None, total=4400, payment_id="pay_1"):
    return Order.objects.create(
        user_id=UID, order_id=order_id, total=total, points_redeemed=900,
        payment_status="paid", payment_id=payment_id, status="paid",
        payload=dict(payload or PAYLOAD, id=order_id),
    )


class ReturnTests(TestCase):
    def setUp(self):
        cache.clear()
        self.order = _paid_order()
        add_txn(UID, 2000, "runnerRun", "Баллы за бег")
        add_txn(UID, -900, "redeem", "Оплата баллами", "SS-R")
        add_txn(UID, 440, "purchase", "Покупка на 4400 ₽", "SS-R")
        self.start = balance_of(UID)  # 1540

    def _return(self, lines, http=None):
        with mock.patch.dict(os.environ, _YK), \
                mock.patch("orders.payment._http", side_effect=http or _refund_ok) as h:
            ret = make_return(self.order.pk, lines, by="tester")
        self.order.refresh_from_db()
        return ret, h

    def test_partial_return_follows_the_receipt(self):
        """Вернули одну футболку: деньги — ровно её строка в чеке, баллы — её доля."""
        paid = {row["index"]: row["paid"] for row in allocate(PAYLOAD, 4400)}
        ret, http = self._return([1])

        self.assertEqual(http.call_args[0][2]["amount"]["value"], f"{paid[1] / 100:.2f}")
        self.assertEqual(ret.amount_kop, paid[1])
        self.assertEqual(ret.points_returned, 900 * 1000 // 5300)  # доля футболки до скидки
        self.assertEqual(ret.points_revoked, 440 * paid[1] // 440000)
        self.assertEqual(self.order.payment_status, "partially_refunded")
        self.assertEqual(self.order.status, "paid")
        self.assertEqual(balance_of(UID),
                         self.start + ret.points_returned - ret.points_revoked)

    def test_returning_everything_in_parts_adds_up_exactly(self):
        """Частями вернули всё: в сумме ровно оплата и ровно списанные и начисленные баллы."""
        first, _ = self._return([1])
        last, _ = self._return([0, 2])

        self.assertEqual(first.amount_kop + last.amount_kop, 440000)
        self.assertEqual(first.points_returned + last.points_returned, 900)
        self.assertEqual(first.points_revoked + last.points_revoked, 440)
        self.assertIn(3, last.lines, "доставка должна уйти вместе с последней вещью")
        self.assertEqual(self.order.payment_status, "refunded")
        self.assertEqual(self.order.status, "cancelled")
        self.assertEqual(balance_of(UID), 2000)

    def test_whole_order_at_once(self):
        ret, _ = self._return([0, 1, 2])
        self.assertEqual(ret.amount_kop, 440000)
        self.assertEqual(balance_of(UID), 2000)

    def test_same_item_cannot_be_returned_twice(self):
        self._return([1])
        with self.assertRaises(ReturnError):
            self._return([1])

    def test_delivery_alone_is_not_returnable(self):
        with self.assertRaises(ReturnError):
            self._return([3])

    def test_equal_partial_returns_are_two_refunds_not_one(self):
        """Две футболки по одной — суммы равны. Ключ «платёж + сумма» склеил бы
        их в один возврат, и за вторую футболку деньги бы не пришли."""
        first, h1 = self._return([1])
        second, h2 = self._return([2])
        self.assertEqual(first.amount_kop, second.amount_kop)
        self.assertNotEqual(h1.call_args[0][3]["Idempotence-Key"],
                            h2.call_args[0][3]["Idempotence-Key"])

    def test_failed_refund_changes_nothing_and_can_be_retried(self):
        def boom(*args, **kwargs):
            raise PaymentError("ЮKassa 500: internal")

        with self.assertRaises(ReturnError):
            self._return([1], http=boom)
        self.assertEqual(balance_of(UID), self.start)
        self.assertEqual(OrderReturn.objects.get().status, "failed")
        self.assertEqual(self.order.payment_status, "paid")

        ret, _ = self._return([1])
        self.assertEqual(ret.status, "done")

    def test_only_orders_paid_through_yookassa(self):
        Order.objects.filter(pk=self.order.pk).update(payment_id="")
        with self.assertRaises(ReturnError):
            self._return([1])
        Order.objects.filter(pk=self.order.pk).update(payment_id="pay_1",
                                                      payment_status="pending")
        with self.assertRaises(ReturnError):
            self._return([1])

    def test_return_in_progress_blocks_a_second_one(self):
        """Два возврата одновременно посчитали бы остаток каждый по-своему."""
        OrderReturn.objects.create(order=self.order, lines=[0], amount_kop=1, status="pending")
        with self.assertRaises(ReturnError):
            self._return([1])

    def test_balance_may_go_negative(self):
        """Начисленные баллы уже потрачены — снимаем всё равно, как и до частичных возвратов.

        Решение про минус владелец отложил (D-73, на паузе). Тест фиксирует нынешнее
        поведение, чтобы его смена была осознанной, а не случайной.
        """
        other = _paid_order("SS-N", payload={
            "items": [{"productName": "Кепка", "price": 1000, "quantity": 1}]},
            total=1000, payment_id="pay_2")
        add_txn(UID, 100, "purchase", "Покупка на 1000 ₽", "SS-N")
        add_txn(UID, -balance_of(UID), "redeem", "Потратил всё", "SS-OTHER")

        with mock.patch.dict(os.environ, _YK), \
                mock.patch("orders.payment._http", side_effect=_refund_ok):
            make_return(other.pk, [0])
        self.assertEqual(balance_of(UID), -100)

    @mock.patch.dict(os.environ, {"PAYMENT_RECEIPT": "1"})
    def test_refund_receipt_holds_only_the_returned_positions(self):
        """Чек возврата — только возвращаемые вещи, и сумма в нём равна возврату."""
        ret, http = self._return([1])
        receipt = http.call_args[0][2]["receipt"]
        self.assertEqual(len(receipt["items"]), 1)
        kop = sum(round(float(i["amount"]["value"]) * 100) for i in receipt["items"])
        self.assertEqual(kop, ret.amount_kop)


class ReturnPageTests(TestCase):
    """Страница возврата: кто видит расчёт и кто может провести возврат."""

    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.owner = User.objects.create_superuser("owner_r", "o@t.dev", "OwnerPass!2026")
        self.staff = User.objects.create_user("clerk@t.dev", "clerk@t.dev",
                                              "ClerkPass!2026", is_staff=True)
        StaffProfile.objects.create(user=self.staff, full_name="Кладовщик")
        self.order = _paid_order()
        add_txn(UID, 2000, "runnerRun", "Баллы за бег")
        add_txn(UID, -900, "redeem", "Оплата баллами", "SS-R")
        add_txn(UID, 440, "purchase", "Покупка на 4400 ₽", "SS-R")
        self.url = f"/admin/order-return/{self.order.pk}/"

    def _login(self, user):
        self.client.force_login(user)
        verify_admin(self.client, user)

    def grant(self, level):
        TabPermission.objects.update_or_create(user=self.staff, tab="orders",
                                               defaults={"level": level})

    def test_closed_without_second_factor(self):
        self.client.force_login(self.owner)
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r["Location"].startswith("/admin/2fa/"))

    def test_closed_without_the_orders_tab(self):
        self._login(self.staff)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_page_lists_items_and_delivery(self):
        self._login(self.owner)
        html = self.client.get(self.url).content.decode()
        self.assertIn("Куртка", html)
        self.assertIn("Доставка", html)

    def test_view_level_sees_the_calculation_but_cannot_return(self):
        self.grant(LEVEL_VIEW)
        self._login(self.staff)
        r = self.client.post(self.url, {"action": "preview", "line": ["1"]})
        self.assertEqual(r.status_code, 200)
        self.assertIn("Вернём покупателю", r.content.decode())
        self.assertNotIn('value="confirm"', r.content.decode())

        r = self.client.post(self.url, {"action": "confirm", "line": ["1"]})
        self.assertEqual(r.status_code, 403)
        self.assertFalse(OrderReturn.objects.exists())

    def test_edit_level_returns(self):
        self.grant(LEVEL_EDIT)
        self._login(self.staff)
        with mock.patch.dict(os.environ, _YK), \
                mock.patch("orders.payment._http", side_effect=_refund_ok):
            r = self.client.post(self.url, {"action": "confirm", "line": ["1"]})
        self.assertEqual(r.status_code, 302)  # POST → redirect: F5 не повторит возврат
        self.assertEqual(OrderReturn.objects.get().status, "done")
