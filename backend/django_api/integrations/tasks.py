# -*- coding: utf-8 -*-
"""Фоновый приём тренировок с часов.

Suunto присылает уведомление «у пользователя X появилась тренировка Y» и ждёт
быстрый ответ. Ходить за самой тренировкой прямо в обработчике нельзя: их API
отвечает не мгновенно, а отправитель по таймауту сочтёт доставку неудачной и
начнёт повторять. Поэтому обработчик только ставит задачу, а работа идёт здесь.

Уведомлению мы не верим на слово — и не обязаны: в нём нет данных тренировки,
только кто и что. Сами данные забираем своим токеном у Suunto. Подделать
уведомление можно, но смысла нет: максимум мы лишний раз спросим про тренировку,
которая и так существует у этого человека.
"""
import logging
from datetime import datetime, timedelta
from datetime import timezone as dt_tz

from celery import shared_task
from django.utils import timezone

from integrations import coros
from integrations import fit as fitlib
from integrations import suunto
from integrations.models import McpClient, WatchAccount
from workouts import trust
from workouts.models import ExternalWorkout

log = logging.getLogger(__name__)


def _fresh_token(account: WatchAccount) -> str:
    """Токен, который точно ещё жив: просроченный продлеваем на месте."""
    if not account.expired:
        return account.access_token
    if not account.refresh_token:
        raise suunto.SuuntoError("токен истёк, а продлить нечем — нужно переподключить часы")
    tokens = suunto.refresh_tokens(account.refresh_token)
    access = (tokens.get("access_token") or "").strip()
    if not access:
        raise suunto.SuuntoError("Suunto не продлила токен")
    account.access_token = access
    account.refresh_token = (tokens.get("refresh_token") or account.refresh_token).strip()
    account.expires_at = suunto.expires_at(tokens)
    account.save(update_fields=["access_token", "refresh_token", "expires_at"])
    return access


@shared_task(name="integrations.fetch_suunto_workout", bind=True, max_retries=3,
             default_retry_delay=120)
def fetch_suunto_workout(self, account_pk: int, workout_id: str):
    """Забрать одну тренировку и провести её общим путём импорта.

    Повторяем при сетевых сбоях: тренировка никуда не денется, а человек не должен
    терять километры из-за того, что их сервер моргнул.
    """
    account = WatchAccount.objects.filter(pk=account_pk, source="suunto").first()
    if account is None:                       # часы отключили, пока задача ждала
        return "нет аккаунта"

    try:
        token = _fresh_token(account)
        raw = suunto.fetch_workout(token, workout_id)
    except suunto.SuuntoError as e:
        log.warning("Suunto: не забрали тренировку %s: %s", workout_id, e)
        raise self.retry(exc=e)

    data = suunto.to_workout(raw, workout_id)
    if not data:
        log.info("Suunto: тренировка %s без дистанции или времени — пропуск", workout_id)
        return "нечего импортировать"

    # Трек нужен для захвата кварталов и для оценки достоверности (D-108). Если
    # файл не отдали — это не повод отказывать: километры засчитаем, а захват
    # придержим. Поэтому сбой скачивания не роняет импорт.
    verdict = trust.unknown()
    track = 0
    try:
        fit_bytes = suunto.download_fit(token, workout_id)
        parsed = fitlib.parse(fit_bytes)
        verdict = trust.score(parsed)
        track = len(parsed.get("points") or [])
    except (suunto.SuuntoError, fitlib.FitError) as e:
        log.info("Suunto: трек тренировки %s не получен (%s)", workout_id, e)

    # Импорт — тем же путём, что и всё остальное: дедуп, склейка с нашим забегом,
    # суточный потолок, начисление (workouts.service).
    from workouts.views import accept_workout

    workout, outcome = accept_workout(account.user_id, "suunto", data)
    if outcome == "imported" and workout is not None:
        workout.trust_level = verdict["level"]
        workout.trust_score = verdict["score"]
        workout.trust_note = "; ".join(verdict["reasons"])[:300]
        workout.track_points = track
        fields = ["trust_level", "trust_score", "trust_note", "track_points"]
        # Низкая достоверность — тренировка сохраняется, но в зачёт не идёт и
        # ждёт разбора: человеку видно причину, а не молчаливый отказ.
        if verdict["level"] == trust.LOW and not workout.flagged:
            workout.flagged = True
            workout.flag_reason = ("Запись не похожа на часы: " + workout.trust_note)[:200]
            fields += ["flagged", "flag_reason"]
        workout.save(update_fields=fields)
    account.last_sync_at = timezone.now()
    account.save(update_fields=["last_sync_at"])
    log.info("Suunto: тренировка %s — %s", workout_id, outcome)
    return outcome

# ─────────────────────────── Часы COROS ──────────────────────────────────
# Вебхуков у COROS нет: о новой тренировке мы узнаём, только если спросим сами.
# Поэтому — опрос по расписанию. Частота выбрана по их лимиту: 50 файлов на
# человека в сутки, то есть раз в полчаса на аккаунт — с большим запасом.
COROS_LOOKBACK_DAYS = 3        # на сколько назад смотрим: хватает, чтобы подобрать
                               # тренировку, синхронизированную с опозданием


def _coros_token(account: WatchAccount) -> str:
    """Живой токен COROS: просроченный продлеваем своим же приложением."""
    if not account.expired:
        return account.access_token
    if not account.refresh_token:
        raise coros.CorosError("токен истёк, продлить нечем — нужно переподключить часы")
    client = McpClient.objects.filter(source="coros").first()
    if client is None:
        raise coros.CorosError("приложение у COROS не зарегистрировано")
    tokens = coros.refresh_tokens(client.client_id, client.client_secret,
                                  account.refresh_token)
    access = (tokens.get("access_token") or "").strip()
    if not access:
        raise coros.CorosError("COROS не продлил токен")
    account.access_token = access
    account.refresh_token = (tokens.get("refresh_token") or account.refresh_token).strip()
    account.expires_at = coros.expires_at(tokens)
    account.save(update_fields=["access_token", "refresh_token", "expires_at"])
    return access


def _records(payload):
    """Список тренировок из ответа инструмента: форма ответа у них плавает."""
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
        for key in ("records", "items", "data", "activities", "sportRecords"):
            value = payload.get(key)
            if isinstance(value, list):
                return [r for r in value if isinstance(r, dict)]
    return []


def _to_workout(raw: dict) -> tuple[str, dict] | None:
    """Запись COROS → (id тренировки, наш вид). None, если это не пробежка."""
    source_id = str(raw.get("labelId") or raw.get("activityId")
                    or raw.get("id") or "").strip()
    if not source_id:
        return None
    distance = suunto._num(raw, "distance", "totalDistance")  # те же имена полей
    duration = suunto._num(raw, "totalTime", "duration", "workoutTime")
    started = suunto._num(raw, "startTime", "startTimestamp", "timestamp")
    if not distance or not duration or not started:
        return None
    if started < 1e11:                       # секунды → миллисекунды
        started *= 1000
    sport = str(raw.get("sportType") or raw.get("mode") or "").lower()
    return source_id, {
        "source_id": source_id[:120],
        "started_at": datetime.fromtimestamp(started / 1000, tz=dt_tz.utc),
        "duration_s": int(duration),
        "distance_m": float(distance),
        "sport": "run" if ("run" in sport or sport in ("8", "100")) else (sport[:30] or "run"),
        "avg_hr": None,
        "max_hr": None,
        "calories": None,
    }


@shared_task(name="integrations.poll_coros", bind=True, max_retries=2,
             default_retry_delay=300)
def poll_coros(self, account_pk: int):
    """Спросить COROS о новых тренировках одного человека и забрать их.

    Экономим их лимит: сначала список (один вызов), а файл качаем только для тех
    тренировок, которых у нас ещё нет.
    """
    account = WatchAccount.objects.filter(pk=account_pk, source="coros").first()
    if account is None:
        return "нет аккаунта"

    try:
        token = _coros_token(account)
        since = timezone.now() - timedelta(days=COROS_LOOKBACK_DAYS)
        result = coros.call_tool(token, "querySportRecords", {
            "startDate": since.strftime("%Y-%m-%d"),
            "endDate": timezone.now().strftime("%Y-%m-%d"),
        })
    except coros.CorosError as e:
        log.warning("COROS: опрос не удался для %s: %s", account.user_id, e)
        raise self.retry(exc=e)

    from workouts.views import accept_workout

    taken = 0
    for raw in _records(coros.tool_payload(result)):
        parsed = _to_workout(raw)
        if not parsed:
            continue
        source_id, data = parsed
        if ExternalWorkout.objects.filter(
                user_id=account.user_id, source="coros", source_id=data["source_id"]).exists():
            continue                      # уже брали — файл не качаем, лимит бережём

        verdict = trust.unknown()
        track = 0
        try:
            urls = coros.tool_payload(coros.call_tool(
                token, "queryActivityFitFileDownloadUrls", {"labelId": source_id}))
            link = _first_url(urls)
            if link:
                raw_fit, _ = coros._request(link, headers={"Accept": "*/*"})
                parsed_fit = fitlib.parse(raw_fit)
                verdict = trust.score(parsed_fit)
                track = len(parsed_fit.get("points") or [])
        except (coros.CorosError, fitlib.FitError) as e:
            log.info("COROS: трек тренировки %s не получен (%s)", source_id, e)

        workout, outcome = accept_workout(account.user_id, "coros", data)
        if outcome == "imported" and workout is not None:
            workout.trust_level = verdict["level"]
            workout.trust_score = verdict["score"]
            workout.trust_note = "; ".join(verdict["reasons"])[:300]
            workout.track_points = track
            fields = ["trust_level", "trust_score", "trust_note", "track_points"]
            if verdict["level"] == trust.LOW and not workout.flagged:
                workout.flagged = True
                workout.flag_reason = ("Запись не похожа на часы: " + workout.trust_note)[:200]
                fields += ["flagged", "flag_reason"]
            workout.save(update_fields=fields)
            taken += 1

    account.last_sync_at = timezone.now()
    account.save(update_fields=["last_sync_at"])
    return f"новых тренировок: {taken}"


def _first_url(payload):
    """Ссылка на файл из ответа: у них это то список, то объект."""
    if isinstance(payload, str) and payload.startswith("http"):
        return payload
    if isinstance(payload, list):
        for item in payload:
            found = _first_url(item)
            if found:
                return found
    if isinstance(payload, dict):
        for key in ("url", "fitUrl", "downloadUrl", "fileUrl"):
            value = payload.get(key)
            if isinstance(value, str) and value.startswith("http"):
                return value
        for value in payload.values():
            found = _first_url(value)
            if found:
                return found
    return None


@shared_task(name="integrations.poll_coros_all")
def poll_coros_all():
    """Обойти всех, у кого подключены часы COROS. Зовётся по расписанию."""
    count = 0
    for account in WatchAccount.objects.filter(source="coros"):
        poll_coros.delay(account.pk)
        count += 1
    return f"поставлено опросов: {count}"

