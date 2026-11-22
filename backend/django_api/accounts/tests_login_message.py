"""Текст ошибки входа — тем языком, каким человек входил (22.11.2026).

Во всех приложениях вход по номеру телефона, а ошибка говорила «Неверный
телефон/email или пароль» — владелец счёл это путаницей.
"""
import json

from django.core.cache import cache
from django.test import TestCase

from accounts.models import Account
from common.security import hash_password


def _login(client, body):
    return client.post("/v1/auth/login", data=json.dumps(body),
                       content_type="application/json")


class LoginErrorWordingTests(TestCase):
    def setUp(self):
        cache.clear()
        Account.objects.create(id="u_msg", email="m@t.dev", phone="+79990006101",
                               provider="phone", password_hash=hash_password("right-pass"))

    def test_phone_login_mentions_phone_only(self):
        r = _login(self.client, {"phone": "+79990006101", "password": "wrong"})
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json()["detail"], "Неверный номер телефона или пароль")

    def test_email_login_mentions_email(self):
        r = _login(self.client, {"email": "m@t.dev", "password": "wrong"})
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json()["detail"], "Неверный email или пароль")
