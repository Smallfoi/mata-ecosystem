# -*- coding: utf-8 -*-
"""Клиент COROS: саморегистрация, вход пользователя и вызов инструментов MCP.

Чем COROS отличается от Suunto. У Suunto обычный REST и вебхуки — они сами
присылают тренировку. У COROS ни того, ни другого: разговор идёт по **MCP**
(вызовы инструментов поверх JSON-RPC), а о новых тренировках мы узнаём, только
если спросим сами. Зато заявка и одобрение не нужны вовсе.

Три вещи, которых нет у других партнёров и которые делают подключение возможным
без единого действия владельца:

1. **Саморегистрация.** Их сервер публикует точку `/connect/register` (RFC 7591):
   мы программно заводим себе приложение и получаем client_id/secret. Ключи в
   Lockbox класть не нужно — их просто никто не выдаёт руками.
2. **PKCE обязателен** (только S256). Это защита от подмены кода на обратном
   пути: код без нашего секрета-проверки чужому бесполезен.
3. **`offline_access`** в разрешениях — значит доступ продлевается, и человека не
   придётся просить входить заново каждый час.

Адреса берём не из документации, а из их же метаданных: сервер публикует их по
стандартному адресу, и если COROS что-то поменяет, мы это увидим, а не сломаемся.
"""
import base64
import hashlib
import json
import os
import secrets
import urllib.parse
import urllib.request
from datetime import timedelta

from django.core.cache import cache
from django.utils import timezone

MCP_URL = os.environ.get("COROS_MCP_URL") or "https://mcp.coros.com/mcp"
METADATA_URL = (os.environ.get("COROS_MCP_METADATA")
                or "https://mcp.coros.com/.well-known/oauth-authorization-server")
SCOPES = "openid mcp.tools offline_access"
PROTOCOL_VERSION = "2025-06-18"
TIMEOUT_S = 30

# Метаданные сервера меняются раз в год, а запрашивать их на каждый вход незачем.
METADATA_TTL = 24 * 3600
_METADATA_KEY = "coros:oauth-metadata"


class CorosError(RuntimeError):
    """COROS ответил отказом или не ответил вовсе."""


def _request(url, data=None, headers=None, method="GET"):
    body = None
    if data is not None:
        body = data if isinstance(data, bytes) else json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, method=method)
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            raw = resp.read()
            return raw, dict(resp.headers)
    except urllib.error.HTTPError as e:
        detail = (e.read() or b"")[:300].decode(errors="replace")
        raise CorosError(f"COROS {e.code}: {detail}") from e
    except Exception as e:
        raise CorosError(f"COROS недоступен: {e}") from e


def metadata() -> dict:
    """Адреса авторизации — из метаданных сервера, а не зашитые в код."""
    cached = cache.get(_METADATA_KEY)
    if cached:
        return cached
    raw, _ = _request(METADATA_URL, headers={"Accept": "application/json"})
    data = json.loads(raw.decode() or "{}")
    if not data.get("authorization_endpoint") or not data.get("token_endpoint"):
        raise CorosError("метаданные COROS без адресов авторизации")
    cache.set(_METADATA_KEY, data, METADATA_TTL)
    return data


# ── Саморегистрация приложения ─────────────────────────────────────────────

def register_client(redirect_uri: str) -> dict:
    """Завести себе приложение у COROS. Делается один раз на всю установку."""
    endpoint = metadata().get("registration_endpoint")
    if not endpoint:
        raise CorosError("COROS не отдаёт точку саморегистрации")
    raw, _ = _request(
        endpoint,
        data={
            "client_name": "MATA Kvartal",
            "redirect_uris": [redirect_uri],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "client_secret_post",
            "scope": SCOPES,
        },
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    data = json.loads(raw.decode() or "{}")
    if not data.get("client_id"):
        raise CorosError("COROS не выдал client_id при регистрации")
    return data


# ── Вход пользователя ──────────────────────────────────────────────────────

def make_pkce() -> tuple[str, str]:
    """Секрет-проверка и её отпечаток: без них COROS код не примет."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).decode().rstrip("=")
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return verifier, challenge


def authorize_url(client_id: str, redirect_uri: str, state: str, challenge: str) -> str:
    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": SCOPES,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return metadata()["authorization_endpoint"] + "?" + urllib.parse.urlencode(params)


def exchange_code(client_id, client_secret, code, redirect_uri, verifier) -> dict:
    return _token_request({
        "grant_type": "authorization_code",
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": redirect_uri,
        "code_verifier": verifier,
    })


def refresh_tokens(client_id, client_secret, refresh_token) -> dict:
    return _token_request({
        "grant_type": "refresh_token",
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
    })


def _token_request(form: dict) -> dict:
    raw, _ = _request(
        metadata()["token_endpoint"],
        data=urllib.parse.urlencode(form).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded",
                 "Accept": "application/json"},
        method="POST",
    )
    return json.loads(raw.decode() or "{}")


def expires_at(token_response: dict):
    try:
        seconds = int(token_response.get("expires_in") or 0)
    except (TypeError, ValueError):
        seconds = 0
    return timezone.now() + timedelta(seconds=seconds or 3600)


# ── Разговор по MCP ────────────────────────────────────────────────────────

def _parse_rpc(raw: bytes) -> dict:
    """Ответ приходит либо чистым JSON, либо потоком событий (SSE).

    В потоке нас интересуют строки `data:` — в них и лежит сам ответ.
    """
    text = raw.decode(errors="replace").strip()
    if not text:
        return {}
    if text.startswith("{"):
        return json.loads(text)
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            payload = line[5:].strip()
            if payload and payload != "[DONE]":
                return json.loads(payload)
    return {}


def call_tool(access_token: str, name: str, arguments: dict | None = None) -> dict:
    """Вызвать инструмент MCP и вернуть его ответ.

    Рукопожатие (`initialize`) не делаем намеренно: сервер COROS принимает вызов
    инструмента сразу, а лишний запрос — это треть секунды и ещё одна точка отказа.
    Если когда-нибудь начнёт требовать — отвалится понятной ошибкой, а не тишиной.
    """
    body = {
        "jsonrpc": "2.0",
        "id": secrets.randbelow(1 << 30) + 1,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments or {}},
    }
    raw, _ = _request(
        MCP_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": PROTOCOL_VERSION,
        },
        method="POST",
    )
    answer = _parse_rpc(raw)
    if answer.get("error"):
        raise CorosError(str(answer["error"])[:300])
    return answer.get("result") or {}


def tool_payload(result: dict):
    """Содержимое ответа инструмента.

    MCP заворачивает ответ в список кусков; данные приходят либо готовым объектом
    (`structuredContent`), либо текстом, в котором лежит JSON.
    """
    if not isinstance(result, dict):
        return None
    if isinstance(result.get("structuredContent"), (dict, list)):
        return result["structuredContent"]
    for chunk in result.get("content") or []:
        if not isinstance(chunk, dict):
            continue
        text = chunk.get("text")
        if not text:
            continue
        try:
            return json.loads(text)
        except (ValueError, TypeError):
            return text
    return None
