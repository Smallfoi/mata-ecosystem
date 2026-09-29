"""Сезоны района (Квартал 2.0, Ф5 — утверждено 31.08.2026).

Сезон = календарный месяц. Двухконтурная прогрессия: месячная таблица
обнуляется, а всё накопленное (уровень, медали, баллы, территория-след)
остаётся навсегда — «ничего накопленного не отнимается».

Закрытие ленивое и одноразовое: первый запрос нового месяца снимает снапшот
итогов прошлого месяца (строки SeasonResult — вечная трофейная история),
начисляет баллы топ-3 и создаёт уведомления. Гонки исключены строкой
SeasonClose (get_or_create + первичный ключ month).
"""
from __future__ import annotations

from datetime import datetime, timezone as dt_tz

from django.db import transaction

from common.people import names_of
from loyalty.models import LoyaltyTransaction, add_txn
from loyalty.v1 import legacy_award_allowed
from notifications.models import create_notification

from .models import SeasonClose, SeasonResult
from .services import _ranked, _totals, period_start, previous_window

SEASON_REWARDS = (100, 60, 30)
REWARD_SOURCE = "runnerSeason"

# Сколько строк сохраняем в вечную историю сезона.
MAX_RESULTS = 500


def _prev_month_bounds(now: datetime | None = None):
    start, end = previous_window("month", now=now)
    return start, end


def _month_key(start: datetime) -> str:
    return f"{start.year:04d}-{start.month:02d}"


def close_season_if_needed(now: datetime | None = None) -> str:
    """Закрыть прошлый месяц, если ещё не закрыт. Возвращает ключ месяца."""
    now = now or datetime.now(dt_tz.utc)
    start, end = _prev_month_bounds(now)
    month = _month_key(start)
    with transaction.atomic():
        _, created = SeasonClose.objects.get_or_create(month=month)
        if not created:
            return month
        ranked = _ranked(_totals(start, until=end), "km")
        totals = _totals(start, until=end)
        rows = []
        of = len(ranked)
        for i, (uid, km) in enumerate(ranked[:MAX_RESULTS]):
            rows.append(
                SeasonResult(
                    id=f"sr_{month}_{uid}"[:64],
                    month=month,
                    user_id=uid,
                    place=i + 1,
                    of=of,
                    km=km,
                    runs=totals.get(uid, {}).get("runs", 0),
                )
            )
        SeasonResult.objects.bulk_create(rows, ignore_conflicts=True)
        for i, (uid, km) in enumerate(ranked[: len(SEASON_REWARDS)]):
            points = SEASON_REWARDS[i]
            dedup_key = f"season:{month}:{uid}"
            if not legacy_award_allowed(REWARD_SOURCE):
                # Программа v1: баллы за сезон не начисляются (решение координатора).
                create_notification(
                    uid,
                    f"Сезон закрыт: ты #{i + 1}",
                    f"{km:.1f} км за месяц. Новый сезон начался!",
                    type="system",
                )
                continue
            if LoyaltyTransaction.objects.filter(
                user_id=uid, run_id=dedup_key, source=REWARD_SOURCE
            ).exists():
                continue
            add_txn(
                uid,
                points,
                REWARD_SOURCE,
                f"Сезон {month}: #{i + 1} месяца",
                None,
                dedup_key,
            )
            create_notification(
                uid,
                f"Сезон закрыт: ты #{i + 1}",
                f"{km:.1f} км за месяц. +{points} баллов. Новый сезон начался!",
                type="system",
            )
    return month


def season_payload(uid: str, now: datetime | None = None) -> dict:
    """Итог прошлого сезона для бегуна (для церемонии в приложении)."""
    now = now or datetime.now(dt_tz.utc)
    month = close_season_if_needed(now)
    mine = SeasonResult.objects.filter(month=month, user_id=uid).first()
    top = list(
        SeasonResult.objects.filter(month=month).order_by("place")[:3]
    )
    names = names_of([r.user_id for r in top])
    return {
        "month": month,
        "closed": True,
        "me": (
            {
                "place": mine.place,
                "of": mine.of,
                "km": mine.km,
                "runs": mine.runs,
            }
            if mine
            else None
        ),
        "top": [
            {
                "userId": r.user_id,
                "name": names.get(r.user_id, "Бегун"),
                "km": r.km,
                "place": r.place,
            }
            for r in top
        ],
        # Текущий сезон — для строки «сезон · сентябрь» в интерфейсе.
        "currentMonth": _month_key(period_start("month", now=now)),
    }
