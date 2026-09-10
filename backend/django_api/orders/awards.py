"""Баллы за заказ: начисление и возврат — идемпотентно по заказу.

Раньше начисление жило прямо в создании заказа. Пока оплаты не было, это совпадало:
заказ = покупка. С реальной ЮKassa так нельзя — иначе баллы (а баллы = деньги)
капают за неоплаченный заказ. Поэтому логика вынесена сюда и вызывается:

- только после подтверждённой оплаты (D-72): вебхук ЮKassa, перепроверка статуса
  покупателем или фоновая сверка неоплаченных заказов; в режиме разработки — после
  упрощённой оплаты без провайдера.

Списание баллов на заказ тоже здесь — его делает сервер при оформлении.

Каждая функция проверяет, не начисляла ли уже по этому заказу: вебхук ЮKassa может
прийти несколько раз (при 5xx она повторяет доставку), и повтор не должен задваивать.
"""
from loyalty.models import LoyaltyTransaction, add_txn

_PURCHASE_RATE = 10   # ₽ на 1 балл
_FIRST_ORDER_BONUS = 50

# Правила списания (Часть 11.5; те же числа в Store: LoyaltyAccount): 1 балл = 1 ₽,
# не меньше 50 баллов и не больше 30% суммы заказа вместе с доставкой.
MIN_REDEEM = 50
MAX_REDEEM_PERCENT = 30


def _has_txn(user_id, order_id, source) -> bool:
    return LoyaltyTransaction.objects.filter(
        user_id=user_id, order_id=order_id, source=source
    ).exists()


def accrue_purchase_points(order) -> None:
    """+1 балл за каждые 10 ₽ суммы заказа и +50 за первый заказ пользователя."""
    uid, oid = order.user_id, order.order_id
    total = float(order.total or 0)

    if not _has_txn(uid, oid, "purchase"):
        base = int(total // _PURCHASE_RATE)
        if base > 0:
            add_txn(uid, base, "purchase", f"Покупка на {int(total)} ₽", oid)

    # «Первый заказ» определяем по отсутствию бонуса у пользователя, а не по числу
    # заказов: при оплате вперёд платит не обязательно самый первый оформленный.
    if not LoyaltyTransaction.objects.filter(user_id=uid, source="registration").exists():
        add_txn(uid, _FIRST_ORDER_BONUS, "registration", "Бонус за первый заказ", oid)


def redeem_for_order(user_id, order_id, amount, order_sum) -> str:
    """Списать баллы на заказ. Возвращает текст ошибки или пустую строку.

    Списывает сервер в момент оформления, а не отдельный запрос клиента: сайт
    такого запроса не делал вовсе — скидка применялась, а баллы оставались на
    счёте. Идемпотентно по заказу: повторная отправка и прежний запрос Store
    `/loyalty/redeem` второй раз не спишут.

    `order_sum` — сумма до скидки (товары и доставка). Доля считается в целых
    рублях: у клиента она с плавающей точкой и на границе может выйти на рубль
    меньше — так сервер никогда не строже приложения.
    """
    from loyalty.models import balance_of

    if amount <= 0 or _has_txn(user_id, order_id, "redeem"):
        return ""
    if amount < MIN_REDEEM:
        return f"Баллами можно оплатить от {MIN_REDEEM} баллов"
    if amount > int(round(order_sum)) * MAX_REDEEM_PERCENT // 100:
        return f"Баллами можно оплатить не больше {MAX_REDEEM_PERCENT}% заказа"
    if amount > balance_of(user_id):
        return "Недостаточно баллов"
    add_txn(user_id, -amount, "redeem", f"Оплата баллами заказа №{order_id}", order_id)
    return ""


def revoke_purchase_points(order) -> None:
    """Снять баллы, начисленные за покупку, если деньги вернули покупателю.

    Иначе возврат превращается в дырку: товар и деньги у покупателя, а баллы
    (то есть скидка на следующую покупку) остались начисленными. Бонус за первый
    заказ не трогаем — он за факт знакомства с магазином, а не за конкретный товар.
    """
    uid, oid = order.user_id, order.order_id
    if _has_txn(uid, oid, "purchase_revoke"):
        return
    earned = LoyaltyTransaction.objects.filter(
        user_id=uid, order_id=oid, source="purchase"
    ).first()
    if not earned or earned.amount <= 0:
        return
    add_txn(uid, -earned.amount, "purchase_revoke", "Отмена начисления: возврат заказа", oid)


def refund_redeemed_points(order) -> None:
    """Вернуть баллы, списанные при оформлении, если оплата не состоялась.

    Покупатель списал баллы на чекауте, а платёж отменился — баллы обязаны
    вернуться, иначе они сгорают ни за что.
    """
    uid, oid = order.user_id, order.order_id
    spent = LoyaltyTransaction.objects.filter(
        user_id=uid, order_id=oid, source="redeem"
    ).first()
    if not spent or _has_txn(uid, oid, "redeem_refund"):
        return
    add_txn(
        uid, -spent.amount, "redeem_refund", "Возврат баллов: оплата не прошла", oid
    )
