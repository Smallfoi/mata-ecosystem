"""Клиент Google Play Integrity API: расшифровка токена на стороне Google (D-129).

Токен, который приложение получило от Google Play на телефоне, сервер не
разбирает сам: отправляет его в Google (`decodeIntegrityToken`) от имени
сервис-аккаунта и получает вердикт. Так ключи расшифровки остаются у Google,
а у нас — только ключ сервис-аккаунта.

Настройка (окружение; на проде — секреты сервера / Lockbox):
  PLAY_INTEGRITY_SA_KEY_B64 — ключ сервис-аккаунта Google (JSON, закодированный
                              base64 одной строкой: многострочный JSON ломает .env)
  PLAY_INTEGRITY_PACKAGE    — имя пакета приложения (по умолчанию ru.mata.kvartal)
Без ключа проверка выключена целиком: `enabled()` → False, токены не принимаем.

Без новых HTTP-библиотек (urllib); подпись JWT — cryptography.
"""
import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from django.core.cache import cache

SCOPE = "https://www.googleapis.com/auth/playintegrity"
DECODE_URL = "https://playintegrity.googleapis.com/v1/{package}:decodeIntegrityToken"
DEFAULT_PACKAGE = "ru.mata.kvartal"
TIMEOUT = 15
_TOKEN_CACHE_KEY = "play_integrity_access_token"


class PlayIntegrityError(Exception):
    """Проверку выполнить не удалось (сеть, ключ, ответ Google) — не вердикт."""


def package_name():
    return (os.environ.get("PLAY_INTEGRITY_PACKAGE") or DEFAULT_PACKAGE).strip()


def _service_account():
    raw = (os.environ.get("PLAY_INTEGRITY_SA_KEY_B64") or "").strip()
    if not raw:
        return None
    try:
        info = json.loads(base64.b64decode(raw).decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise PlayIntegrityError("PLAY_INTEGRITY_SA_KEY_B64: не base64 от JSON-ключа") from e
    for key in ("client_email", "private_key"):
        if not info.get(key):
            raise PlayIntegrityError(f"В ключе сервис-аккаунта нет поля {key}")
    return info


def enabled():
    return bool((os.environ.get("PLAY_INTEGRITY_SA_KEY_B64") or "").strip())


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _signed_jwt(info, now=None):
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    now = int(now or time.time())
    header = {"alg": "RS256", "typ": "JWT"}
    if info.get("private_key_id"):
        header["kid"] = info["private_key_id"]
    claims = {
        "iss": info["client_email"],
        "scope": SCOPE,
        "aud": info.get("token_uri") or "https://oauth2.googleapis.com/token",
        "iat": now,
        "exp": now + 3600,
    }
    signing_input = (_b64url(json.dumps(header, separators=(",", ":")).encode())
                     + "." + _b64url(json.dumps(claims, separators=(",", ":")).encode()))
    try:
        key = serialization.load_pem_private_key(info["private_key"].encode(), password=None)
    except ValueError as e:
        raise PlayIntegrityError("Ключ сервис-аккаунта не читается") from e
    sig = key.sign(signing_input.encode("ascii"), padding.PKCS1v15(), hashes.SHA256())
    return signing_input + "." + _b64url(sig)


def _post(url, data: bytes, headers):
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:  # noqa: S310 (https, адрес наш)
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:300]
        raise PlayIntegrityError(f"Google ответил {e.code}: {body}") from e
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        raise PlayIntegrityError(f"Google недоступен: {e}") from e


def access_token():
    cached = cache.get(_TOKEN_CACHE_KEY)
    if cached:
        return cached
    info = _service_account()
    if info is None:
        raise PlayIntegrityError("Проверка выключена: нет PLAY_INTEGRITY_SA_KEY_B64")
    body = urllib.parse.urlencode({
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": _signed_jwt(info),
    }).encode()
    data = _post(info.get("token_uri") or "https://oauth2.googleapis.com/token", body,
                 {"Content-Type": "application/x-www-form-urlencoded"})
    token = data.get("access_token")
    if not token:
        raise PlayIntegrityError("Google не выдал токен доступа")
    # Токен живёт час; берём с запасом.
    cache.set(_TOKEN_CACHE_KEY, token, max(60, int(data.get("expires_in", 3600)) - 300))
    return token


def decode(integrity_token: str) -> dict:
    """Вердикт Google по токену: словарь tokenPayloadExternal."""
    url = DECODE_URL.format(package=urllib.parse.quote(package_name(), safe=""))
    data = _post(url, json.dumps({"integrity_token": integrity_token}).encode(), {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access_token()}",
    })
    payload = data.get("tokenPayloadExternal")
    if not isinstance(payload, dict):
        raise PlayIntegrityError("В ответе Google нет tokenPayloadExternal")
    return payload
