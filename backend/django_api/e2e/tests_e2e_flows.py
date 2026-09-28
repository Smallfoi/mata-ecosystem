"""Сквозные сценарии экосистемы — только настоящими URL, как ходят приложения и 1С.

Зачем (аудит F06): модульные тесты проверяют каждое звено отдельно, а деньги теряются
на стыках — заказ оплачен, но не ушёл в 1С; статус из 1С пришёл, а покупатель его не
видит; баллы за бег есть, но списать их в Store нельзя. Здесь каждый сценарий — один
путь человека от входа до конца.

1. Store: вход по коду → заказ в формате приложения (mata_store `Order.toJson`) →
   тестовая оплата (D-97, `Account.test_payment`) → баллы за покупку → 1С забирает
   заказ → ack → 1С присылает «доставлен» → покупатель видит заказ → выгрузка данных
   (152-ФЗ) → удаление аккаунта.
2. Квартал → Store: пробежка → баллы за бег → списание этих баллов в заказе.

Проверки намеренно по устойчивым признакам (коды ответа, баланс, наличие заказа),
а не по точной форме JSON: параллельно ждут вливания PR, меняющие эти потоки
(#805, #809, #810, #814, #819, #822). Места, где ожидание поменяется после их
вливания, помечены «ПОСЛЕ #…».
"""
import json
import os
import time
import unittest
from datetime import timedelta
from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings, tag
from django.utils import timezone

from accounts.models import Account
from catalog.models import Product
from loyalty.models import LoyaltyTransaction
from orders.models import Order

ONEC_TOKEN = "e2e-1c-token"
ONEC_PULL = "/v1/integrations/1c/orders"
ONEC_ACK = "/v1/integrations/1c/orders/ack"
ONEC_STATUS = "/v1/integrations/1c/orders/status"

# Переменные, от которых зависит режим: провайдеры входа и оплаты выключены,
# режим разработки (dev-код 1234 и тестовая оплата работают только в нём).
_MODE_VARS = ("SMS_PROVIDER", "PAYMENT_PROVIDER", "SEED_DEMO_POINTS",
              "YOOKASSA_SHOP_ID", "YOOKASSA_SECRET_KEY", "FISCAL_RECEIPTS")


def _order_fixed_by_805() -> bool:
    """В /v1/orders — серверный статус заказа (аудит B08, PR #805)."""
    return hasattr(Order, "CLIENT_STATUS")


def expected_failure_until(fixed: bool):
    """expectedFailure, пока исправление не влито; после — обычный тест.

    Сам снимается, когда в коде появляется признак исправления, — иначе вливание
    исправления превращало бы тест в «unexpected success» и роняло CI.
    """
    def wrap(fn):
        return fn if fixed else unittest.expectedFailure(fn)
    return wrap


class _Journey(TestCase):
    """Общие шаги пути покупателя/бегуна — через HTTP, без прямых вызовов функций."""

    phone = "+79990077001"

    def setUp(self):
        cache.clear()  # лимиты и кэш баланса не должны тянуться из соседних тестов
        env = mock.patch.dict(os.environ, {"DJANGO_DEBUG": "1"})
        env.start()
        self.addCleanup(env.stop)  # patch.dict вернёт и удалённые ниже ключи
        for k in _MODE_VARS:
            os.environ.pop(k, None)
        Product.objects.create(
            id="e2e-shoe-42", name="Кроссовки E2E", category_id="shoes",
            price=11990, sizes=["42"], colors=["Чёрный"],
            article="E2E-ART-1", external_id="E2E-GUID-1",
        )
        Product.objects.create(
            id="e2e-gel", name="Гель E2E", category_id="nutrition", price=1000,
            article="E2E-ART-2", external_id="E2E-GUID-2",
        )

    # ── HTTP ────────────────────────────────────────────────────────────────
    def _post(self, path, body, token=None, **extra):
        if token:
            extra["HTTP_AUTHORIZATION"] = f"Bearer {token}"
        return self.client.post(path, data=json.dumps(body),
                                content_type="application/json", **extra)

    def _get(self, path, token=None):
        extra = {"HTTP_AUTHORIZATION": f"Bearer {token}"} if token else {}
        return self.client.get(path, **extra)

    # ── Шаги ────────────────────────────────────────────────────────────────
    def login(self, phone=None):
        """Вход по коду: запрос кода → ввод. В разработке код всегда 1234."""
        phone = phone or self.phone
        r = self._post("/v1/auth/phone/request", {"phone": phone})
        self.assertEqual(r.status_code, 200, r.content)
        r = self._post("/v1/auth/phone/verify", {"phone": phone, "code": "1234"})
        self.assertEqual(r.status_code, 200, r.content)
        token = r.json()["token"]
        self.assertTrue(token)
        # Токен живой: профиль открывается.
        me = self._get("/v1/auth/me", token)
        self.assertEqual(me.status_code, 200, me.content)
        return token, Account.objects.get(phone=phone).id

    def balance(self, token):
        r = self._get("/v1/loyalty/account", token)
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()["balance"]

    def three_days_pass(self, uid):
        """Баллы за бег созревают 3 дня (решение 28.09.2026) — «прошло 3 дня»."""
        LoyaltyTransaction.objects.filter(
            user_id=uid, available_at__isnull=False
        ).update(available_at=timezone.now() - timedelta(seconds=1))
        cache.clear()

    def store_order(self, oid, items, points=0, delivery=0.0):
        """Заказ ровно в том виде, как его шлёт mata_store (`Order.toJson`)."""
        subtotal = sum(i["price"] * i["quantity"] for i in items)
        return {
            "id": oid,
            "items": [{
                "productId": i["productId"], "productName": i["productName"],
                "productBrand": "МАТА", "imageUrl": "", "price": float(i["price"]),
                "size": i.get("size", ""), "color": i.get("color", ""),
                "quantity": i["quantity"],
            } for i in items],
            "subtotal": float(subtotal),
            "deliveryCost": float(delivery),
            "pointsRedeemed": points,
            "total": float(subtotal + delivery - points),
            "checkoutData": {
                "name": "Тест Покупатель", "phone": self.phone,
                "email": "e2e@example.com", "deliveryType": "courier",
                "city": "Якутск", "street": "Ленина", "house": "1",
                "apartment": "5", "postalCode": "677000", "paymentType": "sbp",
            },
            "status": "pending",
            "createdAt": timezone.now().isoformat(),
        }

    def my_order(self, token, oid):
        r = self._get("/v1/orders", token)
        self.assertEqual(r.status_code, 200, r.content)
        found = [o for o in r.json() if o.get("id") == oid]
        self.assertEqual(len(found), 1, f"заказ {oid} должен быть в /v1/orders ровно один раз")
        return found[0]

    def pay_test(self, token, oid):
        """Тестовая оплата (D-97): право выдаёт сотрудник в админке."""
        uid = Account.objects.get(phone=self.phone).id
        Account.objects.filter(id=uid).update(test_payment=True)
        r = self._post(f"/v1/orders/{oid}/pay", {}, token)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["status"], "paid")
        # Перепроверка статуса покупателем говорит то же самое.
        st = self._get(f"/v1/orders/{oid}/payment", token)
        self.assertEqual(st.status_code, 200, st.content)
        self.assertEqual(st.json()["status"], "paid")
        return r.json()

    def onec_pull(self):
        r = self._get(ONEC_PULL, ONEC_TOKEN)
        self.assertEqual(r.status_code, 200, r.content)
        return {o["orderId"]: o for o in r.json()["orders"]}


@tag("e2e")
@override_settings(INTEGRATION_1C_TOKEN=ONEC_TOKEN)
class StoreOrderJourneyE2E(_Journey):
    """Путь покупателя Store от входа до удаления аккаунта."""

    phone = "+79990077001"
    oid = "SS-E2E-1"

    def _to_delivery(self):
        """Вход → заказ → оплата → баллы → 1С забрала → ack → «доставлен»."""
        token, uid = self.login()
        start = self.balance(token)

        # Заказ из приложения.
        body = self.store_order(self.oid, [{
            "productId": "e2e-shoe-42", "productName": "Кроссовки E2E",
            "price": 11990, "quantity": 1, "size": "42", "color": "Чёрный",
        }])
        r = self._post("/v1/orders", body, token)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(Order.objects.filter(user_id=uid, order_id=self.oid).exists())
        # Не оплачен → на склад не уходит, баллов за покупку нет.
        self.assertNotIn(self.oid, self.onec_pull())
        self.assertEqual(self.balance(token), start)

        # Оплата (тестовая) → баллы: 1 за 10 ₽ + 50 за первый заказ.
        self.pay_test(token, self.oid)
        self.assertEqual(self.balance(token), start + 11990 // 10 + 50)
        # Повтор «Оплатить» не начисляет второй раз.
        self._post(f"/v1/orders/{self.oid}/pay", {}, token)
        self.assertEqual(self.balance(token), start + 11990 // 10 + 50)

        # 1С забирает оплаченный заказ.
        queue = self.onec_pull()
        self.assertIn(self.oid, queue, "оплаченный заказ обязан уйти в 1С")
        sent = queue[self.oid]
        self.assertIs(sent["test"], True, "тестовая оплата помечена для 1С")
        self.assertEqual(sent["paymentStatus"], "paid")
        self.assertEqual([i["article"] for i in sent["items"]], ["E2E-ART-1"])
        # Без ack заказ остаётся в очереди (связь могла оборваться).
        self.assertIn(self.oid, self.onec_pull())

        r = self._post(ONEC_ACK, {"orderIds": [self.oid]}, ONEC_TOKEN)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertNotIn(self.oid, self.onec_pull(), "после ack заказ снят с очереди")

        # 1С: принят → отгружен → доставлен.
        for status in ("accepted", "shipped", "delivered"):
            r = self._post(ONEC_STATUS, {"orders": [
                {"orderId": self.oid, "status": status, "number": "ЗК-000777"},
            ]}, ONEC_TOKEN)
            self.assertEqual(r.status_code, 200, r.content)
            self.assertEqual(r.json().get("errors") or [], [], r.content)
        order = Order.objects.get(user_id=uid, order_id=self.oid)
        self.assertEqual(order.status, "delivered")
        self.assertEqual(order.payment_status, "paid")
        return token, uid

    def test_order_paid_delivered_exported_and_account_deleted(self):
        token, uid = self._to_delivery()

        # Покупатель видит заказ.
        self.my_order(token, self.oid)

        # Выгрузка данных (152-ФЗ): там и заказ, и баллы.
        r = self._get("/v1/account/export", token)
        self.assertEqual(r.status_code, 200, r.content)
        dump = json.dumps(r.json(), ensure_ascii=False, default=str)
        self.assertIn(self.oid, dump)
        self.assertIn(uid, dump)

        # Удаление аккаунта.
        self.assertEqual(self._post("/v1/account/delete", {}, token).status_code, 400,
                         "без явного confirm аккаунт не удаляется")
        r = self._post("/v1/account/delete", {"confirm": True}, token)
        if r.status_code == 409:
            # ПОСЛЕ #822 (D-104): удалить можно только когда прошёл 7-дневный срок
            # возврата после получения. Проверяем именно это: через 8 дней — можно.
            later = timezone.now() + timedelta(days=8)
            with mock.patch("django.utils.timezone.now", return_value=later):
                r = self._post("/v1/account/delete", {"confirm": True}, token)
        self.assertEqual(r.status_code, 200, r.content)

        self.assertFalse(Account.objects.filter(id=uid).exists())
        self.assertFalse(Order.objects.filter(user_id=uid).exists())
        self.assertFalse(LoyaltyTransaction.objects.filter(user_id=uid).exists())
        # Старый токен больше ничего не открывает.
        self.assertEqual(self._get("/v1/orders", token).status_code, 401)
        self.assertEqual(self._get("/v1/loyalty/account", token).status_code, 401)
        # Тот же номер = новый пустой аккаунт, баллы прежнего не «воскресают».
        token2, uid2 = self.login()
        self.assertNotEqual(uid2, uid)
        self.assertEqual(self.balance(token2), 0)

    # Снять после #805: до него /v1/orders отдаёт payload заказа как есть — статус,
    # присланный приложением («pending»), а не пришедший из 1С (аудит B08).
    @expected_failure_until(_order_fixed_by_805())
    def test_orders_list_shows_status_from_1c(self):
        """Покупатель видит в /v1/orders статус, пришедший из 1С (аудит B08)."""
        token, _ = self._to_delivery()
        self.assertEqual(self.my_order(token, self.oid)["status"], "delivered")


@tag("e2e")
class RunPointsSpentInStoreE2E(_Journey):
    """Бег в Квартале → баллы → списание этих баллов в заказе Store."""

    phone = "+79990077002"

    def test_run_points_are_spent_in_store_order(self):
        token, uid = self.login()
        start = self.balance(token)

        # Пробежка 10 км за 60 минут, как её шлёт Квартал (completed_runs_provider).
        run = {
            "id": "run-e2e-1", "distanceMeters": 10000, "elapsedSeconds": 3600,
            "finishedAtMs": int(time.time() * 1000), "capturedTerritory": False,
            "capturedZones": 0, "mockDetected": False,
        }
        r = self._post("/v1/runs", run, token)
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertFalse(body["flagged"], body)
        self.assertEqual(body["pointsAwarded"], 100)  # 10 км × 10
        # Сразу потратить нельзя: баллы за бег созревают 3 дня.
        self.assertEqual(self.balance(token), start)
        self.three_days_pass(uid)
        after_run = self.balance(token)
        # Может добавиться веха пожизненных километров — поэтому «не меньше».
        self.assertGreaterEqual(after_run, start + 100)
        # Повтор из офлайн-очереди не начисляет второй раз.
        self._post("/v1/runs", run, token)
        self.assertEqual(self.balance(token), after_run)

        # Списываем 100 баллов в заказе на 1000 ₽ (лимит — 30% суммы, минимум 50).
        oid = "SS-E2E-RUN"
        order = self.store_order(oid, [{
            "productId": "e2e-gel", "productName": "Гель E2E",
            "price": 1000, "quantity": 1,
        }], points=100)
        r = self._post("/v1/orders", order, token)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self.balance(token), after_run - 100)
        # Повторная отправка заказа (ретрай) не списывает ещё раз.
        r = self._post("/v1/orders", order, token)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self.balance(token), after_run - 100)
        redeem = LoyaltyTransaction.objects.filter(
            user_id=uid, order_id=oid, source="redeem")
        self.assertEqual(sum(t.amount for t in redeem), -100)

        # Оплата: баллы за покупку — с суммы, которую заплатили деньгами (900 ₽).
        self.pay_test(token, oid)
        self.assertEqual(self.balance(token), after_run - 100 + 900 // 10 + 50)
        self.my_order(token, oid)

    def test_cannot_spend_more_points_than_earned(self):
        """Баллов меньше, чем хотят списать, — заказ не проходит, баланс цел."""
        token, uid = self.login()
        r = self._post("/v1/runs", {
            "id": "run-e2e-2", "distanceMeters": 6000, "elapsedSeconds": 2400,
            "finishedAtMs": int(time.time() * 1000),
        }, token)
        self.assertEqual(r.status_code, 200, r.content)
        self.three_days_pass(uid)
        have = self.balance(token)
        self.assertGreaterEqual(have, 60)

        order = self.store_order("SS-E2E-OVER", [{
            "productId": "e2e-shoe-42", "productName": "Кроссовки E2E",
            "price": 11990, "quantity": 1, "size": "42",
        }], points=have + 100)
        r = self._post("/v1/orders", order, token)
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(self.balance(token), have)
        self.assertFalse(Order.objects.filter(order_id="SS-E2E-OVER").exists())
