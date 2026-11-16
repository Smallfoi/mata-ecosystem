"""Проверка подлинности приложения (D-129): режим «наблюдение».

Главное, что проверяем: проверка ничего не ломает и ничего не решает за модератора.
Забег принимается и с токеном, и без, и при недоступном Google; баллы от вердикта
не зависят. Вердикт честный: подмена цифр, чужой пакет, старый токен, эмулятор
и пересобранное приложение распознаются. Google замокан — живых ключей в тестах нет.
"""
import base64
import json
import os
import time
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from accounts.models import Account
from common.testutils import ApiTestCase
from runs.models import Run

from . import play
from .models import IntegrityCheck
from .service import judge, run_request_hash

_NOW_MS = int(time.time() * 1000)
_RUN = {"distanceMeters": 5000.7, "elapsedSeconds": 1800, "finishedAtMs": _NOW_MS}
_ON = {"PLAY_INTEGRITY_SA_KEY_B64": base64.b64encode(b'{"client_email":"a","private_key":"b"}').decode()}


def _payload(request_hash, **over):
    p = {
        "requestDetails": {"requestPackageName": "ru.mata.kvartal",
                           "requestHash": request_hash,
                           "timestampMillis": str(int(time.time() * 1000))},
        "appIntegrity": {"appRecognitionVerdict": "UNRECOGNIZED_VERSION",
                         "packageName": "ru.mata.kvartal",
                         "certificateSha256Digest": ["6a6a1474b5cbbb2b1aa57e0bc3"]},
        "deviceIntegrity": {"deviceRecognitionVerdict": ["MEETS_DEVICE_INTEGRITY"]},
        "accountDetails": {"appLicensingVerdict": "UNEVALUATED"},
    }
    for key, value in over.items():
        p[key] = {**p[key], **value}
    return p


class RequestHashTests(SimpleTestCase):
    def test_matches_client_formula(self):
        """Та же строка, что собирает integrity_service.dart (метры — вниз)."""
        import hashlib

        raw = "mata-run-v1|r1|5000|1800|1700000000000"
        self.assertEqual(run_request_hash("r1", 5000.99, 1800, 1700000000000),
                         hashlib.sha256(raw.encode()).hexdigest())

    def test_no_finish_time_is_empty_slot(self):
        import hashlib

        self.assertEqual(run_request_hash("r1", 10.0, 5, None),
                         hashlib.sha256(b"mata-run-v1|r1|10|5|").hexdigest())

    def test_changed_numbers_change_hash(self):
        a = run_request_hash("r1", 5000, 1800, 1)
        self.assertNotEqual(a, run_request_hash("r1", 9000, 1800, 1))
        self.assertNotEqual(a, run_request_hash("r2", 5000, 1800, 1))


class JudgeTests(SimpleTestCase):
    h = "a" * 64

    def _status(self, payload, env=None):
        with mock.patch.dict(os.environ, env or {}, clear=False):
            return judge(payload, self.h, timezone.now())

    def test_genuine_phone_outside_play_is_ok(self):
        """Раздача APK не через Play — UNRECOGNIZED_VERSION не повод для подозрений."""
        status, reasons, device, app, _ = self._status(_payload(self.h))
        self.assertEqual((status, reasons), ("ok", ""))
        self.assertEqual(device, "MEETS_DEVICE_INTEGRITY")
        self.assertEqual(app, "UNRECOGNIZED_VERSION")

    def test_tampered_numbers(self):
        status, reasons, *_ = self._status(_payload("b" * 64))
        self.assertEqual(status, "bad")
        self.assertIn("отпечаток", reasons)

    def test_other_package(self):
        status, reasons, *_ = self._status(
            _payload(self.h, requestDetails={"requestPackageName": "com.evil"}))
        self.assertEqual(status, "bad")
        self.assertIn("другого приложения", reasons)

    def test_stale_token(self):
        old = str(int((time.time() - 3600) * 1000))
        status, reasons, *_ = self._status(_payload(self.h, requestDetails={"timestampMillis": old}))
        self.assertEqual(status, "bad")
        self.assertIn("несвежий", reasons)

    def test_emulator(self):
        status, reasons, *_ = self._status(
            _payload(self.h, deviceIntegrity={"deviceRecognitionVerdict": []}))
        self.assertEqual(status, "bad")
        self.assertIn("эмулятор", reasons)

    def test_rooted_basic_only(self):
        status, reasons, *_ = self._status(
            _payload(self.h, deviceIntegrity={"deviceRecognitionVerdict": ["MEETS_BASIC_INTEGRITY"]}))
        self.assertEqual(status, "bad")
        self.assertIn("root", reasons)

    def test_foreign_signature_when_ours_known(self):
        ours = "AB" * 32  # hex, как печатает keytool
        status, reasons, *_ = self._status(_payload(self.h), {"PLAY_INTEGRITY_CERT_SHA256": ours})
        self.assertEqual(status, "bad")
        self.assertIn("чужим ключом", reasons)

    def test_our_signature_hex_equals_google_base64url(self):
        raw = bytes(range(32))
        google = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
        payload = _payload(self.h, appIntegrity={"certificateSha256Digest": [google]})
        status, *_ = self._status(payload, {"PLAY_INTEGRITY_CERT_SHA256": raw.hex().upper()})
        self.assertEqual(status, "ok")

    def test_require_play_switch(self):
        status, reasons, *_ = self._status(_payload(self.h), {"PLAY_INTEGRITY_REQUIRE_PLAY": "1"})
        self.assertEqual(status, "bad")
        self.assertIn("не из Google Play", reasons)


class JwtTests(SimpleTestCase):
    def test_signed_jwt_verifies_with_service_account_key(self):
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding, rsa

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption()).decode()
        info = {"client_email": "sa@p.iam.gserviceaccount.com", "private_key": pem,
                "private_key_id": "k1", "token_uri": "https://oauth2.googleapis.com/token"}
        jwt = play._signed_jwt(info, now=1000)
        head, body, sig = jwt.split(".")
        pad = lambda s: s + "=" * (-len(s) % 4)  # noqa: E731
        claims = json.loads(base64.urlsafe_b64decode(pad(body)))
        self.assertEqual(claims["iss"], info["client_email"])
        self.assertEqual(claims["scope"], play.SCOPE)
        self.assertEqual(claims["exp"], 4600)
        key.public_key().verify(base64.urlsafe_b64decode(pad(sig)), f"{head}.{body}".encode(),
                                padding.PKCS1v15(), hashes.SHA256())  # не бросает = подпись верна

    def test_bad_key_is_explained(self):
        with mock.patch.dict(os.environ, {"PLAY_INTEGRITY_SA_KEY_B64": "не base64"}):
            with self.assertRaises(play.PlayIntegrityError):
                play._service_account()


@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
class RunUploadTests(ApiTestCase):
    """Проверка подлинности уходит в Celery (`verify_integrity.delay`).

    EAGER форсим, как в `notifications.PushTaskTests`: без него задача уходит
    РЕАЛЬНОМУ воркеру всюду, где поднят брокер, — то есть на машине разработчика
    с dev-стеком, — и `play.decode` в тестовом процессе не вызывается. В CI
    брокера нет, `CELERY_TASK_ALWAYS_EAGER = not CELERY_BROKER_URL` сам включает
    inline, и тесты зеленеют. Такой тест зелёный там, где его смотрят реже всего.
    """

    phone = "+79990002901"

    def _post(self, rid, integrity=None, body=None):
        data = {"id": rid, **(body or _RUN)}
        if integrity is not None:
            data["integrity"] = integrity
        with self.captureOnCommitCallbacks(execute=True):
            return self.api_post("/v1/runs", data)

    def _hash(self, rid):
        return run_request_hash(rid, _RUN["distanceMeters"], _RUN["elapsedSeconds"], _NOW_MS)

    def test_disabled_without_key_stores_nothing(self):
        with mock.patch.dict(os.environ, {"PLAY_INTEGRITY_SA_KEY_B64": ""}):
            r = self._post("i0", {"platform": "android", "token": "t"})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(IntegrityCheck.objects.exists())

    def test_genuine_token_recorded_and_points_unchanged(self):
        with mock.patch.dict(os.environ, _ON), \
                mock.patch.object(play, "decode", return_value=_payload(self._hash("i1"))) as dec:
            r = self._post("i1", {"platform": "android", "token": "tok"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["pointsAwarded"], 50)
        dec.assert_called_once_with("tok")
        c = IntegrityCheck.objects.get(subject_id="i1")
        self.assertEqual(c.status, "ok")
        self.assertEqual(c.token, "")  # токен после проверки не храним
        self.assertEqual(c.user_id, self.uid)

    def test_bad_verdict_observes_only_by_default(self):
        """Признаки подделки: баллы те же, аккаунт на ревью НЕ уходит без флага."""
        with mock.patch.dict(os.environ, _ON), \
                mock.patch.object(play, "decode", return_value=_payload("f" * 64)):
            r = self._post("i2", {"platform": "android", "token": "tok"})
        self.assertEqual(r.json()["pointsAwarded"], 50)
        self.assertFalse(Run.objects.get(id="i2").flagged)
        self.assertEqual(IntegrityCheck.objects.get(subject_id="i2").status, "bad")
        self.assertFalse(Account.objects.get(id=self.uid).needs_review)

    def test_flag_switch_sends_account_to_review(self):
        env = {**_ON, "PLAY_INTEGRITY_FLAG_REVIEW": "1"}
        with mock.patch.dict(os.environ, env), \
                mock.patch.object(play, "decode", return_value=_payload("f" * 64)):
            self._post("i3", {"platform": "android", "token": "tok"})
        self.assertTrue(Account.objects.get(id=self.uid).needs_review)

    def test_google_down_is_error_not_verdict(self):
        env = {**_ON, "PLAY_INTEGRITY_FLAG_REVIEW": "1"}
        with mock.patch.dict(os.environ, env), \
                mock.patch.object(play, "decode", side_effect=play.PlayIntegrityError("timeout")):
            r = self._post("i4", {"platform": "android", "token": "tok"})
        self.assertEqual(r.status_code, 200)
        c = IntegrityCheck.objects.get(subject_id="i4")
        self.assertEqual(c.status, "error")
        self.assertFalse(Account.objects.get(id=self.uid).needs_review)

    def test_old_build_without_token(self):
        with mock.patch.dict(os.environ, _ON), mock.patch.object(play, "decode") as dec:
            r = self._post("i5")
        self.assertEqual(r.status_code, 200)
        dec.assert_not_called()
        self.assertEqual(IntegrityCheck.objects.get(subject_id="i5").status, "missing")

    def test_ios_waits_for_app_attest(self):
        with mock.patch.dict(os.environ, _ON), mock.patch.object(play, "decode") as dec:
            self._post("i6", {"platform": "ios", "token": "x"})
        dec.assert_not_called()
        c = IntegrityCheck.objects.get(subject_id="i6")
        self.assertEqual((c.status, c.token), ("unsupported", ""))

    def test_duplicate_upload_does_not_recheck(self):
        with mock.patch.dict(os.environ, _ON), \
                mock.patch.object(play, "decode", return_value=_payload(self._hash("i7"))) as dec:
            self._post("i7", {"platform": "android", "token": "tok"})
            r = self._post("i7", {"platform": "android", "token": "tok2"})
        self.assertTrue(r.json()["duplicate"])
        self.assertEqual(dec.call_count, 1)
        self.assertEqual(IntegrityCheck.objects.filter(subject_id="i7").count(), 1)

    def test_broken_integrity_field_never_breaks_upload(self):
        with mock.patch.dict(os.environ, _ON):
            r = self._post("i8", "строка вместо объекта")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(IntegrityCheck.objects.get(subject_id="i8").status, "missing")


class AccessTokenTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_access_token_is_cached(self):
        with mock.patch.object(play, "_service_account", return_value={"client_email": "a"}), \
                mock.patch.object(play, "_signed_jwt", return_value="jwt"), \
                mock.patch.object(play, "_post", return_value={"access_token": "AT",
                                                               "expires_in": 3600}) as post:
            self.assertEqual(play.access_token(), "AT")
            self.assertEqual(play.access_token(), "AT")
        self.assertEqual(post.call_count, 1)

    def test_decode_sends_token_to_package_url(self):
        with mock.patch.object(play, "access_token", return_value="AT"), \
                mock.patch.object(play, "_post", return_value={"tokenPayloadExternal": {"x": 1}}) as post:
            self.assertEqual(play.decode("tok"), {"x": 1})
        url, data, headers = post.call_args.args
        self.assertEqual(url, "https://playintegrity.googleapis.com/v1/ru.mata.kvartal:decodeIntegrityToken")
        self.assertEqual(json.loads(data), {"integrity_token": "tok"})
        self.assertEqual(headers["Authorization"], "Bearer AT")
