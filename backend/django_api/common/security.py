"""
JWT и пароли — БАЙТ-В-БАЙТ как в FastAPI (backend/main.py), чтобы токены и хэши были
совместимы при переключении приложений с FastAPI на Django (D-12).
HS256, payload {sub, exp}, секрет JWT_SECRET (env, дефолт совпадает с FastAPI).
Пароли: pbkdf2_hmac sha256, 100k, формат "salt$hex".
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time

JWT_SECRET = os.environ.get("JWT_SECRET", "dev-secret-change-in-prod")
JWT_TTL = 60 * 60 * 24 * 30  # 30 дней


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000)
    return f"{salt}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, _ = stored.split("$", 1)
    except (ValueError, AttributeError):
        return False
    return hmac.compare_digest(stored, hash_password(password, salt))


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def make_token(user_id: str, version: int = 0) -> str:
    """Токен входа. `version` — версия сессий аккаунта (Account.token_version): её
    поднимает смена пароля, и все выданные раньше токены перестают действовать.
    Нулевую версию в токен не пишем — так он байт-в-байт прежнего формата."""
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body = {"sub": user_id, "exp": int(time.time()) + JWT_TTL}
    if version:
        body["v"] = version
    payload = _b64url(json.dumps(body).encode())
    sig = _b64url(hmac.new(JWT_SECRET.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest())
    return f"{header}.{payload}.{sig}"


def user_id_from_request(request) -> str | None:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth.split(" ", 1)[1]
    try:
        header, payload, sig = token.split(".")
        expected = _b64url(
            hmac.new(JWT_SECRET.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest()
        )
        if not hmac.compare_digest(sig, expected):
            return None
        data = json.loads(base64.urlsafe_b64decode(payload + "=="))
        if data.get("exp", 0) < time.time():
            return None
        uid = data["sub"]
        # Мгновенный бан (S-10): заблокированный теряет доступ, не дожидаясь
        # истечения 30-дневного токена. Аудит 27.09.2026 (A02): так же — удалённый
        # аккаунт (подпись верная, а хозяина нет) и токен старой версии сессий
        # (пароль с тех пор меняли). Кэш 60с — без удара по БД на каждый запрос.
        if not _session_alive(uid, int(data.get("v") or 0)):
            return None
        return uid
    except Exception:
        return None


def _state_key(uid) -> str:
    return f"acc_state:{uid}"


def forget_account(uid) -> None:
    """Сбросить закэшированное состояние аккаунта — сразу после бана, удаления или
    смены пароля, чтобы старые токены не жили ещё минуту."""
    try:
        from django.core.cache import cache

        cache.delete(_state_key(uid))
    except Exception:
        pass


def _session_alive(uid, version: int) -> bool:
    """Действует ли токен: аккаунт есть, не заблокирован, версия сессий совпадает.

    Сбой кэша/БД → действует (нельзя залочить всех из-за хиккапа инфраструктуры).
    """
    try:
        from django.core.cache import cache

        key = _state_key(uid)
        state = cache.get(key)
        if state is None:
            from accounts.models import Account

            row = Account.objects.filter(id=uid).values_list(
                "is_blocked", "token_version").first()
            # (живой ли аккаунт, версия сессий). Нет строки — аккаунт удалён.
            state = (False, 0) if row is None else (not row[0], row[1] or 0)
            cache.set(key, state, 60)
        alive, current = state
        return bool(alive) and current == version
    except Exception:
        return True


def normalize_phone(phone: str) -> str:
    digits = "".join(ch for ch in phone if ch.isdigit())
    if len(digits) == 10:
        digits = "7" + digits
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    return f"+{digits}" if digits else phone.strip()


def synthetic_email_for_phone(phone: str) -> str:
    digits = "".join(ch for ch in phone if ch.isdigit())
    return f"runner_{digits}@kvartal.local"


def new_user_id() -> str:
    return f"u_{secrets.token_hex(8)}"
