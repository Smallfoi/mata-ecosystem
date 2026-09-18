"""Авто-удаление данных по срокам хранения (152-ФЗ §2)."""
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


class AppConfigTests(TestCase):
    """Серверные флаги /v1/config (D-87): по умолчанию периферия скрыта; админ включает."""

    def test_config_defaults_hide_periphery(self):
        d = self.client.get("/v1/config").json()
        # На старте (D-75) периферия скрыта — все флаги False по умолчанию.
        for key in ("showTrails", "showWatch", "showRaces", "showLeagueFull",
                    "showSleepingMedals"):
            self.assertIn(key, d)
            self.assertFalse(d[key], f"{key} должен быть скрыт по умолчанию")

    def test_config_reflects_admin_change(self):
        from core.models import AppConfig

        cfg = AppConfig.load()
        cfg.show_trails = True
        cfg.save()
        self.assertTrue(self.client.get("/v1/config").json()["showTrails"])

    def test_config_is_singleton(self):
        from core.models import AppConfig

        obj = AppConfig.load()
        obj.id = 7  # попытка сменить id
        obj.save()  # save() принудительно нормализует id к 1 → та же строка
        self.assertEqual(AppConfig.objects.count(), 1)
        self.assertEqual(AppConfig.objects.first().id, 1)

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
