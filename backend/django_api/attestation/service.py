"""Проверка подлинности приложения в режиме «наблюдение» (D-129).

Зачем. Все баллы сервер считает сам (S-04), но цифры забега присылает телефон.
Пересобранное приложение или эмулятор может прислать правдоподобную выдумку.
Play Integrity отвечает на два вопроса: запрос пришёл из НАШЕГО приложения
(подпись, пакет) и с настоящего телефона (не эмулятор, не взломанная прошивка).

Как устроено.
1. Перед отправкой пробежки приложение просит у Google Play токен, вшивая в него
   отпечаток запроса (`requestHash`) — sha256 от id забега и его цифр
   (`run_request_hash`). Подменить цифры, сохранив токен, нельзя: отпечаток не
   совпадёт. Перенести токен на другой забег — тоже.
2. Сервер принимает забег КАК ОБЫЧНО и сохраняет токен в `IntegrityCheck`.
3. Фоновая задача отдаёт токен Google и записывает вердикт.

Режим «наблюдение»: вердикт ничего не блокирует и баллы не меняет. Пометить
аккаунт на ревью при явных признаках подделки можно отдельным флагом
`PLAY_INTEGRITY_FLAG_REVIEW=1` (по умолчанию выключен) — решение всё равно
принимает модератор.

Старые сборки без токена и iOS работают как раньше (запись «без токена» /
«платформа пока не проверяется» — только при включённой проверке).

Окружение (кроме ключа из play.py):
  PLAY_INTEGRITY_FLAG_REVIEW   — 1: «есть признаки подделки» → аккаунт на ревью
  PLAY_INTEGRITY_CERT_SHA256   — отпечатки нашего ключа подписи (через запятую,
                                 hex или base64url, как отдаёт Google); задан —
                                 чужая подпись = «есть признаки подделки»
  PLAY_INTEGRITY_REQUIRE_PLAY  — 1: приложение не из Google Play = признак подделки
                                 (включать только когда раздача пойдёт через Play)
"""
import base64
import hashlib
import logging
import math
import os
from datetime import datetime, timedelta, timezone as dt_timezone

from django.db import IntegrityError, transaction
from django.utils import timezone

from . import play
from .models import IntegrityCheck

log = logging.getLogger(__name__)

# Токен выпущен перед отправкой; офлайн-очередь просит новый на каждую попытку.
MAX_TOKEN_AGE = timedelta(minutes=10)
FUTURE_SKEW = timedelta(minutes=2)
MAX_TOKEN_LEN = 8000

DEVICE_OK = {"MEETS_DEVICE_INTEGRITY", "MEETS_STRONG_INTEGRITY"}


def _flag(name):
    return (os.environ.get(name) or "").strip().lower() in ("1", "true", "yes", "on")


def enabled():
    return play.enabled()


def run_request_hash(run_id, distance_m, duration_s, finished_at_ms):
    """Отпечаток пробежки. ДОЛЖЕН совпадать с клиентом (integrity_service.dart).

    Метры — целые вниз (floor): у Dart и Python одинаково, в отличие от round.
    Нет времени финиша — пустое место.
    """
    ms = "" if finished_at_ms is None else str(int(finished_at_ms))
    raw = f"mata-run-v1|{run_id}|{math.floor(distance_m)}|{int(duration_s)}|{ms}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def record(uid, subject_type, subject_id, integrity, expected_hash):
    """Сохранить присланное приложением и поставить проверку в очередь.

    Ничего не бросает: сбой проверки подлинности не должен ронять приём забега.
    """
    if not enabled():
        return None
    try:
        integrity = integrity if isinstance(integrity, dict) else {}
        platform = str(integrity.get("platform") or "")[:10]
        token = integrity.get("token")
        token = token.strip() if isinstance(token, str) else ""
        if platform == "ios":
            status, token = "unsupported", ""  # App Attest — когда будет Apple Developer
        elif not token:
            status = "missing"
        elif len(token) > MAX_TOKEN_LEN:
            status, token = "bad", ""
        else:
            status = "pending"
        try:
            with transaction.atomic():
                check = IntegrityCheck.objects.create(
                    subject_type=subject_type, subject_id=subject_id, user_id=uid,
                    platform=platform, status=status, token=token,
                    expected_hash=expected_hash,
                    reasons="токен слишком длинный" if status == "bad" else "",
                )
        except IntegrityError:
            return None  # уже есть (повтор того же запроса)
        if status == "pending":
            from .tasks import verify_integrity

            transaction.on_commit(lambda: verify_integrity.delay(check.pk))
        return check
    except Exception:  # noqa: BLE001 — наблюдение не должно ломать приём
        log.exception("Проверка подлинности: не удалось сохранить токен")
        return None


def _same_cert(digest, allowed):
    """Google отдаёт отпечаток подписи в base64url; владельцу удобнее hex из keytool."""
    def norm(value):
        value = value.strip().replace(":", "")
        try:
            if len(value) == 64 and all(c in "0123456789abcdefABCDEF" for c in value):
                return bytes.fromhex(value)
            return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        except ValueError:
            return value.encode()
    return norm(digest) in {norm(a) for a in allowed if a.strip()}


def judge(payload, expected_hash, received_at):
    """Вердикт Google → (status, причины, устройство, приложение, установка)."""
    reasons = []
    req = payload.get("requestDetails") or {}
    app = payload.get("appIntegrity") or {}
    device = payload.get("deviceIntegrity") or {}
    account = payload.get("accountDetails") or {}

    if req.get("requestPackageName") != play.package_name():
        reasons.append("токен выпущен для другого приложения")
    if not expected_hash or req.get("requestHash") != expected_hash:
        reasons.append("отпечаток не совпал: токен от другого запроса или цифры подменены")
    try:
        issued = datetime.fromtimestamp(
            int(req.get("timestampMillis")) / 1000, tz=dt_timezone.utc)
    except (TypeError, ValueError, OverflowError):
        issued = None
    if issued is None:
        reasons.append("в токене нет времени выпуска")
    elif issued < received_at - MAX_TOKEN_AGE or issued > received_at + FUTURE_SKEW:
        reasons.append("токен несвежий (повтор старого)")

    labels = [str(v) for v in (device.get("deviceRecognitionVerdict") or [])]
    if not labels:
        reasons.append("устройство не прошло проверку (эмулятор или подмена)")
    elif not DEVICE_OK & set(labels):
        reasons.append("устройство прошло только базовую проверку (root или своя прошивка)")

    app_verdict = str(app.get("appRecognitionVerdict") or "")
    if app_verdict == "UNEVALUATED":
        reasons.append("Google не смог оценить приложение")
    allowed = (os.environ.get("PLAY_INTEGRITY_CERT_SHA256") or "").split(",")
    digests = app.get("certificateSha256Digest") or []
    if any(a.strip() for a in allowed) and digests and not any(
            _same_cert(d, allowed) for d in digests):
        reasons.append("приложение подписано чужим ключом (пересобрано)")
    if _flag("PLAY_INTEGRITY_REQUIRE_PLAY") and app_verdict != "PLAY_RECOGNIZED":
        reasons.append("приложение установлено не из Google Play")

    status = "bad" if reasons else "ok"
    return (status, "; ".join(reasons)[:300], ",".join(labels)[:200],
            app_verdict[:40], str(account.get("appLicensingVerdict") or "")[:40])


def verify(check_pk):
    """Фоновая проверка одной записи. Идемпотентно: проверенное не трогаем."""
    check = IntegrityCheck.objects.filter(pk=check_pk, status="pending").first()
    if check is None:
        return None
    try:
        payload = play.decode(check.token)
    except play.PlayIntegrityError as e:
        log.warning("Проверка подлинности %s не выполнена: %s", check.pk, e)
        check.status, check.reasons = "error", str(e)[:300]
        check.token, check.checked_at = "", timezone.now()
        check.save(update_fields=["status", "reasons", "token", "checked_at"])
        return check
    status, reasons, device, app, licensing = judge(payload, check.expected_hash,
                                                    check.created_at)
    check.status, check.reasons = status, reasons
    check.device, check.app, check.licensing = device, app, licensing
    check.verdict, check.token, check.checked_at = payload, "", timezone.now()
    check.save(update_fields=["status", "reasons", "device", "app", "licensing",
                              "verdict", "token", "checked_at"])
    if status == "bad" and _flag("PLAY_INTEGRITY_FLAG_REVIEW"):
        _send_to_review(check.user_id)
    return check


def _send_to_review(uid):
    from accounts.models import Account
    from common.cache import invalidate_user

    if Account.objects.filter(id=uid, needs_review=False).update(needs_review=True):
        invalidate_user(uid)  # баллы за активность заморожены (D-107) — кошелёк устарел
