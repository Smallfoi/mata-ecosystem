"""Аудит D03: лимиты входа нельзя обойти заголовками, и перебор одного аккаунта
ловится по аккаунту, а не только по адресу."""
import json

from django.core.cache import cache
from django.test import TestCase

from accounts import login_guard
from accounts.models import Account
from common.security import hash_password

PHONE = "+79990002222"
PASSWORD = "right-pass-1"


class LoginIdentTests(TestCase):
    """Ключ лимита `auth` не должен зависеть от заголовков, которые задаёт клиент."""

    def setUp(self):
        cache.clear()

    def _login(self, **headers):
        return self.client.post(
            "/v1/auth/login",
            data=json.dumps({"phone": "+79990009999", "password": "x"}),
            content_type="application/json",
            **headers,
        )

    def test_forged_x_forwarded_for_does_not_reset_the_ip_limit(self):
        # Раньше каждый новый X-Forwarded-For давал новый счётчик: 20/мин не работал.
        codes = [
            self._login(HTTP_X_FORWARDED_FOR=f"10.9.{i // 250}.{i % 250}, 203.0.113.50",
                        HTTP_X_REAL_IP="203.0.113.50").status_code
            for i in range(25)
        ]
        self.assertIn(429, codes)

    def test_x_real_ip_from_outside_is_ignored(self):
        # Запрос не от нашего прокси (адрес соединения публичный): его X-Real-IP
        # не должен менять ключ — иначе тот же обход, только другим заголовком.
        codes = [
            self._login(REMOTE_ADDR="198.51.100.77",
                        HTTP_X_REAL_IP=f"203.0.113.{i + 1}").status_code
            for i in range(25)
        ]
        self.assertIn(429, codes)


class PasswordLoginAccountLimitTests(TestCase):
    def setUp(self):
        cache.clear()
        Account.objects.create(
            id="u_guard", email="guard@test.local", phone=PHONE,
            provider="phone", password_hash=hash_password(PASSWORD),
        )

    def _login(self, password, ip, phone=PHONE):
        return self.client.post(
            "/v1/auth/login",
            data=json.dumps({"phone": phone, "password": password}),
            content_type="application/json",
            HTTP_X_REAL_IP=ip,
        )

    def _fail_from_many_addresses(self, phone=PHONE):
        for i in range(login_guard.MAX_FAILS):
            self.assertEqual(self._login("wrong", ip=f"198.51.100.{i + 1}", phone=phone).status_code, 401)

    def test_bruteforce_from_rotating_addresses_is_stopped(self):
        self._fail_from_many_addresses()
        # Смена адреса не помогает, и даже верный пароль теперь ждёт конца окна.
        r = self._login(PASSWORD, ip="192.0.2.200")
        self.assertEqual(r.status_code, 429)
        self.assertIn("Retry-After", r)

    def test_other_account_is_not_affected(self):
        Account.objects.create(
            id="u_other", email="other@test.local", phone="+79990003333",
            provider="phone", password_hash=hash_password(PASSWORD),
        )
        self._fail_from_many_addresses()
        self.assertEqual(self._login(PASSWORD, ip="192.0.2.1", phone="+79990003333").status_code, 200)

    def test_success_resets_the_counter(self):
        for i in range(login_guard.MAX_FAILS - 1):
            self._login("wrong", ip=f"198.51.100.{i + 1}")
        self.assertEqual(self._login(PASSWORD, ip="192.0.2.1").status_code, 200)
        # После удачного входа счёт с нуля: одна опечатка не блокирует.
        self.assertEqual(self._login("wrong", ip="192.0.2.1").status_code, 401)
        self.assertEqual(self._login(PASSWORD, ip="192.0.2.1").status_code, 200)

    def test_phone_format_does_not_give_a_new_counter(self):
        # 8 999… и +7 999… — один и тот же номер, один счётчик.
        for i in range(login_guard.MAX_FAILS):
            self._login("wrong", ip=f"198.51.100.{i + 1}", phone="8 999 000-22-22")
        self.assertEqual(self._login(PASSWORD, ip="192.0.2.1").status_code, 429)

    def test_legacy_email_login_is_limited_too(self):
        for i in range(login_guard.MAX_FAILS):
            self.client.post(
                "/v1/auth/login",
                data=json.dumps({"email": "Guard@Test.local ", "password": "wrong"}),
                content_type="application/json", HTTP_X_REAL_IP=f"198.51.100.{i + 1}",
            )
        r = self.client.post(
            "/v1/auth/login",
            data=json.dumps({"email": "guard@test.local", "password": PASSWORD}),
            content_type="application/json", HTTP_X_REAL_IP="192.0.2.1",
        )
        self.assertEqual(r.status_code, 429)
