"""Номер заказа (D-120): выдаёт сервер, уникален, ничего не говорит о магазине.

`МАТА-` + 8 случайных цифр (первая не ноль). Порядковый номер выдал бы, сколько
заказов было за день или с прошлой покупки; случайный — нет. Вариантов 90 млн:
совпадение с уже выданным номером маловероятно, но проверяется, а последнее
слово за уникальным индексом базы — два одинаковых номера в неё не попадут.
"""
import secrets

PREFIX = "МАТА-"
_LOW, _SPAN = 10_000_000, 90_000_000
_ATTEMPTS = 20


def random_number() -> str:
    return f"{PREFIX}{_LOW + secrets.randbelow(_SPAN)}"


def new_order_number() -> str:
    from .models import Order

    for _ in range(_ATTEMPTS):
        number = random_number()
        if not Order.objects.filter(order_id=number).exists():
            return number
    # 20 совпадений подряд при 90 млн вариантов — что-то сломано (генератор/база).
    raise RuntimeError("Не удалось подобрать свободный номер заказа")
