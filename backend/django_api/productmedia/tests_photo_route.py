"""Страж диагностики маршрута: она ходит в канал Claude, значит не должна
показывать ни ключ, ни секретный путь релея."""
import os
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import SimpleTestCase

SECRET_PATH = "7f3c9a1b2d4e5f60"
RELAY = f"https://mata-relay.val.run/{SECRET_PATH}/v1"


def _run():
    out = StringIO()
    # Соединение не проверяем вживую: тест не должен зависеть от сети.
    with mock.patch("productmedia.management.commands.photo_route._reachable",
                    return_value=(False, "таймаут")):
        call_command("photo_route", stdout=out)
    return out.getvalue()


class PhotoRouteTests(SimpleTestCase):
    def test_relay_secret_path_is_hidden(self):
        with mock.patch.dict(os.environ, {"OPENAI_BASE_URL": RELAY,
                                          "OPENAI_API_KEY": "sk-живой-ключ"}):
            text = _run()
        self.assertNotIn(SECRET_PATH, text)
        self.assertNotIn("sk-живой-ключ", text)
        self.assertIn("mata-relay.val.run", text)
        self.assertIn("путь скрыт", text)

    def test_plain_v1_path_is_not_scary(self):
        with mock.patch.dict(os.environ, {"OPENAI_BASE_URL": "https://api.openai.com/v1"},
                             clear=False):
            text = _run()
        self.assertIn("api.openai.com/v1", text)
        self.assertNotIn("путь скрыт", text)

    def test_dead_proxy_named_as_the_cause(self):
        """Главная ловушка: прокси применяется и к вызовам через живой релей."""
        env = {"OPENAI_BASE_URL": RELAY, "OPENAI_API_KEY": "k",
               "OPENAI_PROXY": "http://147.45.240.21:8888"}
        with mock.patch.dict(os.environ, env):
            text = _run()
        self.assertIn("147.45.240.21:8888", text)
        self.assertIn("Уберите OPENAI_PROXY", text)

    def test_no_key_says_so_first(self):
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "", "OPENAI_BASE_URL": RELAY}):
            text = _run()
        self.assertIn("OPENAI_API_KEY пуст", text)


class FailLoggingTests(SimpleTestCase):
    """Сбой генерации обязан попадать в журнал сервера, а не только в карточку.

    24.11.2026: ответ релея «OpenAI HTTP 404: not found» был виден лишь владельцу
    на экране — в логах стояло только `status: failed`, и расследовать удалённо
    было нечем.
    """

    def test_failure_goes_to_the_log(self):
        from productmedia import service
        from productmedia.models import PhotoJob

        job = PhotoJob(pk=42, article="XRPL006-5", status=PhotoJob.STATUS_PROCESSING)
        with mock.patch.object(PhotoJob, "save"), \
                self.assertLogs("productmedia.service", level="WARNING") as logs:
            service._fail(job, "OpenAI HTTP 404: not found")

        line = "\n".join(logs.output)
        self.assertIn("XRPL006-5", line)
        self.assertIn("OpenAI HTTP 404", line)
        self.assertEqual(job.status, PhotoJob.STATUS_FAILED)
