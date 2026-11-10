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
from datetime import datetime, timedelta
from datetime import timezone as dt_tz

from django.utils import timezone

AUTHORIZE_URL = "https://cloudapi-oauth.suunto.com/oauth/authorize"
TOKEN_URL = "https://cloudapi-oauth.suunto.com/oauth/token"
API_BASE = "https://cloudapi.suunto.com"

# Токен живёт недолго; обновляем заранее, чтобы не упереться в отказ на середине
# разбора тренировки.
REFRESH_MARGIN = timedelta(minutes=5)
TIMEOUT_S = 20

# Пути их API. Портал отдаёт их только скриптом, в открытой документации версия
# указана по-разному (v2 и v3), поэтому держим в настройках: первый живой прогон
# покажет верный, и менять придётся переменную окружения, а не код.
# Проверить, какой отвечает, можно командой `manage.py suunto_probe`.
WORKOUT_PATH = os.environ.get("SUUNTO_WORKOUT_PATH") or "/v2/workout/{id}"
WORKOUTS_PATH = os.environ.get("SUUNTO_WORKOUTS_PATH") or "/v2/workouts"
FIT_PATH = os.environ.get("SUUNTO_FIT_PATH") or "/v2/workout/exportFit/{id}"


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


def fetch_workout(access_token: str, workout_id: str) -> dict:
    """Сводка одной тренировки: дистанция, время, пульс, вид спорта."""
    data = api_get(WORKOUT_PATH.format(id=urllib.parse.quote(str(workout_id))), access_token)
    if isinstance(data, dict):
        # У них ответ встречается и «как есть», и завёрнутым в payload.
        return data.get("payload") if isinstance(data.get("payload"), dict) else data
    return {}


def download_fit(access_token: str, workout_id: str) -> bytes:
    """FIT-файл тренировки: в нём лежит полный трек с координатами."""
    raw = api_get(FIT_PATH.format(id=urllib.parse.quote(str(workout_id))), access_token)
    return raw if isinstance(raw, (bytes, bytearray)) else b""


def _num(raw, *names):
    """Первое число из перечисленных полей: названия у них разнятся по версиям."""
    for name in names:
        value = raw.get(name)
        if value in (None, ""):
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def to_workout(raw: dict, workout_id: str) -> dict | None:
    """Ответ Suunto → вид, который принимает наш импорт (`workouts.service`).

    Возвращает None, если тренировку нечего засчитывать: без дистанции и времени
    это не пробежка, а, например, запись сна.
    """
    if not isinstance(raw, dict):
        return None
    distance = _num(raw, "totalDistance", "distance") or 0
    duration = _num(raw, "totalTime", "duration", "movingTime") or 0
    started_ms = _num(raw, "startTime", "startTimeMillis", "timestamp") or 0
    if distance <= 0 or duration <= 0 or started_ms <= 0:
        return None
    # Время у них в миллисекундах; секунды тоже встречаются — отличаем по порядку.
    if started_ms < 1e11:
        started_ms *= 1000
    avg_hr = _num(raw, "hrAvg", "avgHr", "averageHeartRate")
    max_hr = _num(raw, "hrMax", "maxHr", "maxHeartRate")
    calories = _num(raw, "energyConsumption", "calories")
    # Пульс приходит и в ударах в минуту, и в ударах в секунду (их «hrAvg»).
    if avg_hr is not None and avg_hr < 10:
        avg_hr *= 60
    if max_hr is not None and max_hr < 10:
        max_hr *= 60
    return {
        "source_id": str(workout_id)[:120],
        "started_at": datetime.fromtimestamp(started_ms / 1000, tz=dt_tz.utc),
        "duration_s": int(duration),
        "distance_m": float(distance),
        "sport": _sport(raw),
        "avg_hr": int(avg_hr) if avg_hr else None,
        "max_hr": int(max_hr) if max_hr else None,
        "calories": int(calories) if calories else None,
    }


# Их вид спорта приходит числом (activityId) или строкой. Нас интересует одно:
# бег это или нет — за бег начисляются баллы, остальное просто показываем.
RUNNING_ACTIVITY_IDS = {1, 2, 3, 11, 13}       # бег, трейл, беговая дорожка, ходьба


def _sport(raw: dict) -> str:
    value = raw.get("activityId")
    if isinstance(value, (int, float)):
        return "run" if int(value) in RUNNING_ACTIVITY_IDS else "other"
    text = str(raw.get("activityType") or raw.get("sport") or "").strip().lower()
    if not text:
        return ""
    return "run" if "run" in text or "walk" in text else text[:30]


def expires_at(token_response: dict):
    """Когда токен перестанет работать. Нет срока в ответе — считаем час."""
    try:
        seconds = int(token_response.get("expires_in") or 0)
    except (TypeError, ValueError):
        seconds = 0
    return timezone.now() + timedelta(seconds=seconds or 3600)
