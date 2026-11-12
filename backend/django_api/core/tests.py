"""Авто-удаление данных по срокам хранения (152-ФЗ §2)."""
import os
from datetime import timedelta

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from common.testutils import login_admin


@override_settings(ANALYTICS_EVENT_RETENTION_DAYS=365, READ_NOTIFICATION_RETENTION_DAYS=90)
class OldDataCleanupTests(TestCase):
    """cleanup_old_data удаляет старые события + старые ПРОЧИТАННЫЕ уведомления,
    свежее и непрочитанное — оставляет. История (лояльность/заказы) не трогается."""

    def _age(self, model, pk, days):
        model.objects.filter(pk=pk).update(created_at=timezone.now() - timedelta(days=days))

    def test_purges_old_events_and_read_notifications(self):
        from analytics.models import Event
        from notifications.models import Notification, create_notification

        old_ev = Event.objects.create(name="old", user_id="u1")
        self._age(Event, old_ev.pk, 400)
        Event.objects.create(name="fresh", user_id="u1")  # свежее — остаётся

        read_old = create_notification("u1", "read old")
        read_old.read = True
        read_old.save(update_fields=["read"])
        self._age(Notification, read_old.pk, 120)
        unread_old = create_notification("u1", "unread old")  # непрочитанное — остаётся
        self._age(Notification, unread_old.pk, 120)

        call_command("cleanup_old_data")

        self.assertFalse(Event.objects.filter(name="old").exists())
        self.assertTrue(Event.objects.filter(name="fresh").exists())
        self.assertFalse(Notification.objects.filter(pk=read_old.pk).exists())
        self.assertTrue(Notification.objects.filter(pk=unread_old.pk).exists())

    @override_settings(ANALYTICS_EVENT_RETENTION_DAYS=0)
    def test_zero_retention_disables_event_cleanup(self):
        from analytics.models import Event

        old_ev = Event.objects.create(name="keep", user_id="u1")
        self._age(Event, old_ev.pk, 9999)
        call_command("cleanup_old_data")
        self.assertTrue(Event.objects.filter(name="keep").exists())  # 0 = не удалять


@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True,
                   ANALYTICS_EVENT_RETENTION_DAYS=365)
class CleanupTaskTests(TestCase):
    """Beat-обёртка core.cleanup_old_data вызывает команду (EAGER → синхронно)."""

    def test_task_runs_command(self):
        from analytics.models import Event
        from core.tasks import cleanup_old_data

        e = Event.objects.create(name="old", user_id="u1")
        Event.objects.filter(pk=e.pk).update(created_at=timezone.now() - timedelta(days=400))
        cleanup_old_data.delay()
        self.assertFalse(Event.objects.filter(name="old").exists())


class HealthTests(TestCase):
    """Liveness /v1/health (db+cache) и readiness /v1/health/ready (200/503 для балансировщика)."""

    def test_health_reports_db_and_cache(self):
        d = self.client.get("/v1/health").json()
        self.assertEqual(d["status"], "ok")
        self.assertTrue(d["db"])
        self.assertTrue(d["cache"])
        self.assertEqual(d["service"], "mata-ecosystem-django")  # контракт: поле есть и стабильно

    def test_readiness_ok_when_deps_up(self):
        r = self.client.get("/v1/health/ready")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ready"])

    def test_readiness_503_when_db_down(self):
        from unittest import mock

        with mock.patch("core.views._db_ok", return_value=False):
            r = self.client.get("/v1/health/ready")
        self.assertEqual(r.status_code, 503)  # инстанс выводят из ротации
        self.assertFalse(r.json()["ready"])
        self.assertFalse(r.json()["db"])


class FeatureFlagConfigTests(TestCase):
    """Серверные флаги /v1/config (D-89): направления-строки; периферия скрыта по
    умолчанию, включается флагом в админке. Строки засеяны миграцией 0003."""

    def test_config_defaults_hide_periphery(self):
        d = self.client.get("/v1/config").json()
        # На старте (D-75) периферия скрыта — все флаги False (enabled=False в сиде).
        for key in ("showTrails", "showWatch", "showRaces", "showLeagueFull",
                    "showSleepingMedals"):
            self.assertIn(key, d)
            self.assertFalse(d[key], f"{key} должен быть скрыт по умолчанию")

    def test_config_reflects_admin_change(self):
        from core.models import FeatureFlag

        FeatureFlag.objects.filter(key="trails").update(enabled=True)
        self.assertTrue(self.client.get("/v1/config").json()["showTrails"])

    def test_config_key_mapping(self):
        # league_full → showLeagueFull (snake → show+Camel).
        from core.models import FeatureFlag

        self.assertEqual(FeatureFlag(key="league_full").config_key, "showLeagueFull")

    def test_directions_seeded_with_info(self):
        from core.models import FeatureFlag

        trails = FeatureFlag.objects.get(key="trails")
        self.assertTrue(trails.summary and trails.done and trails.todo)  # карточка заполнена
        self.assertEqual(FeatureFlag.objects.count(), 5)

    def test_config_public_no_auth(self):
        # UI-конфиг — без токена (это не персональные данные).
        self.assertEqual(self.client.get("/v1/config").status_code, 200)


class ErrorsConsoleTests(TestCase):
    """Страница «Ошибки» в админке (D-32): staff-only, отрисовывается даже без GlitchTip."""

    def setUp(self):
        from django.contrib.auth.models import User

        User.objects.create_superuser("boss2", "boss2@x.dev", "pass-12345")
        login_admin(self.client, "boss2", "pass-12345")

    def test_errors_page_renders(self):
        # GlitchTip может быть не настроен (CI) — страница всё равно 200 (graceful).
        r = self.client.get("/admin/errors/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Информационные")  # переключатель уровней отрисован

    def test_errors_page_requires_staff(self):
        self.client.logout()
        r = self.client.get("/admin/errors/")
        self.assertEqual(r.status_code, 302)  # редирект на вход

    def test_error_detail_renders(self):
        # Карточка ошибки внутри админки; без GlitchTip (CI) — 200 с сообщением.
        r = self.client.get("/admin/errors/5/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Все ошибки")  # ссылка назад к списку


class BackupWatchTests(TestCase):
    """Свежесть бэкапов в /v1/health (core/backups.py): сбой копии не должен быть тихим."""

    PROD = {"DJANGO_DEBUG": "0", "BACKUP_S3_BUCKET": "b1", "BACKUP2_S3_BUCKET": "b2"}

    def _warn(self, env=None, *, archive=False, wal=False, now=None):
        from unittest import mock

        from core.backups import backup_warnings

        with mock.patch("core.backups._archive_mode_on", return_value=archive), \
                mock.patch("core.backups.wal_failing", return_value=wal):
            return backup_warnings(env or self.PROD, now=now)

    def test_dev_is_silent(self):
        from core.backups import backup_warnings

        self.assertEqual(backup_warnings({"DJANGO_DEBUG": "1", "BACKUP_S3_BUCKET": "b"}), [])

    def test_first_sight_starts_clock_instead_of_alarm(self):
        from core.models import BackupMark

        self.assertEqual(self._warn(), [])
        self.assertEqual(set(BackupMark.objects.values_list("name", flat=True)), {"dump:1", "dump:2"})

    def test_copy_that_never_arrives_alarms_after_max_age(self):
        t0 = timezone.now()
        self._warn(now=t0)
        self.assertEqual(self._warn(now=t0 + timedelta(hours=25)), [])
        self.assertEqual(self._warn(now=t0 + timedelta(hours=27)), ["dump:1", "dump:2"])

    def test_stale_store_named_fresh_one_not(self):
        from core.backups import mark

        now = timezone.now()
        mark("dump:1", now - timedelta(hours=30))
        mark("dump:2", now - timedelta(hours=2))
        self.assertEqual(self._warn(now=now), ["dump:1"])

    def test_only_configured_stores_are_expected(self):
        from core.backups import mark

        now = timezone.now()
        mark("dump:2", now - timedelta(days=10))  # Timeweb отключили — старая отметка не тревожит
        mark("dump:1", now)
        self.assertEqual(self._warn({"DJANGO_DEBUG": "0", "BACKUP_S3_BUCKET": "b1"}, now=now), [])

    def test_pgbackrest_expected_only_with_archive_mode(self):
        from core.models import BackupMark

        self._warn(archive=True)
        self.assertEqual(set(BackupMark.objects.values_list("name", flat=True)),
                         {"dump:1", "dump:2", "pgbr:1", "pgbr:2"})

    def test_wal_archiving_failure_is_reported(self):
        from core.backups import mark

        now = timezone.now()
        for n in ("dump:1", "dump:2", "pgbr:1", "pgbr:2"):
            mark(n, now)
        self.assertEqual(self._warn(archive=True, wal=True, now=now), ["wal"])
        # без archive_mode журнал не ждём вовсе
        self.assertEqual(self._warn(archive=False, wal=True, now=now), [])

    def test_check_error_does_not_break_health(self):
        from unittest import mock

        from core.backups import backup_warnings

        with mock.patch("core.backups._archive_mode_on", side_effect=RuntimeError("boom")):
            self.assertEqual(backup_warnings(self.PROD), ["check-failed"])

    def test_real_database_queries_work(self):
        from core.backups import _archive_mode_on, wal_failing

        self.assertIsInstance(_archive_mode_on(), bool)
        self.assertIsInstance(wal_failing(), bool)

    def test_mark_command_and_validation(self):
        from django.core.management.base import CommandError

        from core.models import BackupMark

        call_command("backup_mark", "pgbr:2", "dump:1", stdout=open(os.devnull, "w"))
        self.assertEqual(set(BackupMark.objects.values_list("name", flat=True)), {"pgbr:2", "dump:1"})
        with self.assertRaises(CommandError):
            call_command("backup_mark", "dump:3", stdout=open(os.devnull, "w"))

    def test_health_carries_backup_warnings(self):
        d = self.client.get("/v1/health").json()
        self.assertIn("backupWarnings", d)
        self.assertIsInstance(d["backupWarnings"], list)
