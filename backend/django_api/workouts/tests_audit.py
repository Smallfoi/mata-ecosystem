"""Аудит 27.09.2026: C02 (реестр учтённых тренировок), C05 (активность и начисление
атомарно), D04 (некорректные числа — отказ, а не 500).
"""
import importlib
from datetime import timedelta
from unittest import mock

from django.apps import apps as django_apps
from django.utils import timezone

from common.testutils import ApiTestCase
from loyalty.models import LoyaltyTransaction
from workouts.models import ExternalWorkout, WorkoutAward


class WorkoutAuditTests(ApiTestCase):
    phone = "+79990009881"
    _n = 0

    def _item(self, km=5.0, minutes=30, source_id=None, **extra):
        WorkoutAuditTests._n += 1
        started = timezone.now() - timedelta(hours=2)
        return {
            "sourceId": source_id or f"hca_{WorkoutAuditTests._n}",
            "startedAtMs": int(started.timestamp() * 1000),
            "durationS": minutes * 60,
            "distanceM": km * 1000,
            **extra,
        }

    def _import(self, items, source="healthconnect"):
        return self.api_post("/v1/workouts/import", {"source": source, "items": items})

    def _disconnect(self, source="healthconnect"):
        return self.client.delete(
            f"/v1/workouts/source/{source}", HTTP_AUTHORIZATION=f"Bearer {self.token}"
        )

    # ── C02 ────────────────────────────────────────────────────────────────

    def test_reconnect_does_not_award_same_workout_again(self):
        item = self._item(km=5, source_id="hc-fixed")
        self.assertEqual(self._import([item]).json()["points"], 50)
        self.assertEqual(self._disconnect().status_code, 200)
        self.assertEqual(ExternalWorkout.objects.filter(user_id=self.uid).count(), 0)

        r = self._import([item])
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["points"], 0)
        self.assertEqual(self.balance(), 50)
        # Данные снова видны человеку — но без второго начисления.
        self.assertEqual(ExternalWorkout.objects.filter(user_id=self.uid).count(), 1)

    def test_zero_point_decision_survives_reconnect(self):
        """Тренировка без баллов (велосипед) после переподключения баллов не получает."""
        item = self._item(km=10, source_id="bike-1", sport="biking")
        self._import([item])
        self._disconnect()
        item["sport"] = "running"   # источник «передумал» — решение уже принято
        self.assertEqual(self._import([item]).json()["points"], 0)
        self.assertEqual(self.balance(), 0)

    def test_backfill_registers_workouts_imported_before_registry(self):
        """На проде тренировки импортированы до появления реестра: миграция
        заполняет реестр из них, и переподключение не платит второй раз."""
        item = self._item(km=4, source_id="legacy-1")
        self._import([item])
        WorkoutAward.objects.all().delete()   # состояние «до миграции»

        mig = importlib.import_module("workouts.migrations.0002_workoutaward")
        mig.backfill(django_apps, None)
        self.assertEqual(WorkoutAward.objects.filter(user_id=self.uid).count(), 1)

        self._disconnect()
        self.assertEqual(self._import([item]).json()["points"], 0)
        self.assertEqual(self.balance(), 40)

    # ── C05 ────────────────────────────────────────────────────────────────

    def test_failed_award_rolls_back_and_retry_awards_once(self):
        item = self._item(km=3, source_id="crash-1")
        with mock.patch("workouts.service.add_txn", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self._import([item])
        # Тренировка без начисления не осталась висеть «учтённой».
        self.assertFalse(ExternalWorkout.objects.filter(user_id=self.uid).exists())
        self.assertFalse(WorkoutAward.objects.filter(user_id=self.uid).exists())

        r = self._import([item])
        self.assertEqual(r.json()["points"], 30)
        self._import([item])
        self.assertEqual(self.balance(), 30)
        self.assertEqual(
            LoyaltyTransaction.objects.filter(user_id=self.uid, amount=30).count(), 1
        )

    # ── D04 ────────────────────────────────────────────────────────────────

    def test_non_finite_and_huge_numbers_are_skipped_not_500(self):
        bad = [
            self._item(distanceM="nan"),
            self._item(distanceM="Infinity"),
            self._item(durationS=10 ** 12),
            {**self._item(), "startedAtMs": 10 ** 20},
            self._item(avgHr=10 ** 12),
            self._item(distanceM=True),
        ]
        r = self._import(bad + [self._item(km=2)])
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["imported"], 2)   # хорошая + avgHr (пульс просто отброшен)
        self.assertEqual(body["skipped"], 5)
        self.assertEqual(ExternalWorkout.objects.filter(user_id=self.uid).count(), 2)

    def test_non_dict_body_is_400(self):
        r = self.client.post(
            "/v1/workouts/import", data="[1,2]", content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.token}",
        )
        self.assertEqual(r.status_code, 400)
