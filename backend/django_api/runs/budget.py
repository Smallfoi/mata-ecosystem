"""Суточный бюджет баллов за активность (решение владельца 28.09.2026).

Один бюджет на всё, что платится за бег: свой забег (`POST /v1/runs`), импорт
тренировки с часов (`POST /v1/workouts/import`) и захват территории
(`POST /v1/territories/capture`). Раздельные потолки обходятся тривиально —
набрал лимит одним путём, добрал другим, — поэтому бюджет общий.

Считаем по реестру начислений (`loyalty_transactions`), а не по забегам: так
в бюджет попадает всё, что реально выплачено, какой бы путь это ни был.
Сутки — календарный день UTC по времени начисления.

Звать ТОЛЬКО под блокировкой `common.locks.ACTIVITY` на пользователя: иначе
параллельные запросы оба увидят «бюджет не исчерпан».
"""
from datetime import timedelta, timezone as dt_timezone

from django.db.models import Sum
from django.utils import timezone

from .rules import DAY_CAP_REASON, DAY_CAP_SOURCES, MAX_DAY_ACTIVITY_POINTS


def points_used_today(uid, now=None) -> int:
    from loyalty.models import LoyaltyTransaction

    now = (now or timezone.now()).astimezone(dt_timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return LoyaltyTransaction.objects.filter(
        user_id=uid, source__in=DAY_CAP_SOURCES, amount__gt=0,
        created_at__gte=day_start, created_at__lt=day_start + timedelta(days=1),
    ).aggregate(s=Sum("amount"))["s"] or 0


def grant(uid, points, now=None):
    """Сколько из `points` можно выплатить сейчас: (выплатить, срезано, причина)."""
    if points <= 0:
        return 0, 0, ""
    from loyalty import config as loyalty_config

    if loyalty_config.enabled():
        # Программа v1 (решение координатора к D-107): суточный потолок для
        # активности заменён месячными капами бонусов (loyalty.activity). Игровые
        # баллы (км рейтингов) потолком больше не режутся — деньгами они не являются.
        return points, 0, ""
    left = max(0, MAX_DAY_ACTIVITY_POINTS - points_used_today(uid, now))
    granted = min(points, left)
    cut = points - granted
    return granted, cut, (DAY_CAP_REASON if cut else "")
