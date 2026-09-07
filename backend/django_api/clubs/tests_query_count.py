"""Число запросов к базе на страницах клубов (нагрузочная проверка 08.09.2026).

Почему тест именно на ЧИСЛО запросов, а не на время. Время на ноутбуке ничего
не говорит о проде и плавает от прогона к прогону. Число запросов одинаково
везде и растёт вместе с данными — по нему видно ровно то, что убивает сервер
под нагрузкой.

Что было: `/v1/clubs` делал запрос на КАЖДОГО участника КАЖДОГО клуба. На
измеренном объёме (60 клубов, 5000 участников) это 5061 запрос и 1.9 секунды
на страницу. При трёх воркерах прода несколько таких запросов заняли бы весь
сервер, и приложение встало бы для всех.

Стало: 3 запроса, 42 мс. Тесты ниже держат эту границу.
"""
from django.test import TestCase

from accounts.models import Account
from clubs.models import Club, ClubMember
from common.security import make_token
from loyalty.models import LoyaltyTransaction


class ClubsListStaysFlat(TestCase):
    """Число запросов не должно расти вместе с числом клубов и участников."""

    CLUBS = 5
    PER_CLUB = 10

    def setUp(self):
        self.uid = "q_owner"
        Account.objects.create(id=self.uid, email="q@t.dev", name="Хозяин")
        self.token = make_token(self.uid)
        for c in range(self.CLUBS):
            Club.objects.create(id=f"qc_{c}", name=f"Клуб {c}", owner_id=self.uid)
            for m in range(self.PER_CLUB):
                uid = f"qu_{c}_{m}"
                Account.objects.create(id=uid, email=f"{uid}@t.dev", name=f"Бегун {m}")
                ClubMember.objects.create(club_id=f"qc_{c}", user_id=uid, role="member")
                LoyaltyTransaction.objects.create(
                    id=f"qt_{c}_{m}", user_id=uid, amount=100, source="runnerRun",
                )

    def _get(self, path):
        return self.client.get(path, HTTP_AUTHORIZATION=f"Bearer {self.token}")

    def _warm(self, path):
        """Прогрев: проверка «аккаунт не заблокирован» кэшируется, и первый
        вызов делает на один запрос больше. Без прогрева тест мерил бы разницу
        холодного и тёплого кэша, а не число запросов страницы."""
        self._get(path)

    def test_clubs_list_is_a_handful_of_queries(self):
        """Раньше здесь был запрос на каждого из 50 участников."""
        self._warm("/v1/clubs")
        with self.assertNumQueries(3):
            r = self._get("/v1/clubs")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()), self.CLUBS)

    def test_adding_clubs_does_not_add_queries(self):
        """Главная проверка: удвоили данные — число запросов то же."""
        self._warm("/v1/clubs")
        before = len(self._queries_for("/v1/clubs"))
        for c in range(self.CLUBS, self.CLUBS * 2):
            Club.objects.create(id=f"qc_{c}", name=f"Клуб {c}", owner_id=self.uid)
            for m in range(self.PER_CLUB):
                uid = f"qu2_{c}_{m}"
                Account.objects.create(id=uid, email=f"{uid}@t.dev", name="Бегун")
                ClubMember.objects.create(club_id=f"qc_{c}", user_id=uid, role="member")
        after = len(self._queries_for("/v1/clubs"))
        self.assertEqual(before, after,
                         "число запросов выросло вместе с данными — вернулся N+1")

    def test_club_totals_are_correct_after_the_rewrite(self):
        """Оптимизация не должна поменять цифры: 10 человек × 100 баллов = 100 км."""
        rows = {c["id"]: c for c in self._get("/v1/clubs").json()}
        self.assertEqual(rows["qc_0"]["totalKm"], 100.0)
        self.assertEqual(rows["qc_0"]["memberCount"], self.PER_CLUB)

    def _queries_for(self, path):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as ctx:
            self._get(path)
        return ctx.captured_queries


class ClubDetailStaysFlat(TestCase):
    """Карточка клуба: вклад участников тоже считался по одному."""

    def setUp(self):
        self.uid = "d_owner"
        Account.objects.create(id=self.uid, email="d@t.dev", name="Хозяин")
        self.token = make_token(self.uid)
        Club.objects.create(id="dc_1", name="Клуб", owner_id=self.uid)
        ClubMember.objects.create(club_id="dc_1", user_id=self.uid, role="owner")
        for m in range(15):
            uid = f"du_{m}"
            Account.objects.create(id=uid, email=f"{uid}@t.dev", name=f"Бегун {m}")
            ClubMember.objects.create(club_id="dc_1", user_id=uid, role="member")
            LoyaltyTransaction.objects.create(
                id=f"dt_{m}", user_id=uid, amount=50, source="runnerRun",
            )

    def test_members_are_fetched_in_bulk(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        # Прогрев кэша проверки аккаунта — см. пояснение выше.
        self.client.get("/v1/clubs/dc_1", HTTP_AUTHORIZATION=f"Bearer {self.token}")
        with CaptureQueriesContext(connection) as ctx:
            r = self.client.get("/v1/clubs/dc_1",
                                HTTP_AUTHORIZATION=f"Bearer {self.token}")
        self.assertEqual(r.status_code, 200)
        # 16 участников: раньше это было бы за тридцать запросов (имя + километры
        # на каждого). Порог с запасом, но заведомо ниже «по два на человека».
        self.assertLess(len(ctx.captured_queries), 15,
                        "карточка клуба снова ходит в базу за каждым участником")
        self.assertEqual(len(r.json()["members"]), 16)
