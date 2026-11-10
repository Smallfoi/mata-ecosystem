"""Разбор помеченных забегов человеком (S-04, фаза 2).

Анти-чит только ставит вопрос: забег выглядит неправдоподобно — баллы придержаны.
Ответ даёт человек. Здесь живёт всё, что нужно для этого ответа: очередь на разбор,
контекст по бегуну, признаки мульти-аккаунта и три решения — одобрить, признать
нарушением, пересчитать баллы.

Три правила, которых держимся:
1. **Баллы не переписываем задним числом.** Ошибочное начисление гасится встречной
   транзакцией (`runnerRunRevoked`), а не удалением записи: история платежей должна
   сходиться, даже когда мы ошиблись.
2. **Идемпотентность.** Повторное нажатие кнопки (или двойной клик) не начисляет
   второй раз — сверяемся с транзакцией по `run_id`.
3. **Решение не удаляет улику.** Признанный нарушением забег остаётся помеченным
   и с причиной; меняется только то, что он разобран.
"""
from django.db.models import Count, Sum
from django.utils import timezone

from loyalty.models import LoyaltyTransaction, add_txn

from .models import Run
from .rules import REVIEW_WINDOW, points_for

# Как далеко назад смотрим, когда считаем «свежие» флаги бегуна.
RECENT_WINDOW = REVIEW_WINDOW

SOURCE_RUN = "runnerRun"
SOURCE_REVOKED = "runnerRunRevoked"


# ─────────────────────────── решения модератора ───────────────────────────

def _awarded_for(run) -> int:
    """Сколько баллов сейчас реально висит на этом забеге в истории транзакций."""
    return (
        LoyaltyTransaction.objects.filter(
            user_id=run.user_id, run_id=run.id, source__in=(SOURCE_RUN, SOURCE_REVOKED)
        ).aggregate(s=Sum("amount"))["s"]
        or 0
    )


def _stamp(run, by=""):
    run.reviewed_at = timezone.now()
    run.reviewed_by = (by or "")[:150]


def approve_run(run, by="", notify=True):
    """Снять флаг и начислить баллы за забег. Возвращает начисленные баллы.

    Идемпотентно: если транзакция по этому забегу уже есть — второй раз не платим.
    """
    points = points_for(run.distance_m)
    already = LoyaltyTransaction.objects.filter(
        user_id=run.user_id, run_id=run.id, source=SOURCE_RUN
    ).exists()
    if points > 0 and not already:
        add_txn(run.user_id, points, SOURCE_RUN,
                f"Пробежка {run.distance_km:.1f} км (одобрено модератором)",
                None, run.id)
    run.flagged = False
    run.flag_reason = ""
    run.points_awarded = points
    _stamp(run, by)
    run.save(update_fields=["flagged", "flag_reason", "points_awarded",
                            "reviewed_at", "reviewed_by"])

    from loyalty import activity
    from runs.milestones import award_milestones
    from territories.awards import on_run_approved

    # Программа лояльности v1 (этап 2): бонус за пробежку — по правилам ТЗ, ДО
    # захватов (их бонус — только за валидную пробежку).
    act = activity.on_run_approved(run)
    award_milestones(run.user_id, run.distance_km)
    # Захват этой пробежки ждал решения — теперь его баллы приходят (п.4).
    on_run_approved(run)
    if act is not None:
        points = act.amount  # программа v1: в деньги идёт бонус, а не игровые баллы
    if notify and not already:
        _notify(run.user_id, "Забег подтверждён",
                f"Проверили забег {run.distance_km:.1f} км — всё в порядке. "
                + (f"Баллы начислены: +{points}." if act is None
                   else f"Бонусов начислено: +{points}."))
    return points


def reject_run(run, by="", notify=True):
    """Признать нарушением: баллы за этот забег не полагаются.

    Если баллы за него когда-то уже начислили (например, одобрили по ошибке или
    забег прошёл до ужесточения порогов) — гасим встречной транзакцией, чтобы
    баланс сошёлся. Возвращает величину списания (0, если списывать нечего).
    """
    revoked = 0
    awarded = _awarded_for(run)
    if awarded > 0:
        add_txn(run.user_id, -awarded, SOURCE_REVOKED,
                f"Отмена баллов за забег {run.distance_km:.1f} км (нарушение)",
                None, run.id)
        revoked = awarded
    run.points_awarded = 0
    run.flagged = True  # улику не стираем: забег остаётся помеченным
    _stamp(run, by)
    run.save(update_fields=["points_awarded", "flagged", "reviewed_at", "reviewed_by"])
    # Захват этой пробежки баллов не получит; выплаченные за него — отзываются.
    from loyalty import activity
    from territories.awards import on_run_rejected

    on_run_rejected(run)
    activity.on_run_rejected(run)  # программа v1: бонусы пробежки и её захватов
    if notify:
        body = "Забег не засчитан: данные не подтвердились."
        if revoked:
            body += f" Ранее начисленные баллы списаны: −{revoked}."
        _notify(run.user_id, "Забег не засчитан", body)
    return revoked


def recalculate(uid):
    """Пересчитать баллы за бег у одного бегуна и починить расхождения.

    Зачем: за время жизни проекта менялись пороги и цена километра, а часть
    начислений могла не дойти (обрыв, ошибка в фоне). Проходим по всем НЕ
    помеченным забегам, сверяем «сколько должно быть» с «сколько записано»
    и доначисляем недостающее. Ничего не удаляем: недобор закрывается новой
    транзакцией, перебор — встречной.

    Возвращает сводку: сколько забегов тронули и на сколько изменился баланс.
    """
    fixed, delta = 0, 0
    for run in Run.objects.filter(user_id=uid, flagged=False):
        # Срезанное суточным потолком (решение 28.09.2026) — не недостача.
        should = max(0, points_for(run.distance_m) - run.points_capped)
        has = _awarded_for(run)
        if run.points_awarded != should:
            run.points_awarded = should
            run.save(update_fields=["points_awarded"])
        if has == should:
            continue
        diff = should - has
        if diff > 0:
            add_txn(uid, diff, SOURCE_RUN,
                    f"Доначисление за забег {run.distance_km:.1f} км (пересчёт)",
                    None, run.id)
        else:
            add_txn(uid, diff, SOURCE_REVOKED,
                    f"Корректировка баллов за забег {run.distance_km:.1f} км (пересчёт)",
                    None, run.id)
        fixed += 1
        delta += diff
    return {"runs": fixed, "delta": delta}


def _notify(uid, title, body):
    """Сообщить бегуну решение. Сбой уведомления не должен ломать модерацию."""
    try:
        from notifications.models import create_notification

        create_notification(uid, title, body, type="system")
    except Exception:
        pass


# ────────────────────────── очередь и контекст ──────────────────────────

def pending_queryset():
    """Забеги, ждущие решения: помечены и ещё не разобраны."""
    return Run.objects.filter(flagged=True, reviewed_at__isnull=True)


def linked_accounts(uid):
    """Аккаунты, похожие на «второе лицо того же человека» (мульти-аккаунт).

    Считаем по фактам, а не по догадкам, и только как подсказку модератору:
    - **общее устройство** — один и тот же токен пушей зарегистрирован на разные
      аккаунты. Это самый сильный признак: телефон один, аккаунтов несколько;
    - **общий телефон** — один номер на нескольких записях (совпадение бывает
      после ручных правок, но проверить стоит).

    Совпадение НЕ означает нарушения: телефон дают ребёнку, номер меняют. Поэтому
    страница показывает связь и оставляет решение человеку.
    """
    from accounts.models import Account
    from notifications.models import DeviceAccount

    ids, why = set(), {}

    tokens = list(
        DeviceAccount.objects.filter(user_id=uid).values_list("token", flat=True)
    )
    if tokens:
        for other in DeviceAccount.objects.filter(token__in=tokens).exclude(
            user_id=uid
        ).values_list("user_id", flat=True):
            ids.add(other)
            why[other] = "общее устройство"

    phone = (
        Account.objects.filter(id=uid).values_list("phone", flat=True).first() or ""
    ).strip()
    if phone:
        for other in Account.objects.filter(phone=phone).exclude(id=uid).values_list(
            "id", flat=True
        ):
            ids.add(other)
            why[other] = "общий телефон" if other not in why else "устройство и телефон"

    if not ids:
        return []
    rows = []
    for acc in Account.objects.filter(id__in=ids):
        rows.append({
            "id": acc.id,
            "name": acc.name or acc.phone or acc.email or acc.id,
            "why": why.get(acc.id, ""),
            "blocked": acc.is_blocked,
            "review": acc.needs_review,
        })
    return sorted(rows, key=lambda r: r["name"])


def runner_context(uid):
    """Всё, что нужно знать модератору о бегуне, одним запросом на страницу."""
    from accounts.models import Account
    from loyalty.models import wallet_summary

    acc = Account.objects.filter(id=uid).first()
    wallet = wallet_summary(uid)
    since = timezone.now() - RECENT_WINDOW
    agg = Run.objects.filter(user_id=uid).aggregate(
        total=Count("id"), km=Sum("distance_m"),
    )
    valid = Run.objects.filter(user_id=uid, flagged=False).aggregate(
        n=Count("id"), km=Sum("distance_m"),
    )
    return {
        "id": uid,
        "name": (acc.name or acc.phone or acc.email or uid) if acc else uid,
        "phone": (acc.phone if acc else "") or "",
        "city": (acc.city if acc else "") or "",
        "exists": acc is not None,
        "blocked": bool(acc and acc.is_blocked),
        "block_reason": (acc.block_reason if acc else "") or "",
        "needs_review": bool(acc and acc.needs_review),
        "runs_total": agg["total"] or 0,
        "km_total": round((agg["km"] or 0) / 1000.0, 1),
        "runs_valid": valid["n"] or 0,
        "km_valid": round((valid["km"] or 0) / 1000.0, 1),
        "flags_recent": Run.objects.filter(
            user_id=uid, flagged=True, created_at__gte=since
        ).count(),
        "flags_total": Run.objects.filter(user_id=uid, flagged=True).count(),
        "balance": wallet["total"],
        # Баллы за активность, которые сейчас нельзя потратить: пока аккаунт на
        # проверке — все начисленные по правилу созревания (заморожены), иначе —
        # ещё не созревшие (решение 28.09.2026, п.3).
        "frozen_points": wallet["pending"] if wallet["frozen"] else 0,
        "maturing_points": 0 if wallet["frozen"] else wallet["pending"],
        "linked": linked_accounts(uid),
    }
