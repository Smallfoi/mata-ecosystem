"""Клиент не может выписать себе баллы (анти-чит S-04, продолжение).

Баллы — деньги в Store: за них берут товар. Значит начисление обязано быть
привилегией сервера, а эндпоинт транзакций — не дверью, а стеной.

Раньше здесь стоял ЧЁРНЫЙ список из четырёх источников, и он устарел молча:
Квартал 2.0 добавил награды за вехи, дивизионы и сезоны, и ни один в список не
попал. Эти тесты закрепляют БЕЛЫЙ список — новый источник запрещён по умолчанию.
"""
from common.testutils import ApiTestCase
from loyalty.models import LoyaltyTransaction


class ClientCannotMintPoints(ApiTestCase):
    """Каждый источник, которым сервер платит, должен быть закрыт для клиента."""

    phone = "+79990003001"

    def _try(self, source, amount=999999, **extra):
        return self.api_post("/v1/loyalty/transactions",
                             {"source": source, "amount": amount, **extra})

    def test_server_computed_sources_are_refused(self):
        for source in ["runnerRun", "runnerTerritory", "purchase", "registration",
                       "runnerMilestone", "runnerDivision", "runnerSeason",
                       "runnerCompetition", "manual"]:
            with self.subTest(source=source):
                self.assertEqual(self._try(source).status_code, 403)
        self.assertEqual(self.balance(), 0)

    def test_redeem_with_positive_amount_is_refused(self):
        """Списание с плюсом было бы начислением. Отдельная дыра старого списка."""
        self.assertEqual(self._try("redeem", amount=1000000).status_code, 403)
        self.assertEqual(self.balance(), 0)

    def test_invented_source_is_refused(self):
        """Смысл белого списка: неизвестное запрещено, а не разрешено."""
        for source in ["gift", "bonus", "runnerAnything", "", "  "]:
            with self.subTest(source=source):
                self.assertEqual(self._try(source).status_code, 403)
        self.assertEqual(self.balance(), 0)

    def test_no_transaction_row_is_created(self):
        """Отказ должен быть настоящим: ни одной записи в истории баллов."""
        self._try("runnerDivision")
        self._try("gift")
        self.assertFalse(LoyaltyTransaction.objects.filter(user_id=self.uid).exists())

    def test_refusal_does_not_leak_the_allowed_list(self):
        """Ответ не должен подсказывать, какой источник подобрать."""
        body = self._try("gift").json()
        self.assertNotIn("runner", str(body))


class AmountGuard(ApiTestCase):
    """Потолок на случай, если в белый список когда-нибудь что-то добавят."""

    phone = "+79990003002"

    def setUp(self):
        super().setUp()
        # Временно разрешаем один источник — проверяем, что даже он ограничен.
        from loyalty import views

        self._saved = set(views._CLIENT_ALLOWED_SOURCES)
        views._CLIENT_ALLOWED_SOURCES.add("testAllowed")

    def tearDown(self):
        from loyalty import views

        views._CLIENT_ALLOWED_SOURCES.clear()
        views._CLIENT_ALLOWED_SOURCES.update(self._saved)
        super().tearDown()

    def _try(self, amount):
        return self.api_post("/v1/loyalty/transactions",
                             {"source": "testAllowed", "amount": amount})

    def test_allowed_source_within_limit_works(self):
        self.assertEqual(self._try(100).status_code, 200)
        self.assertEqual(self.balance(), 100)

    def test_amount_over_the_cap_is_refused(self):
        from loyalty.views import MAX_CLIENT_AMOUNT

        self.assertEqual(self._try(MAX_CLIENT_AMOUNT + 1).status_code, 400)
        self.assertEqual(self.balance(), 0)

    def test_negative_and_zero_are_refused(self):
        """Минус — это списание, у него свой адрес с проверкой баланса."""
        for amount in [-100, 0]:
            with self.subTest(amount=amount):
                self.assertEqual(self._try(amount).status_code, 400)
        self.assertEqual(self.balance(), 0)

    def test_non_numeric_amount_is_refused(self):
        self.assertEqual(self._try("много").status_code, 400)
        self.assertEqual(self.balance(), 0)


class ServerStillPaysNormally(ApiTestCase):
    """Закрутив гайку, нельзя перекрыть законные начисления сервера."""

    phone = "+79990003003"

    def test_run_still_awards_points(self):
        import time

        self.api_post("/v1/runs", {
            "id": "allow_r1", "distanceMeters": 5000, "elapsedSeconds": 1800,
            "finishedAtMs": int(time.time() * 1000),
        })
        self.assertEqual(self.balance(), 50)

    def test_redeem_endpoint_still_works(self):
        import time

        self.api_post("/v1/runs", {
            "id": "allow_r2", "distanceMeters": 5000, "elapsedSeconds": 1800,
            "finishedAtMs": int(time.time() * 1000),
        })
        r = self.api_post("/v1/loyalty/redeem", {"amount": 20, "orderId": "o-1"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.balance(), 30)
