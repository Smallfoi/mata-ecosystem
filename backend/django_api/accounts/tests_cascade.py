"""Каскад «звонок → SimPush» (D-78): опрос канала и подтверждение без кода.

SIGMA сама переводит на следующий канал, если код не ввели за 90 секунд. Новый канал
бывает бескодовым: человек подтверждает вход на самом телефоне, а клиент заканчивает
вход пустым кодом.
"""
import json
import os
from unittest import mock

from django.core.cache import cache
from django.test import TestCase

ENV = {"SMS_PROVIDER": "propush", "SIGMA_TOKEN": "t0ken", "SIGMA_WIDGET": "widget-uuid"}
PHONE = "+79990007777"


class CascadeTests(TestCase):
    def setUp(self):
        cache.clear()
        self.calls = []
        self.channel = {"type": "flashcall", "status": "sent", "codeType": "code",
                        "remainingCodeAttempts": 3}
        self.completed = True
        self.code_ok = True

        def fake(method, path, body=None, params=""):
            self.calls.append((method, path))
            if method == "POST" and path == "":
                return 200, {"requestId": "req-1"}
            if path.endswith("/channel"):
                return 200, dict(self.channel)
            if path.endswith("/checkStatusAndComplete"):
                return 200, {"success": self.completed}
            if path.endswith("/checkCode"):
                return 200, {"success": self.code_ok}
            return 200, {}

        # Кэш канала выключаем: тесты меняют канал мгновенно, а в жизни клиент
        # спрашивает раз в 3 секунды. Сам кэш проверяет отдельный тест ниже.
        for patcher in (mock.patch.dict(os.environ, ENV),
                        mock.patch("accounts.sms._CHANNEL_TTL", 0),
                        mock.patch("accounts.sms._propush_call", side_effect=fake)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _post(self, path, body):
        return self.client.post(f"/v1/auth/{path}", data=json.dumps(body),
                                content_type="application/json", HTTP_X_REAL_IP="203.0.113.9")

    def _start_session(self):
        self.assertEqual(self._post("phone/request", {"phone": PHONE}).status_code, 200)

    def _channel_calls(self):
        return [c for c in self.calls if c[1].endswith("/channel")]

    def test_channel_tells_client_how_to_confirm(self):
        self._start_session()
        self.channel = {"type": "sim_push", "status": "sent", "codeType": "codeless",
                        "remainingCodeAttempts": 3}
        r = self._post("phone/channel", {"phone": PHONE})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["codeType"], "codeless")
        self.assertEqual(r.json()["type"], "sim_push")

    def test_repeated_polling_does_not_hammer_the_provider(self):
        """Опрос раз в 3 секунды не должен превращаться в поток запросов к SIGMA."""
        with mock.patch("accounts.sms._CHANNEL_TTL", 2):
            self._start_session()          # ответ о канале уже получен и лёг в кэш
            before = len(self._channel_calls())
            for _ in range(5):
                self.assertEqual(self._post("phone/channel", {"phone": PHONE}).status_code, 200)
            self.assertEqual(len(self._channel_calls()) - before, 0, "опрос ушёл к провайдеру")

        # Без кэша каждый опрос — отдельный поход к провайдеру: вот от чего спасаемся.
        # Номер другой: у первого ответ уже лежит в кэше с прошлой половины теста.
        other = "+79990008888"
        self.assertEqual(self._post("phone/request", {"phone": other}).status_code, 200)
        before = len(self._channel_calls())
        for _ in range(5):
            self._post("phone/channel", {"phone": other})
        self.assertEqual(len(self._channel_calls()) - before, 5)

    def test_polling_is_not_cut_off_by_the_login_limit(self):
        """Жёсткий лимит входа (20/мин) убил бы опрос на второй минуте ожидания."""
        self._start_session()
        codes = {self._post("phone/channel", {"phone": PHONE}).status_code for _ in range(25)}
        self.assertEqual(codes, {200})

    def test_no_session_means_404(self):
        self.assertEqual(self._post("phone/channel", {"phone": PHONE}).status_code, 404)

    def test_codeless_waiting_is_not_called_a_wrong_code(self):
        """На бескодовом канале вводить нечего: «неверный код» сбил бы с толку."""
        self._start_session()
        self.channel = {"type": "sim_push", "status": "sent", "codeType": "codeless",
                        "remainingCodeAttempts": 3}
        self.completed = False
        r = self._post("phone/verify", {"phone": PHONE, "code": ""})
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json()["detail"], "Подтвердите вход на телефоне")

    def test_codeless_confirmation_lets_the_person_in(self):
        self._start_session()
        self.channel = {"type": "sim_push", "status": "confirmed", "codeType": "codeless",
                        "remainingCodeAttempts": 3}
        r = self._post("phone/verify", {"phone": PHONE, "code": "", "name": "Бегун"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["token"])
        self.assertIn(("POST", "/req-1/checkStatusAndComplete"), self.calls)
        # Пустой код провайдеру на проверку не отдаём — проверять нечего.
        self.assertNotIn(("POST", "/req-1/checkCode"), self.calls)

    def test_attempts_burned_out_means_ask_for_a_new_code(self):
        """3 промаха — сессия мертва: канал этим не переключается (ответ SIGMA 14.09)."""
        self._start_session()
        self.channel = {"type": "flashcall", "status": "sent", "codeType": "code",
                        "remainingCodeAttempts": 0}
        self.code_ok = False
        r = self._post("phone/verify", {"phone": PHONE, "code": "9999"})
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json()["detail"], "Код больше не действует — запросите новый")
