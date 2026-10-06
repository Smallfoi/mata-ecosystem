# -*- coding: utf-8 -*-
"""Приём одной тренировки извне — общий путь для всех источников.

Раньше весь разбор жил внутри HTTP-обработчика `import_workouts`: приложение
присылало список, он же его и сохранял. С часами так нельзя — тренировку приносит
не человек, а фоновая задача по уведомлению от Suunto, и повторять в ней дедуп,
античит, склейку с нашим забегом, суточный потолок и начисление значило бы
завести второй, тихо расходящийся свод правил.

Поэтому правила здесь, в одном месте, и ими пользуются оба пути (аудит C02/C05):
HTTP-импорт из приложения и приём с часов.
"""
import hashlib

from django.db import IntegrityError, transaction

from common.locks import ACTIVITY, lock_user
from loyalty.models import add_txn
from runs.budget import grant
from workouts.models import ExternalWorkout, WorkoutAward


def workout_id(user_id: str, source: str, source_id: str) -> str:
    """Детерминированный идентификатор: одна тренировка одного источника —
    одна запись даже при гонке двух параллельных приёмов."""
    return hashlib.sha1(f"{user_id}:{source}:{source_id}".encode()).hexdigest()[:32]


def accept(user_id, source, data, *, validate, find_same_run, running_sports, points_per_km):
    """Принять одну разобранную тренировку.

    Возвращает `(запись, итог)`, где итог — одно из «imported», «duplicate».
    Проверки передаются снаружи: они живут в `workouts.views` рядом с границами
    разбора, и тащить их сюда значило бы разорвать их связь с теми границами.
    """
    existing = ExternalWorkout.objects.filter(
        user_id=user_id, source=source, source_id=data["source_id"]
    ).first()
    if existing:
        return existing, "duplicate"

    wid = workout_id(user_id, source, data["source_id"])
    capped = 0
    cap_note = ""

    try:
        # Тренировка, реестр и начисление — одно целое (аудит C05): сбой посередине
        # откатывает всё, и повтор той же присылки доводит начисление ровно один раз.
        with transaction.atomic():
            # Суточный потолок общий со своими забегами — проверка и запись под той
            # же блокировкой на пользователя (аудит C06).
            lock_user(ACTIVITY, user_id)
            flag_reason = validate(user_id, data)
            same_run = None if flag_reason else find_same_run(user_id, data)

            points = 0
            if not flag_reason and not same_run and data["sport"] in running_sports:
                points = round(data["distance_m"] / 1000.0 * points_per_km)

            # Реестр переживает отключение источника (аудит C02): если по этой
            # тренировке решение уже принималось, второй раз не платим.
            prior = WorkoutAward.objects.select_for_update().filter(id=wid).first()
            if prior:
                points = 0
            points, cut, cap_reason = grant(user_id, points)
            if cut:
                capped, cap_note = cut, cap_reason

            workout = ExternalWorkout.objects.create(
                id=wid,
                user_id=user_id,
                source=source,
                run_id=same_run.id if same_run else "",
                points_awarded=prior.points if prior else points,
                flagged=bool(flag_reason),
                flag_reason=flag_reason,
                **data,
            )
            if not prior:
                txn = None
                if points:
                    txn = add_txn(
                        user_id, points, "runnerRun",
                        f"Тренировка из внешнего источника: {workout.distance_km:.1f} км",
                    )
                WorkoutAward.objects.create(
                    id=wid, user_id=user_id, source=source, points=points,
                    txn_id=txn.id if txn else "",
                )
            # Программа лояльности v1 (этап 2): бонус за тренировку по правилам ТЗ
            # (дубль своего забега, одна в день, капы месяца) — для HTTP-импорта и
            # часов одинаково. Повтор после переподключения источника второй раз не
            # платит: решение хранится (LoyaltyActivity).
            from loyalty import config as loyalty_config

            bonus_act = None
            if loyalty_config.enabled():
                from loyalty import activity

                bonus_act = activity.on_workout(workout, same_run)
    except IntegrityError:
        # Параллельный приём той же тренировки успел первым — это дубль.
        existing = ExternalWorkout.objects.filter(id=wid).first()
        return existing, "duplicate"

    workout.points_this_time = points        # сколько начислили именно сейчас
    workout.bonus_act = bonus_act            # решение по бонусу v1 (None — программа выкл.)
    workout.bonus_this_time = (bonus_act.amount if bonus_act is not None and not prior
                               and bonus_act.status == "granted" else 0)
    workout.points_capped = capped
    workout.cap_reason = cap_note
    return workout, "imported"
