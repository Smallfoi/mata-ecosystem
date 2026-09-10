"""Регрессии начисления за покупку (S-04 Phase 2) + оплата ЮKassa."""
import json
import os
from unittest import mock

from common.testutils import ApiTestCase
from orders.models import Order
from orders.payment import PaymentError, payment_enabled

# Боевой режим оплаты: провайдер + ключи магазина. Сеть в тестах не трогаем —
# подменяется orders.payment._http (единственная точка сетевого ввода-вывода).
_YK_ENV = {
    "PAYMENT_PROVIDER": "yookassa",
    "YOOKASSA_SHOP_ID": "654321",
    "YOOKASSA_SECRET_KEY": "test_secret_key",
    "YOOKASSA_RETURN_URL": "https://example.test/orders",
}


def _yk(status="pending", pid="pay_1", url="https://yoomoney.ru/checkout/pay_1"):
    """Ответ ЮKassa в формате API v3."""
    return {"id": pid, "status": status, "confirmation": {"confirmation_url": url}}


class PaymentScaffoldTests(ApiTestCase):
    phone = "+79990002003"

    def test_dev_pay_marks_paid(self):
        self.assertFalse(payment_enabled())
        self.api_post("/v1/orders", {"id": "SS-P1", "total": 500, "items": []})
        r = self.api_post("/v1/orders/SS-P1/pay", {})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "paid")  # dev — оплата не требуется

    def test_pay_unknown_order_404(self):
        self.assertEqual(self.api_post("/v1/orders/NOPE/pay", {}).status_code, 404)

    @mock.patch.dict(os.environ, {"PAYMENT_PROVIDER": "yookassa"})
    def test_provider_mode_without_keys_is_502_not_silent_pending(self):
        """Провайдер включён, а ключей нет — это ошибка конфигурации, и она должна
        быть громкой. Молчаливый «pending» с пустой ссылкой = заказ, который
        покупатель не может оплатить, и никто об этом не узнает."""
        self.assertTrue(payment_enabled())
        self.api_post("/v1/orders", {"id": "SS-P2", "total": 500, "items": []})
        r = self.api_post("/v1/orders/SS-P2/pay", {})
        self.assertEqual(r.status_code, 502)


class YooKassaPaymentTests(ApiTestCase):
    """Боевой режим оплаты: создание платежа, вебхук, привязка баллов к оплате."""
    phone = "+79990002007"

    def _order(self, oid, total=1000):
        self.api_post("/v1/orders", {"id": oid, "total": total, "items": []})

    def _webhook(self, payment_id, event="payment.succeeded"):
        """Вебхук приходит БЕЗ токена — эндпоинт публичный."""
        return self.client.post(
            "/v1/payments/webhook",
            data=json.dumps({"event": event, "object": {"id": payment_id}}),
            content_type="application/json",
        )

    @mock.patch.dict(os.environ, _YK_ENV)
    @mock.patch("orders.payment._http")
    def test_creates_payment_and_returns_confirmation_url(self, http):
        http.return_value = _yk()
        self._order("SS-Y1", total=500)
        r = self.api_post("/v1/orders/SS-Y1/pay", {"returnUrl": "https://example.test/ok"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["confirmationUrl"], "https://yoomoney.ru/checkout/pay_1")
        self.assertEqual(r.json()["status"], "pending")

        method, url, payload, headers = http.call_args[0]
        self.assertEqual(method, "POST")
        self.assertTrue(url.endswith("/payments"))
        self.assertEqual(payload["amount"], {"value": "500.00", "currency": "RUB"})
        self.assertEqual(payload["confirmation"]["return_url"], "https://example.test/ok")
        self.assertTrue(headers["Authorization"].startswith("Basic "))
        self.assertIn("Idempotence-Key", headers)  # защита от двойного списания

    @mock.patch.dict(os.environ, _YK_ENV)
    @mock.patch("orders.payment._http")
    def test_same_order_reuses_idempotence_key(self, http):
        http.return_value = _yk()
        self._order("SS-Y2", total=700)
        self.api_post("/v1/orders/SS-Y2/pay", {})
        self.api_post("/v1/orders/SS-Y2/pay", {})
        keys = [c[0][3]["Idempotence-Key"] for c in http.call_args_list]
        self.assertEqual(keys[0], keys[1])  # повтор «Оплатить» → тот же платёж

    @mock.patch.dict(os.environ, _YK_ENV)
    @mock.patch("orders.payment._http")
    def test_provider_failure_keeps_order_unpaid(self, http):
        """ЮKassa не ответила — заказ остаётся «ждёт оплату».

        Раньше здесь проверялось «none», и тест закреплял дыру: «none» выглядит
        как «не оплачен», а означает «оплата не требуется» — такой заказ обмен
        с 1С забирает на сборку.
        """
        http.side_effect = PaymentError("ЮKassa 500: internal")
        self._order("SS-Y3")
        r = self.api_post("/v1/orders/SS-Y3/pay", {})
        self.assertEqual(r.status_code, 502)
        self.assertEqual(Order.objects.get(order_id="SS-Y3").payment_status, "pending")

    @mock.patch.dict(os.environ, _YK_ENV)
    @mock.patch("orders.payment._http")
    def test_points_wait_for_confirmed_payment(self, http):
        """Ключевая защита: баллы = деньги, за неоплаченный заказ их быть не должно."""
        http.return_value = _yk()
        self._order("SS-Y4", total=1000)
        self.assertEqual(self.balance(), 0)

        self.api_post("/v1/orders/SS-Y4/pay", {})
        self.assertEqual(self.balance(), 0)  # ссылка выдана, деньги ещё не пришли

        http.return_value = _yk(status="succeeded")
        self.assertEqual(self._webhook("pay_1").status_code, 200)
        self.assertEqual(self.balance(), 150)  # 100 за сумму + 50 за первый заказ

    @mock.patch.dict(os.environ, _YK_ENV)
    @mock.patch("orders.payment._http")
    def test_webhook_repeat_does_not_double_points(self, http):
        http.return_value = _yk()
        self._order("SS-Y5", total=1000)
        self.api_post("/v1/orders/SS-Y5/pay", {})
        http.return_value = _yk(status="succeeded")
        self._webhook("pay_1")
        self._webhook("pay_1")  # ЮKassa повторяет доставку при сбоях
        self.assertEqual(self.balance(), 150)
        self.assertEqual(Order.objects.get(order_id="SS-Y5").payment_status, "paid")

    @mock.patch.dict(os.environ, _YK_ENV)
    @mock.patch("orders.payment._http")
    def test_forged_webhook_cannot_mark_paid(self, http):
        """Тело вебхука не подписано: злоумышленник шлёт «succeeded» на наш публичный
        адрес. Верим только ответу API по нашим ключам — заказ оплаченным не станет."""
        http.return_value = _yk()
        self._order("SS-Y6", total=1000)
        self.api_post("/v1/orders/SS-Y6/pay", {})

        http.return_value = _yk(status="pending")  # правда от API: не оплачен
        self._webhook("pay_1", event="payment.succeeded")  # ложь в теле
        self.assertEqual(Order.objects.get(order_id="SS-Y6").payment_status, "pending")
        self.assertEqual(self.balance(), 0)

    @mock.patch.dict(os.environ, _YK_ENV)
    @mock.patch("orders.payment._http")
    def test_canceled_payment_returns_redeemed_points(self, http):
        from loyalty.models import add_txn

        http.return_value = _yk()
        self._order("SS-Y7", total=1000)
        add_txn(self.uid, 300, "run", "Баллы за бег")
        add_txn(self.uid, -100, "redeem", "Оплата баллами", "SS-Y7")
        self.assertEqual(self.balance(), 200)

        self.api_post("/v1/orders/SS-Y7/pay", {})
        http.return_value = _yk(status="canceled")
        self._webhook("pay_1", event="payment.canceled")
        self.assertEqual(self.balance(), 300)  # списанные баллы вернулись
        self._webhook("pay_1", event="payment.canceled")
        self.assertEqual(self.balance(), 300)  # повтор не начисляет второй раз

    @mock.patch.dict(os.environ, _YK_ENV)
    @mock.patch("orders.payment._http")
    def test_webhook_for_unknown_payment_is_404(self, http):
        http.return_value = _yk(status="succeeded", pid="pay_stranger")
        self.assertEqual(self._webhook("pay_stranger").status_code, 404)

    def test_webhook_without_payment_id_is_400(self):
        r = self.client.post(
            "/v1/payments/webhook", data=json.dumps({}), content_type="application/json"
        )
        self.assertEqual(r.status_code, 400)


class OrderAwardTests(ApiTestCase):
    phone = "+79990002002"

    def test_first_order_awards_purchase_and_registration(self):
        self.api_post("/v1/orders", {"id": "SS-1", "total": 1000, "items": []})
        self.assertEqual(self.balance(), 150)  # 100 (1000/10) + 50 (первый заказ)

    def test_duplicate_order_no_double(self):
        self.api_post("/v1/orders", {"id": "SS-1", "total": 1000, "items": []})
        self.api_post("/v1/orders", {"id": "SS-1", "total": 1000, "items": []})
        self.assertEqual(self.balance(), 150)

    def test_second_order_no_registration_bonus(self):
        self.api_post("/v1/orders", {"id": "SS-1", "total": 1000, "items": []})  # 150
        self.api_post("/v1/orders", {"id": "SS-2", "total": 500, "items": []})   # +50
        self.assertEqual(self.balance(), 200)

    def test_client_cannot_mint_purchase_or_registration(self):
        for src in ("purchase", "registration"):
            r = self.api_post(
                "/v1/loyalty/transactions",
                {"amount": 9999, "source": src, "orderId": "x"},
            )
            self.assertEqual(r.status_code, 403)
        self.assertEqual(self.balance(), 0)


class OrderCheckoutTests(ApiTestCase):
    """Edge-кейсы чекаута: валидация id, изоляция/порядок ленты, мелкий заказ,
    повторный POST (обновление без задвоения), требование токена."""
    phone = "+79990002006"

    def test_missing_id_rejected(self):
        self.assertEqual(self.api_post("/v1/orders", {"total": 100}).status_code, 400)

    def test_get_lists_only_own_newest_first(self):
        from datetime import timedelta

        from django.utils import timezone

        from orders.models import Order

        self.api_post("/v1/orders", {"id": "old", "total": 100, "items": []})
        self.api_post("/v1/orders", {"id": "new", "total": 100, "items": []})
        # Детерминированно разводим по времени (иначе одинаковый created_at → неустойчивый порядок).
        Order.objects.filter(user_id=self.uid, order_id="old").update(
            created_at=timezone.now() - timedelta(hours=1)
        )
        Order.objects.create(
            user_id="u_stranger", order_id="x", total=100, payload={"id": "x"}
        )  # чужой — не должен попасть в ленту
        ids = [o["id"] for o in self.api_get("/v1/orders").json()]
        self.assertEqual(ids, ["new", "old"])

    def test_tiny_order_registration_but_no_purchase_points(self):
        # total=5 ₽: 5//10=0 покупочных баллов, но первый заказ → +50 регистрационных.
        self.api_post("/v1/orders", {"id": "SS-T", "total": 5, "items": []})
        self.assertEqual(self.balance(), 50)

    def test_repeat_post_updates_status_without_reaward(self):
        self.api_post(
            "/v1/orders", {"id": "SS-U", "total": 1000, "status": "pending", "items": []}
        )
        self.assertEqual(self.balance(), 150)  # 100 + 50
        self.api_post(
            "/v1/orders", {"id": "SS-U", "total": 1000, "status": "shipped", "items": []}
        )
        self.assertEqual(self.balance(), 150)  # повтор не задваивает баллы
        from orders.models import Order

        self.assertEqual(
            Order.objects.get(user_id=self.uid, order_id="SS-U").status, "shipped"
        )  # статус обновился

    def test_orders_require_auth(self):
        self.assertEqual(self.client.get("/v1/orders").status_code, 401)
        self.assertEqual(self.client.post("/v1/orders").status_code, 401)


class OrderTotalIntegrityTests(ApiTestCase):
    """Сумму заказа присылает клиент — сервер обязан сверить её с каталогом (D-37)."""
    phone = "+79990002008"

    def setUp(self):
        super().setUp()
        from catalog.models import Product

        Product.objects.create(id="p-jacket", name="Куртка", category_id="wear", price=5000)
        Product.objects.create(id="p-socks", name="Носки", category_id="wear", price=500)

    def _order(self, oid, total, items):
        return self.api_post("/v1/orders", {"id": oid, "total": total, "items": items})

    def test_understated_total_rejected(self):
        """Корзина на 5000 ₽ с заявленной суммой 1 ₽ — отказ, а не рубль за куртку."""
        r = self._order("SS-T1", 1, [{"productId": "p-jacket", "quantity": 1}])
        self.assertEqual(r.status_code, 400)
        self.assertFalse(Order.objects.filter(order_id="SS-T1").exists())

    def test_correct_total_accepted(self):
        r = self._order("SS-T2", 5500, [
            {"productId": "p-jacket", "quantity": 1},
            {"productId": "p-socks", "quantity": 1},
        ])
        self.assertEqual(r.status_code, 200)

    def test_total_above_goods_accepted_delivery_adds_up(self):
        """Сверху к товарам идёт доставка — превышение суммы законно."""
        self.assertEqual(
            self._order("SS-T3", 5400, [{"productId": "p-jacket", "quantity": 1}]).status_code,
            200,
        )

    def test_quantity_counted(self):
        r = self._order("SS-T4", 5000, [{"productId": "p-jacket", "quantity": 3}])
        self.assertEqual(r.status_code, 400)  # три куртки — это 15 000, а не 5 000

    def test_redeemed_points_lower_the_minimum(self):
        """Списанные баллы уменьшают порог — но по реестру, а не по словам клиента."""
        from loyalty.models import add_txn

        add_txn(self.uid, 2000, "run", "Баллы за бег")
        add_txn(self.uid, -1000, "redeem", "Оплата баллами", "SS-T5")
        r = self._order("SS-T5", 4000, [{"productId": "p-jacket", "quantity": 1}])
        self.assertEqual(r.status_code, 200)

    def test_claimed_points_do_not_lower_the_minimum(self):
        """Заявить «списал 5000 баллов» без реального списания нельзя."""
        r = self.api_post("/v1/orders", {
            "id": "SS-T6", "total": 1, "pointsRedeemed": 5000,
            "items": [{"productId": "p-jacket", "quantity": 1}],
        })
        self.assertEqual(r.status_code, 400)

    def test_unknown_items_do_not_block_order(self):
        """Товара нет в каталоге — сверять не с чем, заказ не блокируем."""
        r = self._order("SS-T7", 100, [{"productId": "нет-такого", "quantity": 1}])
        self.assertEqual(r.status_code, 200)


class PaymentReferenceTests(ApiTestCase):
    """Номер заказа для провайдера должен быть уникален глобально.

    `order_id` уникален только в паре с пользователем. Пока ключ идемпотентности
    считался от него, двое покупателей с одинаковым «SS-…» и равной суммой получали
    ОДИН платёж на двоих: второму возвращалась чужая ссылка на оплату.
    """

    phone = "+79990002011"

    @mock.patch.dict(os.environ, _YK_ENV)
    def test_same_order_id_from_two_users_gives_two_payments(self):
        seen = []

        def fake_http(method, url, payload=None, headers=None):
            seen.append((headers or {}).get("Idempotence-Key"))
            return _yk(pid=f"pay_{len(seen)}")

        with mock.patch("orders.payment._http", side_effect=fake_http):
            self.api_post("/v1/orders", {"id": "SS-SAME", "total": 1000, "items": []})
            self.api_post("/v1/orders/SS-SAME/pay", {})

            # Второй покупатель с тем же номером заказа и той же суммой.
            other = self.new_user("+79990002012")
            self.api_post(
                "/v1/orders", {"id": "SS-SAME", "total": 1000, "items": []}, token=other
            )
            self.api_post("/v1/orders/SS-SAME/pay", {}, token=other)

        self.assertEqual(len(seen), 2)
        self.assertNotEqual(seen[0], seen[1], "ключ идемпотентности совпал у двух заказов")

    @mock.patch.dict(os.environ, _YK_ENV)
    def test_repeat_pay_of_same_order_keeps_one_payment(self):
        """Обратная сторона: повтор «Оплатить» по СВОЕМУ заказу — тот же ключ."""
        seen = []

        def fake_http(method, url, payload=None, headers=None):
            seen.append((headers or {}).get("Idempotence-Key"))
            return _yk()

        with mock.patch("orders.payment._http", side_effect=fake_http):
            self.api_post("/v1/orders", {"id": "SS-REP", "total": 700, "items": []})
            self.api_post("/v1/orders/SS-REP/pay", {})
            self.api_post("/v1/orders/SS-REP/pay", {})

        self.assertEqual(seen[0], seen[1])

    @mock.patch.dict(os.environ, _YK_ENV)
    def test_reference_goes_to_provider_metadata(self):
        bodies = []

        def fake_http(method, url, payload=None, headers=None):
            bodies.append(payload)
            return _yk()

        with mock.patch("orders.payment._http", side_effect=fake_http):
            self.api_post("/v1/orders", {"id": "SS-META", "total": 300, "items": []})
            self.api_post("/v1/orders/SS-META/pay", {})

        meta = bodies[0]["metadata"]
        self.assertEqual(meta["order_id"], "SS-META")
        self.assertTrue(meta["reference"].startswith("SS-META-"), meta["reference"])


class PaymentMethodTests(ApiTestCase):
    """Способ оплаты: по умолчанию СБП (решение владельца — карты не подключаем)."""

    phone = "+79990002015"

    def _pay(self, oid="SS-M1", body=None):
        bodies = []

        def fake_http(method, url, payload=None, headers=None):
            bodies.append(payload)
            return _yk()

        with mock.patch("orders.payment._http", side_effect=fake_http):
            self.api_post("/v1/orders", {"id": oid, "total": 500, "items": []})
            self.api_post(f"/v1/orders/{oid}/pay", body or {})
        return bodies[0]

    @mock.patch.dict(os.environ, _YK_ENV)
    def test_sbp_by_default(self):
        self.assertEqual(self._pay()["payment_method_data"], {"type": "sbp"})

    @mock.patch.dict(os.environ, dict(_YK_ENV, PAYMENT_METHOD="any"))
    def test_any_lets_provider_show_all_methods(self):
        """«any» — показать все способы из кабинета: пригодится, когда включим карты."""
        self.assertNotIn("payment_method_data", self._pay(oid="SS-M2"))

    @mock.patch.dict(os.environ, _YK_ENV)
    def test_request_can_override_method(self):
        body = self._pay(oid="SS-M3", body={"method": "bank_card"})
        self.assertEqual(body["payment_method_data"], {"type": "bank_card"})


class ReceiptTests(ApiTestCase):
    """Состав чека по 54-ФЗ. Чек обязателен и при оплате по СБП."""

    phone = "+79990002016"

    PAYLOAD = {
        "items": [
            {"productName": "Худи МАТА", "size": "L", "price": 4000.0, "quantity": 2},
            {"productName": "Кепка", "price": 1500.0, "quantity": 1},
        ],
        "deliveryCost": 300.0,
        "checkoutData": {"email": "buyer@example.test", "phone": "+79148278470"},
    }

    def test_disabled_by_default(self):
        """Пока касса не подключена, чек не передаём — иначе платёж не создастся."""
        from orders.receipt import build_receipt

        self.assertIsNone(build_receipt(self.PAYLOAD, 9800))

    @mock.patch.dict(os.environ, {"PAYMENT_RECEIPT": "1"})
    def test_items_sum_equals_payment_amount(self):
        """Главное требование кассы: позиции сходятся с суммой платежа до копейки."""
        from orders.receipt import build_receipt

        receipt = build_receipt(self.PAYLOAD, 9800)  # 4000×2 + 1500 + 300
        total = sum(float(i["amount"]["value"]) for i in receipt["items"])
        self.assertAlmostEqual(total, 9800.0, places=2)
        self.assertEqual(receipt["items"][-1]["description"], "Доставка")

    @mock.patch.dict(os.environ, {"PAYMENT_RECEIPT": "1"})
    def test_points_discount_is_absorbed_by_last_item(self):
        """Списали 800 баллов — сумма позиций всё равно обязана сойтись с платежом."""
        from orders.receipt import build_receipt

        receipt = build_receipt(self.PAYLOAD, 9000)
        total = sum(float(i["amount"]["value"]) for i in receipt["items"])
        self.assertAlmostEqual(total, 9000.0, places=2)

    @mock.patch.dict(os.environ, {"PAYMENT_RECEIPT": "1"})
    def test_sum_is_exact_on_ugly_numbers(self):
        """Три одинаковые вещи и скидка, которая на три не делится."""
        from orders.receipt import build_receipt

        payload = {
            "items": [{"productName": "Футболка", "price": 1000.0, "quantity": 3}],
            "checkoutData": {"email": "b@example.test"},
        }
        receipt = build_receipt(payload, 2000.01)
        kop = sum(round(float(i["amount"]["value"]) * 100) for i in receipt["items"])
        self.assertEqual(kop, 200001)
        self.assertEqual(len(receipt["items"]), 3, "каждая единица — своя позиция")

    @mock.patch.dict(os.environ, {"PAYMENT_RECEIPT": "1"})
    def test_no_contact_is_an_error_not_a_silent_skip(self):
        from orders.receipt import build_receipt

        payload = dict(self.PAYLOAD, checkoutData={})
        with self.assertRaises(ValueError):
            build_receipt(payload, 9800)

    @mock.patch.dict(os.environ, {"PAYMENT_RECEIPT": "1"})
    def test_marked_goods_carry_the_code(self):
        """Одежда и обувь маркируются: код из заказа обязан уйти в позицию чека."""
        from orders.receipt import build_receipt

        payload = dict(self.PAYLOAD)
        payload["items"] = [dict(self.PAYLOAD["items"][0], markCode="010463003...")]
        payload["deliveryCost"] = 0
        receipt = build_receipt(payload, 8000)
        self.assertEqual(receipt["items"][0]["mark_code_info"]["gs_1m"], "010463003...")

    @mock.patch.dict(os.environ, dict(_YK_ENV, PAYMENT_RECEIPT="1"))
    def test_order_without_contact_fails_loudly_on_pay(self):
        """Лучше 400 с понятным текстом, чем платёж, который отвергнет касса."""
        self.api_post("/v1/orders", {"id": "SS-R1", "total": 500, "items": []})
        r = self.api_post("/v1/orders/SS-R1/pay", {})
        self.assertEqual(r.status_code, 400)
        self.assertIn("чек", r.json()["detail"].lower())


class PaymentStateTests(ApiTestCase):
    """Статус оплаты с перепроверкой — страховка от потерянного вебхука."""

    phone = "+79990002017"

    @mock.patch.dict(os.environ, _YK_ENV)
    def test_lost_webhook_is_recovered_on_status_request(self):
        with mock.patch("orders.payment._http", return_value=_yk()):
            self.api_post("/v1/orders", {"id": "SS-S1", "total": 1000, "items": []})
            self.api_post("/v1/orders/SS-S1/pay", {})

        # Вебхук не дошёл: заказ висит в «ждёт оплаты», хотя деньги списаны.
        self.assertEqual(Order.objects.get(order_id="SS-S1").payment_status, "pending")

        with mock.patch("orders.payment._http", return_value=_yk(status="succeeded")):
            r = self.api_get("/v1/orders/SS-S1/payment")

        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "paid")
        self.assertGreater(self.balance(), 0, "баллы за покупку не начислены")

    @mock.patch.dict(os.environ, _YK_ENV)
    def test_provider_down_does_not_break_the_answer(self):
        with mock.patch("orders.payment._http", return_value=_yk()):
            self.api_post("/v1/orders", {"id": "SS-S2", "total": 100, "items": []})
            self.api_post("/v1/orders/SS-S2/pay", {})

        with mock.patch("orders.payment._http", side_effect=PaymentError("нет связи")):
            r = self.api_get("/v1/orders/SS-S2/payment")

        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "pending")

    def test_unknown_order_404(self):
        self.assertEqual(self.api_get("/v1/orders/NOPE/payment").status_code, 404)


class RefundPointsTests(ApiTestCase):
    """Вернули деньги — начисленные за покупку баллы обязаны уйти."""

    phone = "+79990002018"

    def test_purchase_points_are_revoked_once(self):
        from orders.awards import accrue_purchase_points, revoke_purchase_points

        self.api_post("/v1/orders", {"id": "SS-RF", "total": 1000, "items": []})
        order = Order.objects.get(user_id=self.uid, order_id="SS-RF")
        accrue_purchase_points(order)  # идемпотентно: заказ уже начислил при создании
        earned = self.balance()
        self.assertGreater(earned, 0)

        revoke_purchase_points(order)
        after = self.balance()
        self.assertLess(after, earned)

        revoke_purchase_points(order)  # повтор не должен снимать второй раз
        self.assertEqual(self.balance(), after)


class PaymentStatusAtBirthTests(ApiTestCase):
    """С каким статусом оплаты рождается заказ (найдено 10.09.2026).

    Раньше каждый заказ создавался со статусом «none» — «оплата не требуется». Обмен
    с 1С забирает такие заказы на сборку, и при включённой оплате заказ уезжал на
    склад между оформлением и /pay, а брошенный — неоплаченным навсегда.
    """
    phone = "+79990002091"

    def _order(self, oid, pay_type=None):
        body = {"id": oid, "total": 500, "items": []}
        if pay_type:
            body["checkoutData"] = {"paymentType": pay_type}
        self.assertEqual(self.api_post("/v1/orders", body).status_code, 200)
        return Order.objects.get(user_id=self.uid, order_id=oid)

    @mock.patch.dict(os.environ, _YK_ENV)
    def test_online_order_waits_for_payment(self):
        self.assertEqual(self._order("SS-B1", "sbp").payment_status, "pending")
        self.assertEqual(self._order("SS-B2", "card").payment_status, "pending")

    @mock.patch.dict(os.environ, _YK_ENV)
    def test_order_without_payment_type_waits_for_payment(self):
        """Способ не указан — придерживаем: безопаснее, чем отдать на сборку."""
        self.assertEqual(self._order("SS-B3").payment_status, "pending")

    @mock.patch.dict(os.environ, _YK_ENV)
    def test_pay_on_delivery_needs_no_online_payment(self):
        """Store шлёт `cash`, сайт — `cod`: деньги возьмут при получении."""
        self.assertEqual(self._order("SS-B4", "cash").payment_status, "none")
        self.assertEqual(self._order("SS-B5", "cod").payment_status, "none")

    def test_dev_mode_needs_no_payment(self):
        self.assertEqual(self._order("SS-B6", "sbp").payment_status, "none")

    @mock.patch.dict(os.environ, _YK_ENV)
    def test_resubmit_does_not_unpay_paid_order(self):
        """Клиент повторил отправку — оплаченный заказ остаётся оплаченным."""
        self._order("SS-B7", "sbp")
        Order.objects.filter(user_id=self.uid, order_id="SS-B7").update(payment_status="paid")
        self.assertEqual(self._order("SS-B7", "sbp").payment_status, "paid")

    @mock.patch.dict(os.environ, _YK_ENV)
    @mock.patch("orders.payment._http")
    def test_pay_on_delivery_does_not_open_online_payment(self, http):
        """Выбрал «при получении» — на страницу СБП не отправляем."""
        self._order("SS-B8", "cash")
        r = self.api_post("/v1/orders/SS-B8/pay", {})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "none")
        self.assertEqual(r.json()["confirmationUrl"], "")
        http.assert_not_called()
