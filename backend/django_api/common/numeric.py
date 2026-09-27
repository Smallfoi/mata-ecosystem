"""Разбор чисел из запроса: только конечные значения в разумных границах (аудит D04).

`float("nan")`, `float("inf")`, строки вместо чисел и гигантские значения раньше
доезжали до базы или до `datetime.fromtimestamp` и превращались в 500 — а иногда,
хуже, в сохранённую запись с бесконечной дистанцией. Эти помощники возвращают
число или бросают `BadNumber`, которую представление превращает в понятный 400.

Булевы значения числом не считаем: `True` в поле дистанции — это ошибка клиента,
а не «1 метр».
"""
import math


class BadNumber(ValueError):
    """Значение не число, не конечно или вне допустимых границ."""


def finite_float(value, lo=None, hi=None):
    if isinstance(value, bool):
        raise BadNumber("bool")
    try:
        f = float(value)
    except (TypeError, ValueError, OverflowError):
        raise BadNumber("not a number")
    if not math.isfinite(f):
        raise BadNumber("not finite")
    if lo is not None and f < lo:
        raise BadNumber("too small")
    if hi is not None and f > hi:
        raise BadNumber("too big")
    return f


def bounded_int(value, lo=None, hi=None):
    """Целое. Дробное число с клиента (12.0, 12.7) округляем вниз, как делал `int()`."""
    f = finite_float(value, lo, hi)
    return int(f)
