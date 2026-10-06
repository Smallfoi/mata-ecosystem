# -*- coding: utf-8 -*-
"""Оценка достоверности тренировки с часов (D-108).

Зачем это вообще. «Пришло с часов» не значит «человек бежал»: Suunto и COROS
штатно разрешают загрузить готовый FIT в свой аккаунт — функция нужна тем, кто
переезжает с других часов. Значит, нарисованный на компьютере маршрут приедет к
нам через настоящий OAuth и будет выглядеть как честная запись.

Решение владельца (D-108): не запрещать импорт, а отличать настоящую запись от
нарисованной. Километры и дивизион засчитываем, а захват квартала и рекорд на
тропе — только при высокой достоверности: там отбирается чужое.

Чего эта оценка НЕ обещает. Каждый признак по отдельности подделывается. Вместе
они поднимают цену обмана с «нарисовал за три минуты» до «напиши генератор,
имитирующий шум GPS, дрейф пульса и паспорт конкретной модели часов». Полной
гарантии нет ни у кого — Strava чистит таблицы задним числом.
"""
import math
import statistics

HIGH = "high"        # всё засчитываем, включая захват и тропы
MEDIUM = "medium"    # километры и дивизион сразу, захват и тропа — после разбора
LOW = "low"          # не засчитываем, объясняем человеку

# Сколько очков даёт каждый признак. Числа подобраны так, чтобы запись настоящих
# часов (паспорт + пульс + живой GPS) уверенно проходила, а голый нарисованный
# трек — нет. Уточняются на живых файлах: см. D-108, «что нужно для настройки».
WEIGHTS = {
    "device": 30,      # паспорт устройства на месте
    "hr": 20,          # пульс есть и меняется
    "cadence": 15,     # каденс есть и меняется
    "gps_noise": 25,   # трек дрожит, как настоящий GPS
    "pace": 10,        # темп скачет посекундно
}
HIGH_FROM = 70
MEDIUM_FROM = 40


def _varies(values, min_rel_spread=0.02) -> bool:
    """Значение живое, а не константа. Ровная линия — признак рисунка."""
    values = [v for v in values if isinstance(v, (int, float))]
    if len(values) < 10:
        return False
    avg = statistics.fmean(values)
    if avg <= 0:
        return False
    return (statistics.pstdev(values) / avg) >= min_rel_spread


def _meters(a: dict, b: dict) -> float:
    """Расстояние между соседними точками, м. На городских масштабах плоскости
    достаточно: ошибка много меньше дрожания самого GPS."""
    dlat = (b["lat"] - a["lat"]) * 111_320.0
    dlon = (b["lon"] - a["lon"]) * 111_320.0 * math.cos(math.radians(a["lat"]))
    return math.hypot(dlat, dlon)


def _gps_is_alive(points) -> bool:
    """Настоящий GPS дрожит: шаги между точками разной длины, трек виляет.

    Нарисованный маршрут обычно выходит ровными шагами по прямым отрезкам —
    человек так не бежит никогда.
    """
    if len(points) < 20:
        return False
    steps = [_meters(points[i], points[i + 1]) for i in range(len(points) - 1)]
    steps = [s for s in steps if s > 0]
    if len(steps) < 15:
        return False
    avg = statistics.fmean(steps)
    if avg <= 0:
        return False
    # Разброс длин шагов. У записи часов он заметный даже на ровном темпе.
    return (statistics.pstdev(steps) / avg) >= 0.15


def score(parsed: dict) -> dict:
    """Оценить разобранный FIT. Возвращает {'level', 'score', 'reasons'}.

    `reasons` — человеческие формулировки: их видно в админке при разборе, и по
    ним понятно, чего не хватило, а не «оценка 35».
    """
    points = parsed.get("points") or []
    device = parsed.get("device") or {}
    total, reasons = 0, []

    if device.get("manufacturer") or device.get("serial"):
        total += WEIGHTS["device"]
    else:
        reasons.append("нет паспорта устройства: ни производителя, ни серийного номера")

    if _varies([p.get("hr") for p in points]):
        total += WEIGHTS["hr"]
    else:
        reasons.append("пульса нет или он не меняется")

    if _varies([p.get("cadence") for p in points]):
        total += WEIGHTS["cadence"]
    else:
        reasons.append("каденса нет или он не меняется")

    if _gps_is_alive(points):
        total += WEIGHTS["gps_noise"]
    else:
        reasons.append("трек слишком ровный для записи GPS")

    if _varies([p.get("speed") for p in points], min_rel_spread=0.05):
        total += WEIGHTS["pace"]
    else:
        reasons.append("темп не меняется по ходу")

    level = HIGH if total >= HIGH_FROM else MEDIUM if total >= MEDIUM_FROM else LOW
    return {"level": level, "score": total, "reasons": reasons}


def unknown() -> dict:
    """Файла нет вовсе — оценивать нечего.

    Это не повод отказывать: сводка тренировки могла прийти без трека (так
    устроены некоторые источники). Километры засчитываем, захват придерживаем —
    то есть ровно середина.
    """
    return {"level": MEDIUM, "score": 0, "reasons": ["трек не получен — оценивать нечего"]}
