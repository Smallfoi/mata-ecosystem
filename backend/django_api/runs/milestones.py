"""Вехи пожизненных километров (Квартал 2.0, Ф4 — утверждено 31.08.2026).

Пожизненный счётчик километров пересекает веху — бегун получает баллы и
уведомление. Вехи вечные (накопленное не отнимается), начисление идемпотентно:
дедуп по `run_id="ms:<веха>"` в транзакциях лояльности.
"""
from __future__ import annotations

from django.db import transaction
from django.db.models import Sum

from common.locks import ACTIVITY, lock_user
from loyalty.models import LoyaltyTransaction, add_txn
from loyalty.v1 import legacy_award_allowed
from notifications.models import create_notification

from .models import Run

MILESTONES_KM = (
    25, 50, 100, 150, 200, 250, 375, 500, 750,
    1000, 1250, 1500, 2000, 2500, 3000, 4000, 5000,
    7500, 10000, 15000, 20000,
)
MILESTONE_POINTS = 50
SOURCE = "runnerMilestone"


def lifetime_km(uid: str) -> float:
    meters = Run.objects.filter(user_id=uid, flagged=False).aggregate(
        d=Sum("distance_m")
    )["d"] or 0
    return meters / 1000.0


def award_milestones(uid: str, added_km: float) -> int:
    """Начислить вехи, пересечённые последней пробежкой. Вернуть сумму баллов."""
    if added_km <= 0:
        return 0
    # Проверка «веха уже выдана?» и выдача — под блокировкой бегуна (аудит C06):
    # два параллельных забега, пересёкших одну веху, иначе оба её оплачивают.
    with transaction.atomic():
        lock_user(ACTIVITY, uid)
        return _award_locked(uid, added_km)


def _award_locked(uid: str, added_km: float) -> int:
    after = lifetime_km(uid)
    before = max(0.0, after - added_km)
    total = 0
    for m in MILESTONES_KM:
        if not (before < m <= after):
            continue
        dedup_key = f"ms:{m}"
        if LoyaltyTransaction.objects.filter(
            user_id=uid, run_id=dedup_key, source=SOURCE
        ).exists():
            continue
        if not legacy_award_allowed(SOURCE):
            # Программа v1: баллы за вехи больше не начисляются (решение координатора).
            continue
        add_txn(uid, MILESTONE_POINTS, SOURCE, f"Веха {m} км", None, dedup_key)
        create_notification(
            uid,
            f"Веха: {m} км всего",
            f"Пожизненный счётчик перешагнул {m} км. +{MILESTONE_POINTS} баллов.",
            type="system",
        )
        total += MILESTONE_POINTS
    return total


def next_milestone(total_km: float) -> dict | None:
    """Ближайшая веха впереди — для строки в шапке уровня."""
    for m in MILESTONES_KM:
        if total_km < m:
            return {
                "atKm": m,
                "leftKm": round(m - total_km, 2),
                "reward": MILESTONE_POINTS,
            }
    return None
