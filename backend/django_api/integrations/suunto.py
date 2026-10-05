# -*- coding: utf-8 -*-
"""Клиент Suunto Cloud API: авторизация пользователя и запросы от его имени.

Suunto приняли нас в партнёрскую программу 05.10.2026 (D-108, WEARABLES_PARTNERS).
Схема простая: человек разрешает доступ в своём аккаунте Suunto, нам возвращается
код, мы меняем его на токен и дальше ходим в их API от его имени.

Два ключа в каждом запросе, и это не одно и то же:
- **токен пользователя** (Bearer) — чей именно аккаунт мы читаем;
- **ключ подписки приложения** (`Ocp-Apim-Subscription-Key`) — кто спрашивает.
Без второго их шлюз (Azure API Management) отвечает 401 даже с верным токеном.

Ключи живут в окружении (Lockbox): репозиторий публичный, здесь их нет и не будет.
"""
import json
import os
import urllib.parse
import urllib.request
from datetime import timedelta

from django.utils import timezone

AUTHORIZE_URL = "https://cloudapi-oauth.suunto.com/oauth/authorize"
TOKEN_URL = "https://cloudapi-oauth.suunto.com/oauth/token"
API_BASE = "https://cloudapi.suunto.com"

# Токен живёт недолго; обновляем заранее, чтобы не упереться в отказ на середине
# разбора тренировки.
REFRESH_MARGIN = timedelta(minutes=5)
TIMEOUT_S = 20


class SuuntoError(RuntimeError):
    """Suunto ответила отказом или не ответила вовсе."""


def client_id() -> str:
    return (os.environ.get("SUUNTO_CLIENT_ID") or "").strip()


def client_secret() -> str:
    return (os.environ.get("SUUNTO_CLIENT_SECRET") or "").strip()


def subscription_key() -> str:
    return (os.environ.get("SUUNTO_SUBSCRIPTION_KEY") or "").strip()


def configured() -> bool:
    """Все три ключа на месте — значит подключение можно предлагать людям."""
    return bool(client_id() and client_secret() and subscription_key())


def redirect_uri() -> str:
    """Адрес возврата. Он же вписан в кабинете Suunto — должен совпадать дословно."""
    base = (os.environ.get("PUBLIC_API_BASE") or "https://api.mata-club.ru").rstrip("/")
    return f"{base}/v1/integrations/suunto/callback"


def authorize_url(state: str) -> str:
    """Куда отправить человека, чтобы он разрешил доступ."""
    params = {
        "client_id": client_id(),
        "response_type": "code",
        "redirect_uri": redirect_uri(),
        "scope": "workout",
        "state": state,
    }
    return AUTHORIZE_URL + "?" + urllib.parse.urlencode(params)


def _post_form(url: str, data: dict) -> dict:
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            return json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:                      # отказ с телом ответа
        detail = (e.read() or b"")[:300].decode(errors="replace")
        raise SuuntoError(f"Suunto {e.code}: {detail}") from e
    except Exception as e:                                   # сеть, таймаут, мусор
        raise SuuntoError(f"Suunto недоступна: {e}") from e


def exchange_code(code: str) -> dict:
    """Код с их страницы → токены. Возвращает ответ Suunto как есть."""
    return _post_form(TOKEN_URL, {
        "grant_type": "authorization_code",
        "client_id": client_id(),
        "client_secret": client_secret(),
        "code": code,
        "redirect_uri": redirect_uri(),
    })


def refresh_tokens(refresh_token: str) -> dict:
    """Продлить доступ, когда срок токена вышел."""
    return _post_form(TOKEN_URL, {
        "grant_type": "refresh_token",
        "client_id": client_id(),
        "client_secret": client_secret(),
        "refresh_token": refresh_token,
    })


def api_get(path: str, access_token: str, params: dict | None = None):
    """Запрос к их API от имени пользователя.

    Возвращает разобранный JSON, а для файлов (FIT) — байты: по типу ответа.
    """
    url = API_BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, method="GET")
    req.add_header("Authorization", f"Bearer {access_token}")
    req.add_header("Ocp-Apim-Subscription-Key", subscription_key())
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            raw = resp.read()
            ctype = (resp.headers.get("Content-Type") or "").lower()
            if "json" in ctype:
                return json.loads(raw.decode() or "{}")
            return raw
    except urllib.error.HTTPError as e:
        detail = (e.read() or b"")[:300].decode(errors="replace")
        raise SuuntoError(f"Suunto {e.code}: {detail}") from e
    except Exception as e:
        raise SuuntoError(f"Suunto недоступна: {e}") from e


def expires_at(token_response: dict):
    """Когда токен перестанет работать. Нет срока в ответе — считаем час."""
    try:
        seconds = int(token_response.get("expires_in") or 0)
    except (TypeError, ValueError):
        seconds = 0
    return timezone.now() + timedelta(seconds=seconds or 3600)
