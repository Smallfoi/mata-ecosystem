"""Выбор брокера Celery (аудит E04).

В проде брокер — отдельный Redis с noeviction (docker-compose.prod.yml задаёт
CELERY_BROKER_URL=redis://redis-broker:6379/0), кэш — REDIS_URL с allkeys-lru.
Страж: настройки обязаны брать брокер из CELERY_BROKER_URL, а не из кэша; без него
(dev-стек) — прежнее поведение, брокер = REDIS_URL. Модуль настроек исполняется
заново в изолированном объекте — живые django.conf.settings не трогаются.
"""
import importlib.util
import os
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase

_SETTINGS = Path(__file__).resolve().parent.parent / "config" / "settings.py"


def _load_settings(**env):
    base = {k: v for k, v in os.environ.items()
            if k not in ("REDIS_URL", "CELERY_BROKER_URL", "CELERY_RESULT_BACKEND", "SENTRY_DSN")}
    base["DJANGO_DEBUG"] = "1"
    base.update(env)
    spec = importlib.util.spec_from_file_location("_settings_probe", _SETTINGS)
    mod = importlib.util.module_from_spec(spec)
    with mock.patch.dict(os.environ, base, clear=True):
        spec.loader.exec_module(mod)
    return mod


class CeleryBrokerSelectionTests(SimpleTestCase):
    def test_separate_broker_wins_over_cache_redis(self):
        s = _load_settings(REDIS_URL="redis://redis:6379/0",
                           CELERY_BROKER_URL="redis://redis-broker:6379/0")
        self.assertEqual(s.CELERY_BROKER_URL, "redis://redis-broker:6379/0")
        self.assertEqual(s.CACHES["default"]["LOCATION"], "redis://redis:6379/0")
        self.assertFalse(s.CELERY_TASK_ALWAYS_EAGER)

    def test_without_broker_url_falls_back_to_cache_redis(self):
        # dev-стек (docker-compose.yml) задаёт только REDIS_URL — поведение прежнее
        s = _load_settings(REDIS_URL="redis://redis:6379/0")
        self.assertEqual(s.CELERY_BROKER_URL, "redis://redis:6379/0")
        self.assertFalse(s.CELERY_TASK_ALWAYS_EAGER)

    def test_no_redis_at_all_is_eager(self):
        # CI/тесты без Redis: задачи inline, как и раньше
        s = _load_settings()
        self.assertEqual(s.CELERY_BROKER_URL, "")
        self.assertTrue(s.CELERY_TASK_ALWAYS_EAGER)
