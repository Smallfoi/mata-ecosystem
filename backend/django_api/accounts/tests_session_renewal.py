"""Скользящее продление входа (22.11.2026).

Токен жил ровно 30 дней от входа, продления не было: раз в месяц любой
пользователь вылетал на экран входа посреди дела. Теперь `/auth/me` отдаёт
`renewedToken`, когда старому осталось меньше половины срока.
"""
import time
from unittest import mock

from django.core.cache import cache
from django.test import TestCase

from accounts.models import Account
from common import security
from common.security import make_token


def _me(client, token):
    return client.get("/v1/auth/me", HTTP_AUTHORIZATION=f"Bearer {token}")


def _token_issued_days_ago(uid, days, version=0):
    with mock.patch.object(security.time, "time", return_value=time.time() - days * 86400):
        return make_token(uid, version)


class SessionRenewalTests(TestCase):
    def setUp(self):
        cache.clear()
        self.acc = Account.objects.create(id="u_renew", email="r@t.dev",
                                          phone="+79990005101", provider="phone")

    def test_fresh_token_is_not_renewed(self):
        r = _me(self.client, make_token(self.acc.id))
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("renewedToken", r.json())

    def test_old_token_gets_working_replacement(self):
        old = _token_issued_days_ago(self.acc.id, 20)
        r = _me(self.client, old)
        self.assertEqual(r.status_code, 200)
        fresh = r.json()["renewedToken"]
        self.assertNotEqual(fresh, old)
        # Новый токен действует и сам продления пока не требует.
        r2 = _me(self.client, fresh)
        self.assertEqual(r2.status_code, 200)
        self.assertNotIn("renewedToken", r2.json())

    def test_expired_token_is_not_renewed(self):
        dead = _token_issued_days_ago(self.acc.id, 31)
        self.assertEqual(_me(self.client, dead).status_code, 401)

    def test_revoked_session_is_not_renewed(self):
        # Смена пароля поднимает версию — старый токен не продлить, даже близкий к концу.
        old = _token_issued_days_ago(self.acc.id, 20, version=0)
        Account.objects.filter(id=self.acc.id).update(token_version=1)
        security.forget_account(self.acc.id)
        self.assertEqual(_me(self.client, old).status_code, 401)

    def test_renewal_keeps_session_version(self):
        Account.objects.filter(id=self.acc.id).update(token_version=3)
        security.forget_account(self.acc.id)
        old = _token_issued_days_ago(self.acc.id, 20, version=3)
        fresh = _me(self.client, old).json()["renewedToken"]
        Account.objects.filter(id=self.acc.id).update(token_version=4)
        security.forget_account(self.acc.id)
        self.assertEqual(_me(self.client, fresh).status_code, 401)
