"""Лимиты на запрос кода входа (D-76): баланс SIGMA не сжечь накруткой.

Часы подменены: `_now` и `_local` двигает сам тест, чтобы «через 90 секунд» и «завтра»
не требовали ждать.
"""
import json
import os
from datetime import timedelta
from unittest import mock

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from accounts import otp_guard
from accounts.models import Account
from notifications.models import Notification

ENV = {"SMS_PROVIDER": "propush", "SIGMA_TOKEN": "t0ken", "SIGMA_WIDGET": "widget-uuid"}
PHONE = "+79990001111"


class OtpCostGuardTests(TestCase):
    def setUp(self):
        cache.clear()
        self.starts = 0
        self.provider_ok = True
        self.clock = 1_000_000.0
        self.moment = timezone.localtime().replace(hour=12, minute=0, second=0, microsecond=0)

        def fake_call(method, path, body=None, params=""):
            if method == "POST" and path == "":
                self.starts += 1
                return (200, {"requestId": "req-1"}) if self.provider_ok else (500, {})
            return 200, {"type": "flashcall", "status": "sent", "codeType": "code",
                         "remainingCodeAttempts": 3}

        for patcher in (
            mock.patch.dict(os.environ, ENV),
            mock.patch("accounts.sms._propush_call", side_effect=fake_call),
            mock.patch("accounts.otp_guard._now", side_effect=lambda: self.clock),
            mock.patch("accounts.otp_guard._local", side_effect=lambda: self.moment),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _request(self, phone=PHONE, ip="203.0.113.5"):
        return self.client.post(
            "/v1/auth/phone/request",
            data=json.dumps({"phone": phone}),
            content_type="application/json",
            HTTP_X_REAL_IP=ip,
        )

    def _later(self, seconds=otp_guard.COOLDOWN_SECONDS + 1):
        self.clock += seconds
        self.moment += timedelta(seconds=seconds)

    def test_second_code_within_90_seconds_is_refused(self):
        self.assertEqual(self._request().status_code, 200)
        self._later(30)
        r = self._request()
        self.assertEqual(r.status_code, 429)
        self.assertEqual(r.json()["retryAfter"], 60)
        self.assertEqual(r["Retry-After"], "60")
        self.assertIn("через 60 сек", r.json()["detail"])
        self.assertEqual(self.starts, 1, "за отказ SIGMA платить не должна")

    def test_after_90_seconds_next_code_is_sent(self):
        self._request()
        self._later()
        self.assertEqual(self._request().status_code, 200)
        self.assertEqual(self.starts, 2)

    def test_fourth_code_a_day_is_refused(self):
        for _ in range(otp_guard.PHONE_PER_DAY):
            self.assertEqual(self._request().status_code, 200)
            self._later()
        r = self._request()
        self.assertEqual(r.status_code, 429)
        self.assertIn("завтра", r.json()["detail"])
        self.assertEqual(self.starts, 3)

    def test_day_limit_is_per_number(self):
        for _ in range(3):
            self._request()
            self._later()
        self.assertEqual(self._request(phone="+79990002222").status_code, 200)

    def test_limit_resets_next_day(self):
        for _ in range(3):
            self._request()
            self._later()
        self._later(24 * 3600)
        self.assertEqual(self._request().status_code, 200)

    def test_provider_failure_does_not_use_up_attempts(self):
        """SIGMA не приняла отправку — человек не ждёт 90 секунд и не теряет попытку."""
        self.provider_ok = False
        self.assertEqual(self._request().status_code, 502)
        self.provider_ok = True
        for _ in range(3):
            self.assertEqual(self._request().status_code, 200)
            self._later()

    def test_one_network_is_limited(self):
        with mock.patch.object(otp_guard, "IP_PER_HOUR", 2):
            self.assertEqual(self._request(phone="+79990000001").status_code, 200)
            self.assertEqual(self._request(phone="+79990000002").status_code, 200)
            r = self._request(phone="+79990000003")
            self.assertEqual(r.status_code, 429)
            self.assertIn("из вашей сети", r.json()["detail"])
            # Другой адрес не страдает, и отказ не съел попытку у номера.
            other = self._request(phone="+79990000003", ip="198.51.100.7")
            self.assertEqual(other.status_code, 200)

    def test_no_limits_without_provider(self):
        """В разработке код 1234 бесплатен — лимиты мешали бы только нам."""
        with mock.patch.dict(os.environ, {"SMS_PROVIDER": ""}):
            for _ in range(5):
                self.assertEqual(self._request().status_code, 200)

    def _owner(self):
        return Account.objects.create(
            id="u_owner", email="owner@example.test", phone="+79990009999", provider="phone"
        )

    def test_owner_is_told_once_when_the_hour_looks_like_abuse(self):
        owner = self._owner()
        with mock.patch.object(otp_guard, "ALERT_PER_HOUR", 2), \
                mock.patch.dict(os.environ, {"ALERT_PHONES": " +79990009999 , +70000000000"}), \
                self.assertLogs("accounts.otp_guard", level="WARNING"):
            for i in range(4):
                self.assertEqual(self._request(phone=f"+7999000100{i}").status_code, 200)
        alerts = Notification.objects.filter(user_id=owner.id)
        self.assertEqual(alerts.count(), 1)
        self.assertIn("около 3 ₽", alerts.get().body)

    def test_failed_alert_does_not_break_login(self):
        self._owner()
        with mock.patch.object(otp_guard, "ALERT_PER_HOUR", 1), \
                mock.patch.dict(os.environ, {"ALERT_PHONES": "+79990009999"}), \
                mock.patch("notifications.models.create_notification",
                           side_effect=RuntimeError("boom")), \
                self.assertLogs("accounts.otp_guard", level="WARNING"):
            self.assertEqual(self._request().status_code, 200)
