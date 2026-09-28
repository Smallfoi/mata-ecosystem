"""Аудит D09: неполная прод-конфигурация — явный отказ, а не тихое dev-поведение.

Отказ старта — только для переменных, которые прод-скрипты кладут в .env всегда
(deploy/prod-deploy.sh, deploy/refresh-env.sh). Для остальных — предупреждение.
"""
import os
from unittest import mock

from django.test import SimpleTestCase, TestCase

from common.prodcheck import prod_config_report

# Ровно то, что гарантированно лежит в прод-.env по deploy-скриптам (+ секреты,
# наличие которых скрипты проверяют сами).
_PROD_ENV = {
    "DJANGO_DEBUG": "0",
    "DJANGO_ALLOWED_HOSTS": "api.mata-club.ru",
    "DJANGO_CORS_ORIGINS": "https://mata-club.ru,https://www.mata-club.ru",
    "POSTGRES_DB": "mata",
    "POSTGRES_USER": "mata",
    "POSTGRES_HOST": "db",
    "REDIS_URL": "redis://redis:6379/0",
    "POSTGRES_PASSWORD": "strong-db-pass",
    "DJANGO_SECRET_KEY": "s" * 50,
    "JWT_SECRET": "j" * 50,
}
_INTEGRATIONS = {
    "SMS_PROVIDER": "propush",
    "SENTRY_DSN": "https://key@glitchtip.example/1",
    "MEDIA_S3_BUCKET": "b",
    "MEDIA_S3_ACCESS_KEY": "a",
    "MEDIA_S3_SECRET_KEY": "k",
}


def _without(env, *names):
    return {k: v for k, v in env.items() if k not in names}


class ProdConfigReportTests(SimpleTestCase):
    def test_env_from_deploy_scripts_starts(self):
        # Главное: то, что реально собирают прод-скрипты, НЕ даёт отказа старта.
        self.assertEqual(prod_config_report(_PROD_ENV, debug=False)["fatal"], [])

    def test_fully_configured_prod_has_no_warnings(self):
        self.assertEqual(prod_config_report({**_PROD_ENV, **_INTEGRATIONS}, debug=False),
                         {"fatal": [], "warnings": []})

    def test_missing_redis_refuses_to_start(self):
        # Раньше: молча LocMem-кэш на каждом воркере + Celery EAGER.
        rep = prod_config_report(_without(_PROD_ENV, "REDIS_URL"), debug=False)
        self.assertEqual(rep["fatal"], ["REDIS_URL"])

    def test_broker_alone_does_not_replace_redis(self):
        # CELERY_BROKER_URL спасает задачи, но кэш всё равно ушёл бы в LocMem.
        env = {**_without(_PROD_ENV, "REDIS_URL"), "CELERY_BROKER_URL": "redis://redis:6379/1"}
        self.assertIn("REDIS_URL", prod_config_report(env, debug=False)["fatal"])

    def test_missing_cors_refuses_to_start(self):
        # Раньше: пустой список = CORS_ALLOW_ALL_ORIGINS=True на проде.
        rep = prod_config_report({**_PROD_ENV, "DJANGO_CORS_ORIGINS": " "}, debug=False)
        self.assertEqual(rep["fatal"], ["DJANGO_CORS_ORIGINS"])

    def test_default_secrets_still_refuse(self):
        rep = prod_config_report(_without(_PROD_ENV, "JWT_SECRET", "DJANGO_SECRET_KEY"),
                                 debug=False)
        self.assertEqual(set(rep["fatal"]), {"JWT_SECRET", "DJANGO_SECRET_KEY"})

    def test_optional_integrations_only_warn(self):
        rep = prod_config_report(_PROD_ENV, debug=False)
        self.assertEqual(rep["fatal"], [])
        self.assertEqual(set(rep["warnings"]), {"SMS_PROVIDER", "SENTRY_DSN", "MEDIA_S3_BUCKET"})

    def test_partial_s3_keys_warn(self):
        env = {**_PROD_ENV, **_without(_INTEGRATIONS, "MEDIA_S3_SECRET_KEY")}
        self.assertEqual(prod_config_report(env, debug=False)["warnings"], ["MEDIA_S3_BUCKET"])

    def test_dev_never_blocks_or_warns(self):
        self.assertEqual(prod_config_report({}, debug=True), {"fatal": [], "warnings": []})

    def test_report_contains_names_not_values(self):
        rep = prod_config_report({**_PROD_ENV, "DJANGO_CORS_ORIGINS": ""}, debug=False)
        flat = " ".join(rep["fatal"] + rep["warnings"])
        self.assertNotIn("strong-db-pass", flat)
        self.assertNotIn("redis://", flat)


class HealthConfigWarningsTests(TestCase):
    def test_dev_health_has_empty_list(self):
        d = self.client.get("/v1/health").json()
        # Контракт прежний, поле добавлено.
        self.assertEqual(d["status"], "ok")
        self.assertEqual(d["configWarnings"], [])

    def test_prod_health_names_missing_integrations(self):
        with mock.patch.dict(os.environ, {**_PROD_ENV}, clear=False):
            for k in _INTEGRATIONS:
                os.environ.pop(k, None)
            d = self.client.get("/v1/health", secure=True, HTTP_HOST="api.mata-club.ru").json()
        self.assertEqual(set(d["configWarnings"]), {"SMS_PROVIDER", "SENTRY_DSN", "MEDIA_S3_BUCKET"})
        self.assertEqual(d["status"], "ok")
