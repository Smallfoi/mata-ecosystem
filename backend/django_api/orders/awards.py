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
from django.db import transaction
from django.db.models import Sum

from loyalty import wallet
from loyalty.models import LoyaltyTransaction, add_txn

# Правила списания живут в loyalty.wallet — одни на все пути (аудит B02).
from loyalty.wallet import MAX_REDEEM_PERCENT, MIN_REDEEM  # noqa: F401  (реэкспорт)

_PURCHASE_RATE = 10   # ₽ на 1 балл
_FIRST_ORDER_BONUS = 50


def accrue_purchase_points(order) -> None:
    """+1 балл за каждые 10 ₽ суммы заказа и +50 за первый заказ пользователя.

    Однократно под замком кошелька (B03): вебхук ЮKassa, перепроверка статуса и
    фоновая сверка могут прийти одновременно — начисление всё равно одно.
    """
    uid, oid = order.user_id, order.order_id
    total = float(order.total or 0)

    base = int(total // _PURCHASE_RATE)
    if base > 0:
        wallet.post_once(uid, base, "purchase", f"Покупка на {int(total)} ₽", oid)

    # «Первый заказ» определяем по отсутствию бонуса у пользователя, а не по числу
    # заказов: при оплате вперёд платит не обязательно самый первый оформленный.
    wallet.post_once(
        uid, _FIRST_ORDER_BONUS, "registration", "Бонус за первый заказ", oid, per="user"
    )


def redeem_for_order(user_id, order_id, amount, order_sum) -> str:
    """Списать баллы на заказ. Возвращает текст ошибки или пустую строку.

    Списывает сервер в момент оформления, а не отдельный запрос клиента: сайт
    такого запроса не делал вовсе — скидка применялась, а баллы оставались на
    счёте. Идемпотентно по заказу: повторная отправка и прежний запрос Store
    `/loyalty/redeem` второй раз не спишут.

    Это обёртка над единым сервисом `loyalty.wallet.redeem` (аудит B02): те же
    правила (минимум, 30%) и для повтора — существующее списание не отменяет
    проверок; другая сумма при повторе — ошибка. `order_sum` — сумма до скидки
    (товары и доставка).
    """
    return wallet.redeem(user_id, order_id, amount, order_sum)


def _sum(order, source) -> int:
    return LoyaltyTransaction.objects.filter(
        user_id=order.user_id, order_id=order.order_id, source=source
    ).aggregate(s=Sum("amount"))["s"] or 0


def redeemed_for(order) -> int:
    """Сколько баллов списано на заказ при оформлении."""
    return -_sum(order, "redeem")


def earned_for(order) -> int:
    """Сколько баллов начислено за покупку (без бонуса за первый заказ)."""
    return _sum(order, "purchase")


def return_redeemed_points(order, amount, description) -> int:
    """Вернуть на счёт часть списанных на заказ баллов — не больше ещё не возвращённого.

    Частями (D-73) или целиком. Возвращает, сколько баллов вернули.
    """
    # Остаток и запись — под замком кошелька (B03): две отмены сразу не вернут дважды.
    with transaction.atomic():
        wallet.lock_wallet(order.user_id)
        left = redeemed_for(order) - _sum(order, "redeem_refund")
        n = min(max(0, int(amount)), left)
        if n > 0:
            add_txn(order.user_id, n, "redeem_refund", description, order.order_id)
    return n


def revoke_earned_points(order, amount, description) -> int:
    """Снять часть начисленных за покупку баллов — не больше ещё не снятого.

    Баланс может уйти в минус, если начисленное уже потрачено. Так было и до частичных
    возвратов; решение про минус владелец отложил (D-73, на паузе). Деньгами из
    возврата не удерживаем.
    Возвращает, сколько баллов сняли.
    """
    with transaction.atomic():
        wallet.lock_wallet(order.user_id)
        left = earned_for(order) + _sum(order, "purchase_revoke")
        n = min(max(0, int(amount)), left)
        if n > 0:
            add_txn(order.user_id, -n, "purchase_revoke", description, order.order_id)
    return n


def revoke_purchase_points(order) -> None:
    """Снять всё ещё не снятое из начисленного за покупку (полный возврат денег).

    Иначе возврат превращается в дырку: товар и деньги у покупателя, а баллы
    (то есть скидка на следующую покупку) остались начисленными. Бонус за первый
    заказ не трогаем — он за факт знакомства с магазином, а не за конкретный товар.
    """
    revoke_earned_points(order, earned_for(order), "Отмена начисления: возврат заказа")


def refund_redeemed_points(order) -> None:
    """Вернуть все ещё не возвращённые баллы, списанные при оформлении.

    Покупатель списал баллы на чекауте, а платёж отменился — баллы обязаны
    вернуться, иначе они сгорают ни за что.
    """
    return_redeemed_points(order, redeemed_for(order), "Возврат баллов: оплата не прошла")
