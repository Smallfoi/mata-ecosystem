"""Суточный потолок захватов территории (анти-чит S-04, аудит 08.09.2026).

Почему одного кулдауна мало. Кулдаун в 30 секунд ограничивает ТЕМП, но не сумму:
за сутки это 2880 захватов по 50 баллов — 144 000 баллов из воздуха, а баллы
покупают товар в Store.

Полагаться на проверку скорости тоже нельзя: она срабатывает, только если клиент
САМ прислал дистанцию и время. Не прислал — проверки нет. Потолок работает
независимо от того, что клиент решил о себе сообщить, и в этом его смысл.
"""
from datetime import timedelta

from django.utils import timezone

from common.testutils import ApiTestCase
from loyalty.models import LoyaltyTransaction
from territories.views import MAX_CAPTURES_PER_DAY, TERRITORY_POINTS


class DailyCaptureCap(ApiTestCase):
    phone = "+79990004001"

    def _award(self, n, when=None):
        """Проставить n уже начисленных захватов (быстрее, чем гонять геометрию)."""
        created = when or timezone.now()
        for i in range(n):
            LoyaltyTransaction.objects.create(
                id=f"tx_cap_{i}_{created.timestamp()}",
                user_id=self.uid, amount=TERRITORY_POINTS,
                source="runnerTerritory", run_id=f"cap-{i}", created_at=created,
            )

    def _capture(self):
        """Квадрат примерно 150×150 м — заведомо больше минимальной площади."""
        pts = [[62.0, 129.70], [62.0, 129.7030], [62.0014, 129.7030], [62.0014, 129.70]]
        return self.api_post("/v1/territories/capture",
                             {"points": pts, "captureId": f"c-{timezone.now().timestamp()}"})

    def test_cap_blocks_when_reached(self):
        self._award(MAX_CAPTURES_PER_DAY)
        r = self._capture()
        self.assertEqual(r.status_code, 429)

    def test_below_cap_still_allowed(self):
        self._award(MAX_CAPTURES_PER_DAY - 1)
        self.assertNotEqual(self._capture().status_code, 429)

    def test_yesterday_does_not_count(self):
        """Окно скользящее: вчерашние захваты не должны блокировать сегодня."""
        self._award(MAX_CAPTURES_PER_DAY, when=timezone.now() - timedelta(days=2))
        self.assertNotEqual(self._capture().status_code, 429)

    def test_cap_works_without_client_sending_speed_fields(self):
        """Главное свойство: потолок не зависит от того, что прислал клиент.

        Проверку скорости можно выключить, просто не прислав дистанцию и время.
        Потолок так обойти нельзя.
        """
        self._award(MAX_CAPTURES_PER_DAY)
        r = self.api_post("/v1/territories/capture", {
            "points": [[62.0, 129.70], [62.0, 129.7030],
                       [62.0014, 129.7030], [62.0014, 129.70]],
            "captureId": "no-speed-fields",
        })
        self.assertEqual(r.status_code, 429)
