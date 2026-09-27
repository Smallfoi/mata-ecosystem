"""Аудит 27.09.2026, блок A: вход и сессии.

Каждый тест воспроизводит находку аудита так, как ей воспользовался бы
посторонний, и проверяет, что больше не выходит.
"""
import importlib
import json
import os
from unittest import mock

from django.apps import apps as django_apps
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase

from accounts.models import Account
from common.security import hash_password, make_token


def _post(client, path, body, token=None):
    headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"} if token else {}
    return client.post(path, data=json.dumps(body), content_type="application/json", **headers)


def _patch(client, path, body, token):
    return client.patch(path, data=json.dumps(body), content_type="application/json",
                        HTTP_AUTHORIZATION=f"Bearer {token}")


def _me(client, token):
    return client.get("/v1/auth/me", HTTP_AUTHORIZATION=f"Bearer {token}")


class OtpAccountHasNoGuessablePassword(TestCase):
    """A01: аккаунт, созданный входом по коду, не открывается паролем «phone:<номер>»."""

    phone = "+79990004101"

    def setUp(self):
        cache.clear()

    def test_password_login_with_phone_as_password_fails(self):
        r = _post(self.client, "/v1/auth/phone/verify", {"phone": self.phone, "code": "1234"})
        self.assertEqual(r.status_code, 200)
        acc = Account.objects.get(phone=self.phone)
        self.assertFalse(acc.password_hash)

        r = _post(self.client, "/v1/auth/login",
                  {"phone": self.phone, "password": f"phone:{self.phone}"})
        self.assertEqual(r.status_code, 401)

    def test_password_set_by_reset_works(self):
        _post(self.client, "/v1/auth/phone/verify", {"phone": self.phone, "code": "1234"})
        r = _post(self.client, "/v1/auth/password/reset",
                  {"phone": self.phone, "code": "1234", "password": "my-own-pass"})
        self.assertEqual(r.status_code, 200)
        r = _post(self.client, "/v1/auth/login", {"phone": self.phone, "password": "my-own-pass"})
        self.assertEqual(r.status_code, 200)

    def test_migration_drops_only_the_guessable_password(self):
        weak = Account.objects.create(id="u_weak", email="w@t.dev", phone="+79990004102",
                                      provider="phone",
                                      password_hash=hash_password("phone:+79990004102"))
        real = Account.objects.create(id="u_real", email="r@t.dev", phone="+79990004103",
                                      provider="phone", password_hash=hash_password("secret-1"))
        mig = importlib.import_module("accounts.migrations.0010_drop_phone_default_password")
        mig.drop(django_apps, None)

        weak.refresh_from_db()
        real.refresh_from_db()
        self.assertIsNone(weak.password_hash)
        r = _post(self.client, "/v1/auth/login", {"phone": "+79990004103", "password": "secret-1"})
        self.assertEqual(r.status_code, 200)


class OldTokensStopWorking(TestCase):
    """A02: токен удалённого аккаунта и токен до смены пароля не действуют."""

    phone = "+79990004201"

    def setUp(self):
        cache.clear()
        r = _post(self.client, "/v1/auth/phone/verify", {"phone": self.phone, "code": "1234"})
        self.token = r.json()["token"]
        self.uid = Account.objects.get(phone=self.phone).id

    def test_token_of_deleted_account_is_rejected(self):
        self.assertEqual(_me(self.client, self.token).status_code, 200)
        r = _post(self.client, "/v1/account/delete", {"confirm": True}, self.token)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(_me(self.client, self.token).status_code, 401)

    def test_token_for_account_that_never_existed_is_rejected(self):
        self.assertEqual(_me(self.client, make_token("ghost-user")).status_code, 401)

    def test_password_reset_revokes_previous_tokens(self):
        self.assertEqual(_me(self.client, self.token).status_code, 200)
        r = _post(self.client, "/v1/auth/password/reset",
                  {"phone": self.phone, "code": "1234", "password": "new-pass-1"})
        self.assertEqual(r.status_code, 200)
        fresh = r.json()["token"]
        self.assertEqual(_me(self.client, self.token).status_code, 401)
        self.assertEqual(_me(self.client, fresh).status_code, 200)
        # Вход по новому паролю даёт действующий токен той же версии.
        r = _post(self.client, "/v1/auth/login", {"phone": self.phone, "password": "new-pass-1"})
        self.assertEqual(_me(self.client, r.json()["token"]).status_code, 200)

    def test_block_takes_effect_immediately(self):
        from accounts.admin import AccountAdmin
        from django.contrib.admin.sites import site

        self.assertEqual(_me(self.client, self.token).status_code, 200)  # состояние в кэше
        admin_obj = AccountAdmin(Account, site)
        with mock.patch.object(admin_obj, "message_user"):
            admin_obj.block_accounts(None, Account.objects.filter(id=self.uid))
        self.assertEqual(_me(self.client, self.token).status_code, 401)

    def test_revoke_sessions_command(self):
        call_command("revoke_sessions", "--user", self.uid, "--apply", stdout=open(os.devnull, "w"))
        self.assertEqual(_me(self.client, self.token).status_code, 401)

    def test_old_format_token_still_valid_until_revoked(self):
        # Токены, выданные до исправления (без версии), не разлогинивают людей сами.
        self.assertEqual(_me(self.client, make_token(self.uid)).status_code, 200)


class PhoneBindingNeedsCode(TestCase):
    """A03: к аккаунту без телефона нельзя привязать номер без подтверждения."""

    def setUp(self):
        cache.clear()
        self.acc = Account.objects.create(id="u_mail", email="m@t.dev", provider="email",
                                          password_hash=hash_password("pw-12345"))
        self.token = make_token(self.acc.id)

    def test_phone_without_code_is_not_bound_but_profile_saves(self):
        r = _patch(self.client, "/v1/profile", {"name": "Новое имя", "phone": "+79990004301"},
                   self.token)
        self.assertEqual(r.status_code, 200)
        self.acc.refresh_from_db()
        self.assertFalse(self.acc.phone)
        self.assertEqual(self.acc.name, "Новое имя")

    def test_phone_with_valid_code_is_bound(self):
        r = _patch(self.client, "/v1/profile", {"phone": "+79990004302", "phoneCode": "1234"},
                   self.token)
        self.assertEqual(r.status_code, 200)
        self.acc.refresh_from_db()
        self.assertEqual(self.acc.phone, "+79990004302")

    def test_phone_with_wrong_code_is_not_bound(self):
        _patch(self.client, "/v1/profile", {"phone": "+79990004303", "phoneCode": "0000"},
               self.token)
        self.acc.refresh_from_db()
        self.assertFalse(self.acc.phone)


class DevCodeOnlyInDevelopment(TestCase):
    """A05: без SMS-провайдера код 1234 принимается только в разработке."""

    def setUp(self):
        cache.clear()

    def test_prod_without_provider_rejects_dev_code(self):
        env = {"DJANGO_DEBUG": "0"}
        with mock.patch.dict(os.environ, env), mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SMS_PROVIDER", None)
            r = _post(self.client, "/v1/auth/phone/verify",
                      {"phone": "+79990004401", "code": "1234"})
        self.assertEqual(r.status_code, 401)
        self.assertFalse(Account.objects.filter(phone="+79990004401").exists())

    def test_dev_accepts_dev_code(self):
        with mock.patch.dict(os.environ, {"DJANGO_DEBUG": "1"}):
            os.environ.pop("SMS_PROVIDER", None)
            r = _post(self.client, "/v1/auth/phone/verify",
                      {"phone": "+79990004402", "code": "1234"})
        self.assertEqual(r.status_code, 200)
