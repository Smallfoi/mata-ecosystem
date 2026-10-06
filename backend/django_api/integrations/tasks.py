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

from celery import shared_task
from django.utils import timezone

from integrations import suunto
from integrations.models import WatchAccount

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

    # Импорт — тем же путём, что и всё остальное: дедуп, склейка с нашим забегом,
    # суточный потолок, начисление (workouts.service).
    from workouts.views import accept_workout

    workout, outcome = accept_workout(account.user_id, "suunto", data)
    account.last_sync_at = timezone.now()
    account.save(update_fields=["last_sync_at"])
    log.info("Suunto: тренировка %s — %s", workout_id, outcome)
    return outcome
