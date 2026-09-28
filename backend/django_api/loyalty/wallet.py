"""Кошелёк баллов: блокировка, однократные операции и единое списание (аудит B02/B03).

Баланс — это сумма всех транзакций пользователя (`balance_of`), отдельной строки
«баланс» нет. Поэтому гонка выглядит так: два запроса одновременно читают баланс
или «не начисляли ли уже», оба видят «можно» — и оба пишут. `transaction.atomic()`
от этого не спасает: при READ COMMITTED вторая транзакция не видит незакоммиченную
первую.

Решение — один кошелёк = одна блокировка на время транзакции:
`pg_advisory_xact_lock(<пространство>, hashtext(user_id))`. Кто первый взял —
читает, проверяет, пишет и коммитит; второй ждёт и видит уже новый баланс.

Почему advisory-lock, а не `select_for_update` строки `accounts`: транзакции бывают
у пользователя без строки аккаунта (удалённый аккаунт, служебные uid) — тогда
блокировать было бы нечего и гонка вернулась бы молча. Замок по uid есть всегда,
снимается сам при коммите/откате и ничего не хранит.

Вторая линия защиты — частичные уникальные индексы (миграция 0004): один
`purchase`/`redeem` на заказ и один `registration` на пользователя. Если индекс
на проде не создался из-за старых дублей, блокировка всё равно держит.
"""
from django.db import IntegrityError, connection, transaction

# Правила списания (Часть 11.5; те же числа в Store: LoyaltyAccount): 1 балл = 1 ₽,
# не меньше 50 баллов и не больше 30% суммы заказа вместе с доставкой.
MIN_REDEEM = 50
MAX_REDEEM_PERCENT = 30

# Первое число advisory-lock: пространство «кошельки баллов», чтобы не пересечься
# с другими замками по hashtext.
_LOCK_SPACE = 74_010


def lock_wallet(user_id) -> None:
    """Взять замок кошелька до конца текущей транзакции (вызывать внутри atomic)."""
    if connection.vendor != "postgresql":
        return
    with connection.cursor() as cur:
        cur.execute(
            "SELECT pg_advisory_xact_lock(%s, hashtext(%s))", [_LOCK_SPACE, str(user_id)]
        )


def post_once(user_id, amount, source, description="", order_id=None, *, per="order"):
    """Записать операцию, если такой ещё нет. Возвращает транзакцию или None (повтор).

    per="order" — одна операция `source` на заказ; per="user" — одна на пользователя
    (бонус за первый заказ). Проверка и запись — под замком кошелька.
    """
    from .models import LoyaltyTransaction, add_txn

    with transaction.atomic():
        lock_wallet(user_id)
        qs = LoyaltyTransaction.objects.filter(user_id=user_id, source=source)
        if per == "order":
            qs = qs.filter(order_id=order_id)
        if qs.exists():
            return None
        try:
            with transaction.atomic():
                return add_txn(user_id, amount, source, description, order_id)
        except IntegrityError:
            # Уникальный индекс поймал дубль, проскочивший мимо замка (например,
            # запись из старого кода во время выкатки) — это тоже «уже есть».
            return None


def check_redeem_rules(amount, order_sum) -> str:
    """Минимум и доля от заказа. Текст ошибки или пустая строка.

    Доля считается в целых рублях: у клиента она с плавающей точкой и на границе
    может выйти на рубль меньше — так сервер никогда не строже приложения.
    """
    if amount < MIN_REDEEM:
        return f"Баллами можно оплатить от {MIN_REDEEM} баллов"
    if amount > int(round(order_sum)) * MAX_REDEEM_PERCENT // 100:
        return f"Баллами можно оплатить не больше {MAX_REDEEM_PERCENT}% заказа"
    return ""


def redeemed_on_order(user_id, order_id) -> int:
    """Сколько баллов списано на заказ при оформлении (по реестру)."""
    from django.db.models import Sum

    from .models import LoyaltyTransaction

    s = LoyaltyTransaction.objects.filter(
        user_id=user_id, order_id=order_id, source="redeem"
    ).aggregate(s=Sum("amount"))["s"] or 0
    return -s


def redeem(user_id, order_id, amount, order_sum, description=None) -> str:
    """ЕДИНОЕ списание баллов на заказ — для всех путей (оформление заказа и
    прежний `/loyalty/redeem`). Текст ошибки или пустая строка.

    - правила (минимум, 30%) проверяются всегда, в том числе при повторе;
    - повтор с той же суммой — успех без второго списания;
    - повтор с другой суммой — ошибка: заказ уже оплачен баллами иначе;
    - баланс проверяется и списание пишется под замком кошелька.

    `order_sum` — сумма до скидки (товары и доставка).
    """
    from . import models

    if amount <= 0:
        return ""
    if not order_id:
        return "Баллы списываются только на заказ"
    problem = check_redeem_rules(amount, order_sum)
    if problem:
        return problem
    with transaction.atomic():
        lock_wallet(user_id)
        spent = redeemed_on_order(user_id, order_id)
        if spent:
            return "" if spent == amount else "Баллы по этому заказу уже списаны"
        # Тратить можно только доступные баллы: баллы за активность созревают
        # 3 дня и замораживаются, пока аккаунт на проверке (решение 28.09.2026).
        wallet = models.wallet_summary(user_id)
        if amount > wallet["spendable"]:
            if amount <= wallet["total"] and wallet["pending"]:
                return (
                    f"Сейчас доступно {wallet['spendable']} баллов: баллы за бег "
                    "становятся доступны для оплаты через 3 дня после начисления"
                    + (" и после проверки аккаунта" if wallet["frozen"] else "")
                )
            return "Недостаточно баллов"
        try:
            with transaction.atomic():
                models.add_txn(
                    user_id, -amount, "redeem",
                    description or f"Оплата баллами заказа №{order_id}", order_id,
                )
        except IntegrityError:
            return "" if redeemed_on_order(user_id, order_id) == amount else (
                "Баллы по этому заказу уже списаны"
            )
    return ""
