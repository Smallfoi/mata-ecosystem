"""Дивизионы недели (Квартал 2.0, Ф0/Ф5 — утверждено 31.08.2026).

Дивизион — «лига недели»: до 30 бегунов ОДНОГО уровня (уровень считается по
пожизненным километрам, как в приложении). Драма недели — место внутри своей
группы, а не в общегородской таблице на тысячу человек.

Всё ленивое и идемпотентное — ни cron, ни Celery-beat не требуется:
- назначение в группу происходит при первом запросе бегуна на этой неделе;
- закрытие прошлой недели (баллы топ-3 + уведомления) — при первом запросе
  любого участника группы на новой неделе; повторное закрытие невозможно
  (флаг closed + дедуп начисления по run_id).

Периоды в UTC — так же, как во всех зачётах (`league.services.period_start`).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone as dt_tz

from django.db import transaction

from common.people import club_names_of, names_of
from loyalty.models import LoyaltyTransaction, add_txn
from loyalty.v1 import legacy_award_allowed
from notifications.models import create_notification
from runs.models import Run

from .models import Division, DivisionMember
from .services import _totals, period_start

# Пороги уровней по пожизненным км — 1:1 с клиентом (Ф4).
TIER_MIN_KM = (0, 50, 250, 1000, 2500, 5000, 15000)
TIER_LABELS = ("Асфальт", "Дворы", "Улица", "Проспект", "Район", "Город", "Лайм")
TIER_ROMANS = ("VII", "VI", "V", "IV", "III", "II", "I")

DIVISION_CAP = 30

# Зоны шкалы (доля таблицы): низ — «вылет», верх — «выше». Пока переходы между
# группами не включены (население маленькое), зоны — драма и приз недели.
ZONE_SHARE = 0.18

# Баллы за подиум недели. Идемпотентно по run_id="div:<division>:<uid>".
WEEK_REWARDS = (50, 30, 20)
REWARD_SOURCE = "runnerDivision"


def tier_for_km(km: float) -> int:
    tier = 0
    for i, min_km in enumerate(TIER_MIN_KM):
        if km >= min_km:
            tier = i
    return tier


def lifetime_km(uid: str) -> float:
    meters = (
        Run.objects.filter(user_id=uid, flagged=False)
        .values_list("distance_m", flat=True)
    )
    return round(sum(meters) / 1000.0, 2)


def _week_start_date(now: datetime | None = None):
    return period_start("week", now=now).date()


def assign_division(uid: str, now: datetime | None = None) -> Division:
    """Дивизион бегуна на текущей неделе (создаёт членство при первом входе)."""
    week = _week_start_date(now)
    member = DivisionMember.objects.filter(user_id=uid, week_start=week).first()
    if member:
        div = Division.objects.filter(id=member.division_id).first()
        if div:
            return div
    tier = tier_for_km(lifetime_km(uid))
    with transaction.atomic():
        # Последняя открытая группа уровня; если полна — новая.
        div = (
            Division.objects.select_for_update()
            .filter(tier=tier, week_start=week)
            .order_by("-seq")
            .first()
        )
        if div is None or DivisionMember.objects.filter(
            division_id=div.id
        ).count() >= DIVISION_CAP:
            seq = (div.seq + 1) if div else 1
            div = Division.objects.create(
                id=f"d_{uuid.uuid4().hex[:16]}", tier=tier, week_start=week, seq=seq
            )
        DivisionMember.objects.get_or_create(
            user_id=uid,
            week_start=week,
            defaults={"division_id": div.id},
        )
    return div


def _ranked_members(div: Division, until: datetime | None = None):
    """Члены группы по км за неделю группы. Бегавшие — по км, затем остальные
    по порядку вступления (место есть у каждого: таблица дивизиона полная)."""
    members = list(
        DivisionMember.objects.filter(division_id=div.id).order_by("joined_at")
    )
    ids = [m.user_id for m in members]
    start = datetime.combine(
        div.week_start, datetime.min.time(), tzinfo=dt_tz.utc
    )
    totals = _totals(start, until=until, user_ids=ids)
    ran = sorted(
        ((uid, totals[uid]["km"], totals[uid]["runs"]) for uid in totals),
        key=lambda x: (-x[1], x[0]),
    )
    rest = [uid for uid in ids if uid not in totals]
    ordered = [(uid, km, runs) for uid, km, runs in ran]
    ordered += [(uid, 0.0, 0) for uid in rest]
    return ordered


def division_payload(uid: str, now: datetime | None = None) -> dict:
    now = now or datetime.now(dt_tz.utc)
    _close_finished_weeks(uid, now=now)
    div = assign_division(uid, now=now)
    ordered = _ranked_members(div, until=now)
    # Движение мест: против расклада сутки назад (столько же данных — честно).
    day_ago = now - timedelta(days=1)
    week_start_dt = datetime.combine(
        div.week_start, datetime.min.time(), tzinfo=dt_tz.utc
    )
    movement: dict[str, int | None] = {}
    if day_ago > week_start_dt:
        yesterday = {
            u: i + 1
            for i, (u, _, _) in enumerate(_ranked_members(div, until=day_ago))
        }
        for i, (u, _, _) in enumerate(ordered):
            prev = yesterday.get(u)
            movement[u] = (prev - (i + 1)) if prev else None
    else:
        movement = {u: None for u, _, _ in ordered}

    ids = [u for u, _, _ in ordered]
    names = names_of(ids)
    clubs = club_names_of(ids)
    members = []
    me_block = {"place": None, "of": len(ordered), "km": 0.0, "movement": None}
    for i, (u, km, runs) in enumerate(ordered):
        place = i + 1
        item = {
            "userId": u,
            "name": names.get(u, "Бегун"),
            "club": clubs.get(u),
            "km": km,
            "runs": runs,
            "place": place,
            "movement": movement.get(u),
            "isMe": u == uid,
        }
        members.append(item)
        if u == uid:
            me_block = {
                "place": place,
                "of": len(ordered),
                "km": km,
                "movement": movement.get(u),
            }

    next_monday = datetime.combine(
        div.week_start + timedelta(days=7), datetime.min.time(), tzinfo=dt_tz.utc
    )
    return {
        "division": {
            "id": div.id,
            "tier": div.tier,
            "tierLabel": TIER_LABELS[div.tier],
            "roman": TIER_ROMANS[div.tier],
            "name": f"{TIER_LABELS[div.tier]}-{div.seq}",
            "size": len(ordered),
            "resetAtMs": int(next_monday.timestamp() * 1000),
        },
        "me": me_block,
        "members": members,
        "zones": {"up": ZONE_SHARE, "down": ZONE_SHARE},
    }


def _close_finished_weeks(uid: str, now: datetime) -> None:
    """Закрыть прошлые недели бегуна: баллы топ-3 его группы + уведомления."""
    week = _week_start_date(now)
    stale = DivisionMember.objects.filter(user_id=uid, week_start__lt=week)
    for member in stale:
        div = Division.objects.filter(id=member.division_id, closed=False).first()
        if div:
            close_division(div)


def close_division(div: Division) -> None:
    """Идемпотентное закрытие недели группы: топ-3 получают баллы."""
    with transaction.atomic():
        locked = (
            Division.objects.select_for_update().filter(id=div.id, closed=False).first()
        )
        if not locked:
            return
        end = datetime.combine(
            locked.week_start + timedelta(days=7),
            datetime.min.time(),
            tzinfo=dt_tz.utc,
        )
        ordered = _ranked_members(locked, until=end)
        for i, (u, km, _) in enumerate(ordered[: len(WEEK_REWARDS)]):
            if km <= 0:
                continue
            points = WEEK_REWARDS[i]
            dedup_key = f"div:{locked.id}:{u}"
            if not legacy_award_allowed(REWARD_SOURCE):
                # Программа v1: баллы за дивизион не начисляются (решение координатора);
                # сам итог недели и место остаются.
                create_notification(
                    u,
                    f"Итоги недели: #{i + 1} в дивизионе",
                    f"«{TIER_LABELS[locked.tier]}-{locked.seq}» — {km:.1f} км.",
                    type="system",
                )
                continue
            if LoyaltyTransaction.objects.filter(
                user_id=u, run_id=dedup_key, source=REWARD_SOURCE
            ).exists():
                continue
            add_txn(
                u,
                points,
                REWARD_SOURCE,
                f"Дивизион «{TIER_LABELS[locked.tier]}-{locked.seq}»: "
                f"#{i + 1} недели",
                None,
                dedup_key,
            )
            create_notification(
                u,
                f"Итоги недели: #{i + 1} в дивизионе",
                f"«{TIER_LABELS[locked.tier]}-{locked.seq}» — {km:.1f} км. "
                f"+{points} баллов.",
                type="system",
            )
        locked.closed = True
        locked.save(update_fields=["closed"])
