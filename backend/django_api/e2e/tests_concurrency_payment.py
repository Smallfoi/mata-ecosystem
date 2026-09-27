"""Конкурентные финансовые операции: двойное подтверждение оплаты (аудит F06, B05).

ЮKassa повторяет уведомление, если не дождалась ответа, а покупатель одновременно
жмёт «проверить оплату» — два подтверждения одного платежа приходят почти вместе.
Баллы = деньги (1 балл = 1 ₽), поэтому начисление за заказ обязано случиться ровно
один раз, как бы ни легли запросы.

Почему TransactionTestCase и потоки: в обычном TestCase всё идёт в одной транзакции
и одном соединении — гонку там не воспроизвести. Здесь у каждого потока своё
соединение с БД, как у двух воркеров gunicorn.

Детерминизм: оба потока встречаются на барьере в момент записи начисления
(`orders.awards.add_txn`). Без блокировки заказа оба к этому моменту уже решили
«ещё не начисляли» — и начисляют дважды. С блокировкой (PR #809 — `select_for_update`
в `mark_paid`; PR #810 — замок кошелька) второй поток ждёт на замке и до барьера не
доходит; барьер истекает по таймауту, первый поток дописывает и коммитит, второй
видит готовое начисление.
"""
import importlib.util
import json
import os
import threading
import unittest
from unittest import mock

from django.core.cache import cache
from django.db import connection
from django.test import Client, TransactionTestCase, tag

from loyalty.models import LoyaltyTransaction
from orders import awards, lifecycle
from orders.models import Order

WEBHOOK = "/v1/payments/webhook"
_BARRIER_TIMEOUT = 3  # сек: столько первый поток ждёт второго, если тот стоит на замке


def _double_accrual_fixed() -> bool:
    """Двойное начисление закрыто любым из двух исправлений.

    #809 (аудит B05) — переходы оплаты под блокировкой заказа (`select_for_update`);
    #810 (аудит B03) — атомарный кошелёк баллов (`loyalty.wallet`, начисление
    «один раз» под замком кошелька).
    """
    return (hasattr(lifecycle, "payment_started")
            or hasattr(lifecycle, "apply_payment_info")
            or importlib.util.find_spec("loyalty.wallet") is not None)


def expected_failure_until(fixed: bool):
    """expectedFailure, пока исправление не влито; после — обычный тест (сам снимается)."""
    def wrap(fn):
        return fn if fixed else unittest.expectedFailure(fn)
    return wrap


@tag("e2e", "concurrency")
class DoubleWebhookConcurrencyTests(TransactionTestCase):
    phone = "+79990077101"

    def setUp(self):
        cache.clear()
        env = mock.patch.dict(os.environ, {
            "DJANGO_DEBUG": "1",
            "YOOKASSA_SHOP_ID": "e2e-shop",
            "YOOKASSA_SECRET_KEY": "e2e-secret",
        })
        env.start()
        self.addCleanup(env.stop)
        for k in ("SMS_PROVIDER", "PAYMENT_PROVIDER", "SEED_DEMO_POINTS"):
            os.environ.pop(k, None)

        r = Client().post("/v1/auth/phone/verify",
                          data=json.dumps({"phone": self.phone, "code": "1234"}),
                          content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        self.uid = r.json()["user"]["id"]
        LoyaltyTransaction.objects.filter(user_id=self.uid).delete()

        self.order = Order.objects.create(
            user_id=self.uid, order_id="SS-RACE-1", total=5000, status="pending",
            payment_status="pending", payment_id="yk-race-1",
            payload={"id": "SS-RACE-1", "items": [
                {"productId": "x", "productName": "Кроссовки", "price": 5000,
                 "quantity": 1},
            ]},
        )

    def _yookassa_says_paid(self):
        """Ответ ЮKassa «платёж прошёл» — полный, чтобы его приняла и сверка суммы
        и reference из #809 (payment_mismatch)."""
        body = {
            "id": self.order.payment_id,
            "status": "succeeded",
            "paid": True,
            "amount": {"value": "5000.00", "currency": "RUB"},
            "metadata": {"order_id": self.order.order_id,
                         "reference": f"{self.order.order_id}-{self.order.pk}"},
        }
        return mock.patch("orders.payment._http", return_value=body)

    @expected_failure_until(_double_accrual_fixed())
    # Снять после #809 (или #810): на текущем main mark_paid не блокирует заказ, и
    # два одновременных подтверждения начисляют баллы за покупку дважды.
    def test_two_simultaneous_webhooks_accrue_points_once(self):
        barrier = threading.Barrier(2, timeout=_BARRIER_TIMEOUT)
        real_add_txn = awards.add_txn

        def add_txn_at_barrier(*args, **kwargs):
            try:
                barrier.wait()
            except threading.BrokenBarrierError:
                pass  # второй поток ждёт на замке — это и есть правильное поведение
            return real_add_txn(*args, **kwargs)

        answers, errors = [], []

        def webhook():
            try:
                r = Client().post(WEBHOOK,
                                  data=json.dumps({"event": "payment.succeeded",
                                                   "object": {"id": "yk-race-1"}}),
                                  content_type="application/json")
                answers.append(r.status_code)
            except Exception as e:  # noqa: BLE001 — ошибку потока показываем в тесте
                errors.append(repr(e))
            finally:
                connection.close()  # у каждого потока своё соединение

        with self._yookassa_says_paid(), \
                mock.patch.object(awards, "add_txn", side_effect=add_txn_at_barrier):
            threads = [threading.Thread(target=webhook) for _ in range(2)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=30)

        self.assertEqual(errors, [])
        self.assertEqual(answers, [200, 200])
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, "paid")

        purchase = LoyaltyTransaction.objects.filter(
            user_id=self.uid, order_id=self.order.order_id, source="purchase")
        self.assertEqual(purchase.count(), 1, "баллы за покупку начислены не один раз")
        bonus = LoyaltyTransaction.objects.filter(user_id=self.uid, source="registration")
        self.assertEqual(bonus.count(), 1, "бонус за первый заказ начислен не один раз")
        total = sum(t.amount for t in LoyaltyTransaction.objects.filter(user_id=self.uid))
        self.assertEqual(total, 5000 // 10 + 50)

    def test_sequential_repeat_webhook_is_idempotent(self):
        """Контроль без гонки: повтор уведомления после первого ничего не добавляет."""
        with self._yookassa_says_paid():
            for _ in range(2):
                r = Client().post(WEBHOOK,
                                  data=json.dumps({"object": {"id": "yk-race-1"}}),
                                  content_type="application/json")
                self.assertEqual(r.status_code, 200, r.content)
        total = sum(t.amount for t in LoyaltyTransaction.objects.filter(user_id=self.uid))
        self.assertEqual(total, 5000 // 10 + 50)
