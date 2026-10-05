# -*- coding: utf-8 -*-
"""Подключение часов Suunto: кто разрешил доступ — тот и получает свои тренировки.

Главное, что здесь проверяется, — чужой не может подключить свои часы к нашему
аккаунту и наоборот. Поэтому `state` подписан: Suunto возвращает человека на
публичный адрес, где нашего токена уже нет, и единственное доказательство, кто
это, — подпись в ссылке.
"""
from unittest import mock

from django.core import signing
from common.testutils import ApiTestCase
from integrations import suunto
from integrations.models import WatchAccount

KEYS = {
    "SUUNTO_CLIENT_ID": "client-123",
    "SUUNTO_CLIENT_SECRET": "secret-456",
    "SUUNTO_SUBSCRIPTION_KEY": "sub-789",
}

TOKENS = {
    "access_token": "acc-token",
    "refresh_token": "ref-token",
    "expires_in": 3600,
    "user": "suunto-user-1",
}


@mock.patch.dict("os.environ", KEYS, clear=False)
class SuuntoConnectTests(ApiTestCase):
    phone = "+79990009303"

    def _start(self):
        return self.api_get("/v1/integrations/suunto/connect")

    def test_connect_requires_login(self):
        self.assertEqual(self.client.get("/v1/integrations/suunto/connect").status_code, 401)

    def test_connect_returns_suunto_link(self):
        r = self._start()
        self.assertEqual(r.status_code, 200)
        url = r.json()["url"]
        self.assertIn("cloudapi-oauth.suunto.com", url)
        self.assertIn("client_id=client-123", url)
        self.assertIn("api.mata-club.ru%2Fv1%2Fintegrations%2Fsuunto%2Fcallback", url)

    @mock.patch.dict("os.environ", {"SUUNTO_CLIENT_ID": ""}, clear=False)
    def test_connect_without_keys_says_not_ready(self):
        """Ключей нет — честный 503, а не ссылка, которая приведёт в тупик."""
        self.assertEqual(self._start().status_code, 503)

    def _state_for_me(self):
        return signing.dumps({"uid": self.uid}, salt="mata.suunto.connect")

    @mock.patch("integrations.suunto.exchange_code", return_value=TOKENS)
    def test_callback_saves_account(self, m_exchange):
        r = self.client.get(
            f"/v1/integrations/suunto/callback?code=abc&state={self._state_for_me()}")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])
        acc = WatchAccount.objects.get(user_id=self.uid, source="suunto")
        self.assertEqual(acc.access_token, "acc-token")
        self.assertEqual(acc.external_id, "suunto-user-1")
        self.assertFalse(acc.expired)

    @mock.patch("integrations.suunto.exchange_code", return_value=TOKENS)
    def test_second_connect_updates_instead_of_duplicating(self, m_exchange):
        for _ in range(2):
            self.client.get(
                f"/v1/integrations/suunto/callback?code=abc&state={self._state_for_me()}")
        self.assertEqual(WatchAccount.objects.filter(user_id=self.uid).count(), 1)

    def test_callback_rejects_forged_state(self):
        """Подставленный идентификатор пользователя — подпись не сойдётся."""
        r = self.client.get("/v1/integrations/suunto/callback?code=abc&state=я-другой-человек")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(WatchAccount.objects.count(), 0)

    def test_callback_without_code_is_a_polite_refusal(self):
        """Человек передумал на странице Suunto — это не ошибка."""
        r = self.client.get("/v1/integrations/suunto/callback")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["ok"])
        self.assertEqual(WatchAccount.objects.count(), 0)

    @mock.patch("integrations.suunto.exchange_code",
                side_effect=suunto.SuuntoError("Suunto 400: bad code"))
    def test_callback_survives_suunto_refusal(self, m_exchange):
        r = self.client.get(
            f"/v1/integrations/suunto/callback?code=abc&state={self._state_for_me()}")
        self.assertEqual(r.status_code, 502)
        self.assertEqual(WatchAccount.objects.count(), 0)

    @mock.patch("integrations.suunto.exchange_code", return_value={"access_token": ""})
    def test_callback_without_token_does_not_save(self, m_exchange):
        r = self.client.get(
            f"/v1/integrations/suunto/callback?code=abc&state={self._state_for_me()}")
        self.assertEqual(r.status_code, 502)
        self.assertEqual(WatchAccount.objects.count(), 0)

    @mock.patch("integrations.suunto.exchange_code", return_value=TOKENS)
    def test_disconnect_removes_the_token(self, m_exchange):
        """Отключил часы — токен исчезает целиком, а не «помечается неактивным»."""
        self.client.get(f"/v1/integrations/suunto/callback?code=abc&state={self._state_for_me()}")
        r = self.client.delete("/v1/integrations/suunto/disconnect",
                               HTTP_AUTHORIZATION=f"Bearer {self.token}")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["removed"])
        self.assertEqual(WatchAccount.objects.count(), 0)

    def test_disconnect_requires_login(self):
        self.assertEqual(self.client.delete("/v1/integrations/suunto/disconnect").status_code, 401)
