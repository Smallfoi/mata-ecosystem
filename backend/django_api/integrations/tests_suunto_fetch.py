# -*- coding: utf-8 -*-
"""Приём тренировки с часов Suunto: уведомление → задача → импорт.

Проверяем три вещи, в которых легко ошибиться:
1) уведомление не несёт данных, поэтому чужой «пинг» ничего не портит;
2) тренировка проходит ОБЩИЙ путь импорта — та же склейка с нашим забегом,
   тот же суточный потолок, то же начисление;
3) повтор уведомления не задваивает ни запись, ни баллы.
"""
from datetime import timedelta
from unittest import mock

from django.utils import timezone

from common.testutils import ApiTestCase
from integrations import suunto
from integrations.models import WatchAccount
from integrations.tasks import fetch_suunto_workout
from workouts.models import ExternalWorkout
from workouts.tests_trust import _drawn_track, _recorded_track

PUSH = "/v1/integrations/suunto/push"

def _recent_ms(hours_ago=2):
    """Время недавней тренировки. Фиксированную дату брать нельзя: через месяц
    она станет «слишком старой» и тест начнёт падать сам по себе."""
    return int((timezone.now() - timedelta(hours=hours_ago)).timestamp() * 1000)


# Ответ Suunto на запрос тренировки: 5 км за 30 минут.
WORKOUT = {
    "workoutKey": "w-1",
    "activityId": 1,
    "startTime": _recent_ms(),
    "totalDistance": 5000,
    "totalTime": 1800,
    "hrAvg": 2.5,            # у них удары в СЕКУНДУ — должны превратиться в 150
    "energyConsumption": 320,
}


class SuuntoPushTests(ApiTestCase):
    phone = "+79990009304"

    def setUp(self):
        super().setUp()
        self.account = WatchAccount.objects.create(
            user_id=self.uid, source="suunto", external_id="suunto-user-1",
            access_token="acc", refresh_token="ref",
            expires_at=timezone.now() + timedelta(hours=1),
        )

    def _push(self, body):
        return self.client.post(PUSH, data=body, content_type="application/json")

    # ── Уведомление ────────────────────────────────────────────────────────

    @mock.patch("integrations.tasks.fetch_suunto_workout.delay")
    def test_known_user_gets_a_task(self, m_delay):
        r = self._push('{"username": "suunto-user-1", "workoutid": "w-1"}')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["queued"], 1)
        m_delay.assert_called_once_with(self.account.pk, "w-1")

    @mock.patch("integrations.tasks.fetch_suunto_workout.delay")
    def test_unknown_user_is_ignored_quietly(self, m_delay):
        """Чужой username не должен ни ставить задачу, ни подтверждать, кто у нас есть."""
        r = self._push('{"username": "кто-то-ещё", "workoutid": "w-9"}')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["queued"], 0)
        m_delay.assert_not_called()

    @mock.patch("integrations.tasks.fetch_suunto_workout.delay")
    def test_event_without_workout_id_is_skipped(self, m_delay):
        self.assertEqual(self._push('{"username": "suunto-user-1"}').json()["queued"], 0)
        m_delay.assert_not_called()

    def test_garbage_body_is_refused(self):
        r = self.client.post(PUSH, data="не json", content_type="application/json")
        self.assertEqual(r.status_code, 400)

    # ── Задача: получение и импорт ─────────────────────────────────────────

    @mock.patch("integrations.suunto.fetch_workout", return_value=WORKOUT)
    def test_task_imports_workout_and_awards_points(self, m_fetch):
        self.assertEqual(fetch_suunto_workout(self.account.pk, "w-1"), "imported")
        w = ExternalWorkout.objects.get(user_id=self.uid, source="suunto")
        self.assertEqual(w.source_id, "w-1")
        self.assertEqual(w.distance_m, 5000)
        self.assertEqual(w.duration_s, 1800)
        self.assertEqual(w.avg_hr, 150, "удары в секунду не перевели в минуту")
        self.assertGreater(w.points_awarded, 0)
        self.account.refresh_from_db()
        self.assertIsNotNone(self.account.last_sync_at)

    @mock.patch("integrations.suunto.fetch_workout", return_value=WORKOUT)
    def test_repeat_notification_does_not_double_anything(self, m_fetch):
        fetch_suunto_workout(self.account.pk, "w-1")
        before = self.balance()
        self.assertEqual(fetch_suunto_workout(self.account.pk, "w-1"), "duplicate")
        self.assertEqual(ExternalWorkout.objects.filter(user_id=self.uid).count(), 1)
        self.assertEqual(self.balance(), before, "баллы начислились второй раз")

    @mock.patch("integrations.suunto.fetch_workout", return_value={"totalDistance": 0})
    def test_workout_without_distance_is_not_imported(self, m_fetch):
        """Сон и прочие записи без дистанции — не пробежка, импортировать нечего."""
        self.assertEqual(fetch_suunto_workout(self.account.pk, "w-2"), "нечего импортировать")
        self.assertEqual(ExternalWorkout.objects.count(), 0)

    def test_task_without_account_does_nothing(self):
        """Часы отключили, пока задача ждала очереди."""
        self.assertEqual(fetch_suunto_workout(999999, "w-1"), "нет аккаунта")

    @mock.patch("integrations.suunto.refresh_tokens",
                return_value={"access_token": "new-acc", "expires_in": 3600})
    @mock.patch("integrations.suunto.fetch_workout", return_value=WORKOUT)
    def test_expired_token_is_refreshed_before_fetching(self, m_fetch, m_refresh):
        self.account.expires_at = timezone.now() - timedelta(minutes=1)
        self.account.save(update_fields=["expires_at"])
        fetch_suunto_workout(self.account.pk, "w-1")
        self.account.refresh_from_db()
        self.assertEqual(self.account.access_token, "new-acc")
        m_fetch.assert_called_once()
        self.assertEqual(m_fetch.call_args[0][0], "new-acc", "запрос ушёл со старым токеном")


class SuuntoShapeTests(ApiTestCase):
    """Перевод их ответа в наш вид: названия полей у них разнятся по версиям."""

    phone = "+79990009305"

    def test_seconds_timestamps_are_understood(self):
        """Секунды вместо миллисекунд — не 1970 год, а то же самое время."""
        seconds = int(_recent_ms() / 1000)
        data = suunto.to_workout(
            {"startTime": seconds, "totalDistance": 3000, "totalTime": 900}, "w-3")
        self.assertAlmostEqual(data["started_at"].timestamp(), seconds, delta=1)

    def test_alternative_field_names_work(self):
        data = suunto.to_workout(
            {"timestamp": _recent_ms(), "distance": 4200, "duration": 1200,
             "activityType": "trail running"}, "w-4")
        self.assertEqual(data["distance_m"], 4200)
        self.assertEqual(data["sport"], "run")

    def test_non_running_activity_is_marked_other(self):
        data = suunto.to_workout(
            {"startTime": _recent_ms(), "totalDistance": 20000, "totalTime": 3600,
             "activityId": 99}, "w-5")
        self.assertEqual(data["sport"], "other")

    def test_empty_payload_gives_nothing(self):
        self.assertIsNone(suunto.to_workout({}, "w-6"))
        self.assertIsNone(suunto.to_workout(None, "w-7"))

class SuuntoTrustTests(ApiTestCase):
    """Достоверность записи (D-108) доезжает до тренировки, а не остаётся в голове."""

    phone = "+79990009306"

    def setUp(self):
        super().setUp()
        self.account = WatchAccount.objects.create(
            user_id=self.uid, source="suunto", external_id="suunto-user-2",
            access_token="acc", expires_at=timezone.now() + timedelta(hours=1),
        )

    @mock.patch("integrations.suunto.fetch_workout", return_value=WORKOUT)
    @mock.patch("integrations.suunto.download_fit", return_value=b"fit-bytes")
    @mock.patch("integrations.fit.parse")
    def test_real_recording_is_marked_trusted(self, m_parse, m_fit, m_fetch):
        m_parse.return_value = _recorded_track()
        fetch_suunto_workout(self.account.pk, "w-10")
        w = ExternalWorkout.objects.get(user_id=self.uid)
        self.assertEqual(w.trust_level, "high")
        self.assertGreater(w.track_points, 50)
        self.assertFalse(w.flagged)

    @mock.patch("integrations.suunto.fetch_workout", return_value=WORKOUT)
    @mock.patch("integrations.suunto.download_fit", return_value=b"fit-bytes")
    @mock.patch("integrations.fit.parse")
    def test_drawn_track_is_flagged_with_a_reason(self, m_parse, m_fit, m_fetch):
        m_parse.return_value = _drawn_track()
        fetch_suunto_workout(self.account.pk, "w-11")
        w = ExternalWorkout.objects.get(user_id=self.uid)
        self.assertEqual(w.trust_level, "low")
        self.assertTrue(w.flagged)
        self.assertIn("не похожа на часы", w.flag_reason)

    @mock.patch("integrations.suunto.fetch_workout", return_value=WORKOUT)
    @mock.patch("integrations.suunto.download_fit",
                side_effect=suunto.SuuntoError("404"))
    def test_missing_fit_does_not_break_the_import(self, m_fit, m_fetch):
        """Трек не отдали — километры всё равно засчитываем, захват придержим."""
        self.assertEqual(fetch_suunto_workout(self.account.pk, "w-12"), "imported")
        w = ExternalWorkout.objects.get(user_id=self.uid)
        self.assertEqual(w.trust_level, "medium")
        self.assertEqual(w.track_points, 0)
        self.assertFalse(w.flagged)

