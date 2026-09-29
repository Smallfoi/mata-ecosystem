"""Возврат заказа — целиком или частями (D-73).

Правила (решение владельца 10.09.2026):
- деньги возвращаются по суммам из чека: скидка баллами разложена по позициям
  пропорционально (`receipt.allocate`), и чек возврата обязан с этим совпадать;
- потраченные на заказ баллы возвращаются, начисленные за него — снимаются, в той
  же доле, что и возвращённые вещи;
- доставка возвращается вместе с последней вещью заказа («Возврат и обмен», п. 4.3:
  первичная доставка из возврата не удерживается). Пока хоть одна вещь у покупателя,
  доставка ему пригодилась;
- если начисленные баллы уже потрачены, баланс уходит в минус — как и до частичных
  возвратов (в программе v1 это правило ТЗ §4: долг гасится следующими
  начислениями); деньгами из возврата не удерживаем.
- программа лояльности v1 (loyalty/v1.py): списанные бонусы делятся по доле
  позиции в eligible_total и возвращаются в исходные лоты; лот покупки в удержании
  отменяется, доступный — списывается с баланса.

Сумма всех возвратов по заказу ровно равна оплате, а баллы — ровно списанным и
начисленным: последний возврат забирает остаток, а не свою долю с округлением.

Жизненный цикл возврата (аудит B04): «В обработке» (pending) → «Проведён» (done)
или «Не прошёл» (failed). Проведённым возврат становится ТОЛЬКО по подтверждению
ЮKassa (статус succeeded) — в ответе на запрос, в уведомлении refund.succeeded
или при фоновой сверке. Баллы и статус заказа меняются ровно один раз, в этом
переходе. Нет ответа ЮKassa (таймаут, 5xx) — исход неизвестен: возврат остаётся
«в обработке», второй по заказу не оформить, а сверка повторяет запрос с тем же
ключом идемпотентности (ЮKassa вернёт уже созданный возврат, а не сделает новый).
"""
import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .awards import (
    earned_for,
    redeemed_for,
    redeemed_share,
    return_redeemed_points,
    revoke_earned_points,
)
from .models import Order, OrderReturn
from .money import kop_to_rub
from .payment import PaymentError, PaymentUncertain, create_refund, fetch_refund
from .receipt import allocate, refund_receipt

log = logging.getLogger(__name__)

# Статусы оплаты, при которых ещё есть что возвращать.
RETURNABLE = ("paid", "partially_refunded")

# Сверка «зависших» возвратов: не раньше, чем закончился бы сам запрос
# (таймаут 15 с), и не позже, чем ЮKassa помнит ключ идемпотентности (24 ч).
# Старше — повтор запроса мог бы вернуть деньги второй раз: только вручную.
RECONCILE_AFTER = timedelta(minutes=2)
RESEND_WITHIN = timedelta(hours=23)


class ReturnError(Exception):
    """Возврат оформить нельзя — текст для сотрудника."""


def _rows(order):
    try:
        return allocate(order.payload, kop_to_rub(order.amount_kop))
    except ValueError as e:
        raise ReturnError(f"Не удалось разложить заказ по позициям: {e}") from e


def _taken(order):
    """Позиции, которые уже вернули или возвращают прямо сейчас."""
    out = set()
    for ret in order.returns.filter(status__in=("pending", "done")):
        out.update(int(i) for i in ret.lines)
    return out


def return_plan(order):
    """Позиции заказа с суммами из чека и отметкой, что уже вернули."""
    taken = _taken(order)
    rows = _rows(order)
    for row in rows:
        row["returned"] = row["index"] in taken
    return rows


def _compute(order, indexes):
    """Сколько денег и баллов уйдёт покупателю при возврате этих позиций."""
    if order.payment_status not in RETURNABLE or not order.payment_id:
        raise ReturnError("Вернуть можно только заказ, оплата которого прошла через ЮKassa")
    if order.returns.filter(status="pending").exists():
        # Иначе два одновременных возврата посчитали бы «остаток» каждый по-своему
        # и вернули бы деньги дважды.
        raise ReturnError("По заказу уже идёт возврат — дождитесь результата")

    rows = _rows(order)
    goods = {row["index"] for row in rows if row["subject"] == "commodity"}
    taken = _taken(order)
    chosen = {int(i) for i in indexes}
    if not chosen:
        raise ReturnError("Отметьте, что возвращаем")
    if not chosen <= goods:
        raise ReturnError("В заказе нет такой позиции (доставка отдельно не возвращается)")
    if chosen & taken:
        raise ReturnError("Часть отмеченных вещей уже вернули")

    done = list(order.returns.filter(status="done"))
    total_kop = sum(row["paid"] for row in rows)
    completes = (taken | chosen) >= goods
    redeemed, earned = redeemed_for(order), earned_for(order)

    if completes:
        # Последние вещи: возвращаем остаток целиком — вместе с доставкой.
        lines = sorted(chosen | {row["index"] for row in rows if row["index"] not in goods})
        amount_kop = total_kop - sum(r.amount_kop for r in done)
        points_back = max(0, redeemed - sum(r.points_returned for r in done))
        points_off = max(0, earned - sum(r.points_revoked for r in done))
    else:
        lines = sorted(chosen)
        amount_kop = sum(row["paid"] for row in rows if row["index"] in chosen)
        gross_all = sum(row["gross"] for row in rows)
        gross_chosen = sum(row["gross"] for row in rows if row["index"] in chosen)
        # Скидка баллами разложена по всем позициям пропорционально цене — баллы
        # возвращаем в той же доле. Начисленные — в доле возвращённых денег.
        points_back = redeemed * gross_chosen // gross_all if gross_all else 0
        # Программа v1: списанные бонусы возвращаются по доле позиции в eligible_total
        # (исключённые категории и уценка бонусами не оплачивались — им ничего).
        share = redeemed_share(order, chosen)
        if share is not None:
            points_back = share
        points_off = earned * amount_kop // total_kop if total_kop else 0

    return {
        "lines": lines,
        "amount_kop": amount_kop,
        "points_back": points_back,
        "points_off": points_off,
        "completes": completes,
    }


def preview(order, indexes):
    """Расчёт возврата без действий — чтобы сотрудник увидел суммы до нажатия."""
    return _compute(order, indexes)


def make_return(order_pk, indexes, by=""):
    """Оформить возврат: запрос в ЮKassa, затем — по её подтверждению — баллы и статус.

    Возвращает OrderReturn: done — деньги ушли; pending — ЮKassa ещё обрабатывает
    или не ответила (досверит вебхук/фоновая сверка). Отказ — ReturnError.
    """
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order_pk)
        plan = _compute(order, indexes)
        # Баллы по плану запоминаем сразу: проводятся они позже, в момент
        # подтверждения, и пересчитывать их тогда было бы не из чего.
        ret = OrderReturn.objects.create(
            order=order, lines=plan["lines"], amount_kop=plan["amount_kop"],
            points_returned=plan["points_back"], points_revoked=plan["points_off"],
            status="pending", created_by=by[:150],
        )

    # Запрос в ЮKassa — вне транзакции: сеть не должна держать блокировку заказа.
    try:
        refund = _send(order, ret)
    except PaymentUncertain as e:
        # Запрос мог дойти: «не прошёл» здесь — приглашение вернуть деньги дважды.
        ret.error = f"Нет ответа ЮKassa ({e}) — проверим автоматически"[:300]
        ret.save(update_fields=["error"])
        log.warning("Возврат %s по заказу %s: исход неизвестен: %s",
                    ret.pk, order.order_id, e)
        return ret
    except (PaymentError, ValueError) as e:
        _fail(ret.pk, str(e))
        raise ReturnError(f"Возврат не прошёл: {e}") from e

    ret = settle(ret.pk, refund)
    if ret.status == "failed":
        raise ReturnError(f"Возврат не прошёл: {ret.error}")
    return ret


def _send(order, ret):
    """Запрос возврата в ЮKassa. Повтор с тем же ret — тот же ключ, тот же возврат."""
    receipt = refund_receipt(order.payload, kop_to_rub(order.amount_kop), ret.lines)
    return create_refund(
        order.payment_id,
        kop_to_rub(ret.amount_kop),
        f"Возврат по заказу {order.order_id}",
        # Свой ключ у каждого возврата: ключ «платёж + сумма» склеил бы два
        # частичных возврата на равную сумму в один.
        key=f"order-return-{ret.pk}",
        receipt=receipt,
    )


def _fail(ret_pk, error):
    with transaction.atomic():
        ret = OrderReturn.objects.select_for_update().get(pk=ret_pk)
        if ret.status != "pending":
            return ret
        ret.status, ret.error = "failed", str(error)[:300]
        ret.points_returned = ret.points_revoked = 0
        ret.save(update_fields=["status", "error", "points_returned", "points_revoked"])
        return ret


def _kop(value):
    try:
        return int(round(float(value) * 100))
    except (TypeError, ValueError):
        return None


def settle(ret_pk, refund):
    """Применить к возврату его статус ПО ДАННЫМ ЮKassa. Идемпотентно.

    succeeded → «проведён»: баллы и статус заказа — ровно один раз (повторное
    уведомление застанет возврат уже не «в обработке» и ничего не проведёт);
    canceled → «не прошёл»; pending → ждём дальше, запоминаем номер возврата.
    """
    order_id = OrderReturn.objects.values_list("order_id", flat=True).get(pk=ret_pk)
    with transaction.atomic():
        # Порядок блокировок как в make_return: заказ, потом возврат.
        order = Order.objects.select_for_update().get(pk=order_id)
        ret = OrderReturn.objects.select_for_update().get(pk=ret_pk)
        rid = refund.get("refundId") or ""
        if rid and ret.refund_id != rid:
            if ret.refund_id:
                log.error("Возврат %s: ЮKassa прислала другой номер %s (у нас %s)",
                          ret.pk, rid, ret.refund_id)
                return ret
            ret.refund_id = rid
            ret.save(update_fields=["refund_id"])
        if ret.status != "pending":
            return ret

        status = refund.get("status")
        paid_back = _kop(refund.get("amount")) if refund.get("amount") else None
        if status == "succeeded" and paid_back is not None and paid_back != ret.amount_kop:
            log.error("Возврат %s: ЮKassa вернула %s ₽, а оформлено %.2f ₽ — "
                      "нужна ручная сверка", ret.pk, refund.get("amount"),
                      ret.amount_kop / 100)
            return ret
        if status == "canceled":
            ret.status, ret.error = "failed", "ЮKassa отклонила возврат"
            ret.points_returned = ret.points_revoked = 0
            ret.save(update_fields=["status", "error", "points_returned", "points_revoked"])
            return ret
        if status != "succeeded":
            return ret

        ret.status, ret.error = "done", ""
        ret.points_returned = return_redeemed_points(
            order, ret.points_returned,
            f"Возврат баллов: возврат товара по заказу №{order.order_id}",
        )
        ret.points_revoked = revoke_earned_points(
            order, ret.points_revoked,
            f"Отмена начисления: возврат товара по заказу №{order.order_id}",
        )
        ret.save(update_fields=["status", "error", "points_returned", "points_revoked"])
        goods = {row["index"] for row in _rows(order) if row["subject"] == "commodity"}
        back = set()
        for other in order.returns.filter(status="done"):
            back.update(int(i) for i in other.lines)
        completes = back >= goods
        if completes:
            order.payment_status = "refunded"
            order.status = "cancelled"
            order.save(update_fields=["payment_status", "status"])
        else:
            order.payment_status = "partially_refunded"
            order.save(update_fields=["payment_status"])

    if not completes:
        # Полный возврат покупатель и так увидит: смена статуса заказа шлёт уведомление.
        _notify_partial(order, ret)
    return ret


def apply_refund_info(info):
    """Уведомление/ответ ЮKassa о возврате → наш OrderReturn. None — возврат не наш.

    Ищем по номеру возврата; если номер ещё не сохранён (ответ на запрос не дошёл
    до нас, а уведомление — дошло), то по платежу и сумме среди «в обработке».
    """
    rid = info.get("refundId") or ""
    ret = OrderReturn.objects.filter(refund_id=rid).first() if rid else None
    if ret is None and info.get("paymentId"):
        ret = OrderReturn.objects.filter(
            order__payment_id=info["paymentId"], status="pending", refund_id="",
            amount_kop=_kop(info.get("amount")),
        ).first()
    if ret is None:
        return None
    return settle(ret.pk, info)


def reconcile_returns(now=None) -> dict:
    """Досверить возвраты «в обработке» с ЮKassa (фоновая задача).

    Номер возврата известен — спрашиваем статус. Неизвестен (ответ не дошёл) —
    повторяем запрос с тем же ключом: ЮKassa вернёт уже созданный возврат или
    создаст его, если первый запрос до неё не дошёл. Ключ ЮKassa помнит сутки,
    поэтому старые «зависшие» возвраты без номера не трогаем — их разбирает человек.
    """
    now = now or timezone.now()
    stats = {"done": 0, "failed": 0, "waiting": 0, "errors": 0, "manual": 0}
    rows = OrderReturn.objects.filter(
        status="pending", created_at__lt=now - RECONCILE_AFTER
    ).select_related("order").order_by("created_at")[:200]
    for ret in rows:
        try:
            if ret.refund_id:
                info = fetch_refund(ret.refund_id)
            elif ret.created_at >= now - RESEND_WITHIN:
                info = _send(ret.order, ret)
            else:
                log.error("Возврат %s по заказу %s завис без номера ЮKassa больше суток — "
                          "сверить вручную", ret.pk, ret.order.order_id)
                stats["manual"] += 1
                continue
        except PaymentUncertain:
            stats["errors"] += 1
            continue
        except (PaymentError, ValueError) as e:
            if ret.refund_id:
                # Номер есть, а статус не отдают — не повод считать возврат неудачным.
                log.error("Возврат %s: не удалось узнать статус: %s", ret.pk, e)
                stats["errors"] += 1
            else:
                # Повтор с тем же ключом ЮKassa отклонила — возврата нет.
                _fail(ret.pk, str(e))
                stats["failed"] += 1
            continue
        state = settle(ret.pk, info).status
        stats[{"done": "done", "failed": "failed"}.get(state, "waiting")] += 1
    return stats


def _notify_partial(order, ret):
    try:
        from notifications.models import create_notification

        text = f"По заказу №{order.order_id} вернём {ret.amount_kop / 100:.2f} ₽"
        if ret.points_returned:
            text += f", на счёт вернутся {ret.points_returned} баллов"
        create_notification(order.user_id, "Возврат оформлен", text + ".", "order", order.order_id)
    except Exception:
        # Уведомление — не часть возврата: деньги и баллы уже проведены.
        pass
