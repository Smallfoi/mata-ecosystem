"""Аудит 27.09.2026, C06: суточные лимиты защищены от параллельных запросов.

Было: забег, импорт тренировки и захват сначала считали «сколько уже есть», а
потом писали новое — без блокировки. Два одновременных запроса одного человека
оба видели «лимит не достигнут» и оба проходили; у захвата оба читали площадь
следа «до» и новая земля оплачивалась дважды.

Стало: проверка и запись идут под транзакционной advisory-блокировкой на
пользователя (common/locks.py). Тест детерминированный: держим эту блокировку
из другого соединения и убеждаемся, что запрос ЖДЁТ, а после отпускания —
проходит. Без блокировки в коде запрос завершается сразу и тест падает.

TransactionTestCase: запрос из другого потока должен видеть закоммиченного
пользователя. Сырые таблицы территорий (не модели Django) после теста чистим сами.
"""
import json
import threading
import time
from datetime import timedelta

from django.core.cache import cache
from django.db import connection, transaction
from django.test import Client, TransactionTestCase
from django.utils import timezone

from accounts.models import Account
from common.locks import ACTIVITY, TERRITORY, lock_user

# Квадрат ~110×55 м далеко от квадратов других тестов (не пересекаемся по геометрии).
_POLY = [[58.000, 110.700], [58.001, 110.700], [58.001, 110.701], [58.000, 110.701]]
_RAW_TABLES = (
    "territories", "footprints", "recent_captures", "processed_captures",
    "territory_events", "block_ownership",
)

HOLD_S = 1.0


class UserLockSerializesLimits(TransactionTestCase):
    phone = "+79990009887"

    def setUp(self):
        cache.clear()
        c = Client()
        r = c.post("/v1/auth/phone/verify",
                   data=json.dumps({"phone": self.phone, "code": "1234"}),
                   content_type="application/json")
        self.token = r.json()["token"]
        self.uid = Account.objects.get(phone=self.phone).id

    def tearDown(self):
        with connection.cursor() as cur:
            for t in _RAW_TABLES:
                col = "owner_id"
                if t == "territory_events":
                    cur.execute(f"DELETE FROM {t} WHERE attacker=%s OR victim_owner=%s",
                                [self.uid, self.uid])
                    continue
                cur.execute(f"DELETE FROM {t} WHERE {col}=%s", [self.uid])

    def _post_while_locked(self, namespace, path, body):
        """Держим (namespace, uid) из другого соединения; шлём запрос.

        Возвращает (ждал ли запрос, пока блокировка держится; ответ).
        """
        acquired, release = threading.Event(), threading.Event()

        def holder():
            try:
                with transaction.atomic():
                    lock_user(namespace, self.uid)
                    acquired.set()
                    release.wait(15)
            finally:
                connection.close()

        out = {}

        def request():
            try:
                out["r"] = Client().post(
                    path, data=json.dumps(body), content_type="application/json",
                    HTTP_AUTHORIZATION=f"Bearer {self.token}",
                )
            finally:
                out["done_at"] = time.monotonic()
                connection.close()

        h = threading.Thread(target=holder)
        h.start()
        self.assertTrue(acquired.wait(10), "не удалось взять блокировку в тесте")
        q = threading.Thread(target=request)
        q.start()
        q.join(HOLD_S)
        waited = q.is_alive()
        release.set()
        h.join(15)
        q.join(30)
        self.assertFalse(q.is_alive(), "запрос не завершился после снятия блокировки")
        return waited, out["r"]

    def test_capture_waits_for_user_lock(self):
        waited, r = self._post_while_locked(TERRITORY, "/v1/territories/capture", {
            "points": _POLY, "captureId": "lock-cap",
            "distanceMeters": 1200.0, "elapsedSeconds": 420,
        })
        self.assertTrue(waited, "захват проверил лимит, не дожидаясь блокировки")
        self.assertEqual(r.status_code, 200, r.content)

    def test_run_waits_for_user_lock(self):
        now_ms = int(timezone.now().timestamp() * 1000)
        waited, r = self._post_while_locked(ACTIVITY, "/v1/runs", {
            "id": "lock-run-1", "distanceMeters": 5000.0, "elapsedSeconds": 1800,
            "finishedAtMs": now_ms,
        })
        self.assertTrue(waited, "забег проверил суточный лимит, не дожидаясь блокировки")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertGreater(r.json()["pointsAwarded"], 0)

    def test_workout_import_waits_for_user_lock(self):
        started = timezone.now() - timedelta(hours=2)
        waited, r = self._post_while_locked(ACTIVITY, "/v1/workouts/import", {
            "source": "healthconnect",
            "items": [{
                "sourceId": "lock-hc-1",
                "startedAtMs": int(started.timestamp() * 1000),
                "durationS": 1800, "distanceM": 5000.0,
            }],
        })
        self.assertTrue(waited, "импорт проверил суточный лимит, не дожидаясь блокировки")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["imported"], 1)

    def test_other_user_is_not_blocked(self):
        """Блокировка персональная: чужой запрос не ждёт."""
        acquired, release = threading.Event(), threading.Event()

        def holder():
            try:
                with transaction.atomic():
                    lock_user(ACTIVITY, "someone-else")
                    acquired.set()
                    release.wait(15)
            finally:
                connection.close()

        h = threading.Thread(target=holder)
        h.start()
        try:
            self.assertTrue(acquired.wait(10))
            r = Client().post(
                "/v1/runs",
                data=json.dumps({"id": "lock-run-2", "distanceMeters": 3000.0,
                                 "elapsedSeconds": 1200,
                                 "finishedAtMs": int(timezone.now().timestamp() * 1000)}),
                content_type="application/json",
                HTTP_AUTHORIZATION=f"Bearer {self.token}",
            )
            self.assertEqual(r.status_code, 200, r.content)
        finally:
            release.set()
            h.join(15)

    def test_milestone_award_waits_for_user_lock(self):
        """Веха выдаётся под той же блокировкой: параллельные забеги не платят дважды."""
        import threading as _t

        from loyalty.models import LoyaltyTransaction
        from runs.milestones import award_milestones
        from runs.models import Run

        Run.objects.create(id="lock-ms-1", user_id=self.uid, distance_m=30_000,
                           duration_s=3 * 3600, finished_at=timezone.now())
        acquired, release = _t.Event(), _t.Event()

        def holder():
            try:
                with transaction.atomic():
                    lock_user(ACTIVITY, self.uid)
                    acquired.set()
                    release.wait(15)
            finally:
                connection.close()

        out = {}

        def award():
            try:
                out["n"] = award_milestones(self.uid, 30.0)
            finally:
                connection.close()

        h = _t.Thread(target=holder)
        h.start()
        self.assertTrue(acquired.wait(10))
        a = _t.Thread(target=award)
        a.start()
        a.join(HOLD_S)
        waited = a.is_alive()
        release.set()
        h.join(15)
        a.join(30)
        self.assertTrue(waited, "веха выдана, не дожидаясь блокировки")
        self.assertEqual(out["n"], 50)  # веха 25 км
        self.assertEqual(LoyaltyTransaction.objects.filter(
            user_id=self.uid, source="runnerMilestone").count(), 1)
