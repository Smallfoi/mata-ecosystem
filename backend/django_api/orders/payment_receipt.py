"""Чек оплаты из ЮKassa — его номер уходит в 1С вместе с заказом (D-101).

Зачем. При оплате касса пробивает чек ПРЕДОПЛАТЫ: деньги получены, вещь ещё на
складе. При сборке склад в 1С пробивает второй чек — «полный расчёт» с зачётом
этого аванса и кодами маркировки. Чтобы зачесть аванс, 1С нужны реквизиты первого
чека: номер фискального документа, номер фискального накопителя, фискальный
признак и время. Их знает только касса, а мы узнаём у ЮKassa по номеру платежа.

Почему ждём. Касса пробивает чек не в момент оплаты, а через секунды или минуты
после неё. Поэтому оплаченный заказ какое-то время ждёт чек и только потом уходит
в 1С — иначе склад получил бы заказ без реквизитов. Ждём не дольше
`WAIT_MINUTES`: сломанная касса не должна останавливать сборку. Отпущенный без
чека заказ уходит в 1С с `receipt: null`, а чек мы продолжаем запрашивать — он
появится в админке.

Опрос — раз в минуту (`orders.sync_payment_receipts`), а не цепочка повторов
после оплаты: так ожидание переживает перезапуск воркера, а пропущенный запуск
просто подхватит следующий.
"""
import logging
from datetime import timedelta

from django.utils import timezone

from .payment import PaymentError, PaymentUncertain, fetch_receipts
from .receipt import receipts_enabled

log = logging.getLogger(__name__)

# Сколько держим оплаченный заказ, ожидая чек, прежде чем отдать его в 1С без чека.
WAIT_MINUTES = 30

# Сколько ещё спрашиваем ЮKassa о чеке, если заказ уже ушёл без него.
GIVE_UP_HOURS = 24

# Сколько заказов опрашиваем за один проход: по запросу к ЮKassa на каждый.
BATCH = 100

WAITING = "waiting"          # оплата есть, чека ещё нет
SUCCEEDED = "succeeded"      # касса пробила чек, реквизиты есть
CANCELED = "canceled"        # касса чек не пробила
UNAVAILABLE = "unavailable"  # ЮKassa отказала в запросе (например, касса не через неё)


def expects_receipt(order) -> bool:
    """Будет ли у оплаты чек. Тестовая оплата (D-97) проходит без денег — и без чека."""
    return receipts_enabled() and bool(order.payment_id) and not order.is_test


def held_until():
    """Заказы, оплаченные позже этой отметки и ждущие чек, в 1С пока не отдаём."""
    return timezone.now() - timedelta(minutes=WAIT_MINUTES)


def _from_yookassa(item: dict) -> dict:
    status = item.get("status")
    out = {"status": SUCCEEDED if status == "succeeded" else CANCELED,
           "id": item.get("id") or ""}
    if status == "succeeded":
        out.update({
            "fiscalDocumentNumber": str(item.get("fiscal_document_number") or ""),
            "fiscalStorageNumber": str(item.get("fiscal_storage_number") or ""),
            "fiscalAttribute": str(item.get("fiscal_attribute") or ""),
            "registeredAt": item.get("registered_at") or "",
        })
    return out


def sync(order) -> bool:
    """Спросить ЮKassa о чеке оплаты заказа. True — ждать больше нечего."""
    try:
        items = fetch_receipts(order.payment_id)
    except PaymentUncertain as e:
        # Сбой сети или ЮKassa — спросим на следующем проходе.
        log.warning("Чек по заказу %s: ЮKassa не ответила (%s)", order.order_id, e)
        return False
    except PaymentError as e:
        # Запрос отклонён — повтор не поможет. Не держим заказ.
        log.error("Чек по заказу %s: ЮKassa отказала (%s)", order.order_id, e)
        order.receipt = {"status": UNAVAILABLE, "error": str(e)[:200]}
        order.save(update_fields=["receipt"])
        return True

    paid = [i for i in items if isinstance(i, dict) and i.get("type") == "payment"]
    final = [i for i in paid if i.get("status") in ("succeeded", "canceled")]
    if not final:
        return False  # чек ещё в кассе
    # Удачный чек важнее отменённого: касса могла пробить его со второй попытки.
    best = next((i for i in final if i.get("status") == "succeeded"), final[0])
    order.receipt = _from_yookassa(best)
    order.save(update_fields=["receipt"])
    if order.receipt["status"] != SUCCEEDED:
        log.error("Касса не пробила чек оплаты по заказу %s (платёж %s)",
                  order.order_id, order.payment_id)
    return True


def sync_waiting() -> dict:
    """Проход по всем заказам, ждущим чек (раз в минуту)."""
    from .models import Order

    since = timezone.now() - timedelta(hours=GIVE_UP_HOURS)
    rows = list(
        Order.objects.filter(receipt__contains={"status": WAITING}, paid_at__gte=since)
        .order_by("paid_at")[:BATCH]
    )
    done = sum(1 for order in rows if sync(order))
    return {"checked": len(rows), "done": done}


def for_1c(order):
    """Реквизиты чека оплаты для 1С. None — чека нет (не ждали, ещё не пришёл, не пробит)."""
    receipt = order.receipt or {}
    if receipt.get("status") != SUCCEEDED:
        return None
    return {
        "id": receipt.get("id") or "",
        "fiscalDocumentNumber": receipt.get("fiscalDocumentNumber") or "",
        "fiscalStorageNumber": receipt.get("fiscalStorageNumber") or "",
        "fiscalAttribute": receipt.get("fiscalAttribute") or "",
        "registeredAt": receipt.get("registeredAt") or "",
    }
