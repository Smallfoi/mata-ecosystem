"""Suunto: путь API подбирается сам и запоминается; статус говорит, готово ли
подключение, не раскрывая ключей (22.11.2026)."""
import os
from unittest import mock

from django.core.cache import cache
from django.test import TestCase

from integrations import suunto

KEYS = {"SUUNTO_CLIENT_ID": "id", "SUUNTO_CLIENT_SECRET": "sec", "SUUNTO_SUBSCRIPTION_KEY": "sub"}


def _api(answers):
    """api_get по таблице «путь → ответ или код ошибки»; запоминает вызовы."""
    calls = []

    def fake(path, token, params=None):
        calls.append(path)
        got = answers.get(path, 404)
        if isinstance(got, int):
            raise suunto.SuuntoError(f"Suunto {got}", status=got)
        return got
    return fake, calls


class PathDiscoveryTests(TestCase):
    def setUp(self):
        for k in ("workout", "fit"):
            cache.delete(suunto._PATH_KEY.format(k))

    def test_first_answering_path_is_found_and_remembered(self):
        fake, calls = _api({"/v3/workout/7": {"payload": {"totalDistance": 5000}},
                            "/v3/workout/8": {"totalDistance": 3000}})
        with mock.patch.object(suunto, "api_get", side_effect=fake):
            self.assertEqual(suunto.fetch_workout("t", "7"), {"totalDistance": 5000})
            self.assertEqual(calls, ["/v2/workout/7", "/v3/workout/7"])
            calls.clear()
            suunto.fetch_workout("t", "8")
        self.assertEqual(calls, ["/v3/workout/8"], "второй раз — сразу по найденному пути")
        self.assertEqual(suunto.known_path("workout"), "/v3/workout/{id}")

    def test_a_real_error_is_not_mistaken_for_a_wrong_path(self):
        fake, calls = _api({"/v2/workout/7": 401})
        with mock.patch.object(suunto, "api_get", side_effect=fake):
            with self.assertRaises(suunto.SuuntoError) as caught:
                suunto.fetch_workout("t", "7")
        self.assertEqual(caught.exception.status, 401)
        self.assertEqual(calls, ["/v2/workout/7"], "401 — не перебор путей, а отказ")
        self.assertEqual(suunto.known_path("workout"), "")

    def test_path_from_environment_wins(self):
        fake, calls = _api({"/v9/fit/7": b"FIT"})
        with mock.patch.dict(os.environ, {"SUUNTO_FIT_PATH": "/v9/fit/{id}"}), \
                mock.patch.object(suunto, "api_get", side_effect=fake):
            self.assertEqual(suunto.download_fit("t", "7"), b"FIT")
        self.assertEqual(calls, ["/v9/fit/7"])

    def test_nothing_answers(self):
        fake, calls = _api({})
        with mock.patch.object(suunto, "api_get", side_effect=fake):
            with self.assertRaises(suunto.SuuntoError):
                suunto.download_fit("t", "7")
        self.assertEqual(len(calls), len(suunto.FIT_CANDIDATES))


class StatusTests(TestCase):
    def setUp(self):
        for k in ("workout", "fit"):
            cache.delete(suunto._PATH_KEY.format(k))

    def test_suunto_status_says_configured_without_values(self):
        with mock.patch.dict(os.environ, KEYS):
            body = self.client.get("/v1/integrations/suunto/status").json()
        self.assertIs(body["configured"], True)
        self.assertEqual(body["paths"], {"workout": "", "fit": ""})
        self.assertNotIn("sec", str(body))

    def test_suunto_status_without_keys(self):
        with mock.patch.dict(os.environ, {k: "" for k in KEYS}):
            body = self.client.get("/v1/integrations/suunto/status").json()
        self.assertIs(body["configured"], False)

    def test_coros_status_says_whether_we_are_registered(self):
        from integrations.models import McpClient
        self.assertIs(self.client.get("/v1/integrations/coros/status").json()["registered"], False)
        McpClient.objects.create(source="coros", client_id="c", redirect_uri="https://x")
        self.assertIs(self.client.get("/v1/integrations/coros/status").json()["registered"], True)
