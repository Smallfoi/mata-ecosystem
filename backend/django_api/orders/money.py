"""Деньги заказа — в копейках (целое) и Decimal, не float (аудит B09).

Правило одно для всего серверного расчёта: заказ, чек (`receipt.py`), платёж
(`payment.py`), возвраты (`returns.py`), выгрузка в 1С. Из рублей в копейки —
через `str` и `ROUND_HALF_UP`: float 0.285 хранится как 0.28499999…, и
`round(x * 100)` дал бы 28, а по правилам арифметики — 29.

Хранение: у заказа `total_kop` (целое, копейки) — основное поле; `total` (float,
рубли) продолжает заполняться и отдаваться в API как раньше — контракт Store,
сайта и 1С не меняется. Удалить float-поле — отдельный будущий шаг.
"""
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

_KOP = Decimal("0.01")


def money(value) -> Decimal:
    """Рубли → Decimal с копейками. Через str: float 0.1 не превращается в 0.1000…055.
    Пусто — 0. Не число — ValueError."""
    if isinstance(value, bool):
        raise ValueError(f"не число: {value!r}")
    try:
        amount = Decimal(str(value if value not in (None, "") else 0))
    except (InvalidOperation, ValueError):
        raise ValueError(f"не число: {value!r}") from None
    if not amount.is_finite():
        raise ValueError(f"не число: {value!r}")
    return amount.quantize(_KOP, rounding=ROUND_HALF_UP)


def to_kop(value) -> int:
    """Рубли (float, Decimal, int, строка) → копейки, ROUND_HALF_UP. Не число — ValueError."""
    return int(money(value) * 100)


def kop_to_rub(kop) -> Decimal:
    """Копейки → рубли (Decimal с двумя знаками), без потерь."""
    return (Decimal(int(kop)) / 100).quantize(_KOP)


def kop_to_float(kop) -> float:
    """Копейки → рубли float — только для старых полей и контрактов API.
    Двухзнаковое значение float хранит так, что обратно через str читается точно."""
    return float(kop_to_rub(kop))


def rub_str(kop) -> str:
    """Копейки → '1234.50' (формат ЮKassa и подписей)."""
    return f"{kop_to_rub(kop):.2f}"
