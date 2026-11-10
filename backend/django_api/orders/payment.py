"""Оплата заказов — ЮKassa (D-13) + провайдер-агностичный слой.

Без `PAYMENT_PROVIDER` — dev-режим: оплата не требуется, заказ сразу «оплачен»
(поведение dev/CI не меняется). С `PAYMENT_PROVIDER=yookassa` + ключами магазина
работает реальная ЮKassa: создаём платёж → отдаём `confirmationUrl` для редиректа,
подтверждение прилетает вебхуком (`POST /v1/payments/webhook`).

Почему тут `urllib`, а не `requests`: в зависимостях бэкенда HTTP-клиента нет
(тот же приём, что в `accounts/sms.py`) — не тянем пакет ради трёх запросов.

**Деньги — идемпотентно.** Ключ идемпотентности ЮKassa считается детерминированно
от (номер платежа + сумма): повтор «Оплатить» по тому же заказу возвращает ТОТ ЖЕ
платёж, а не создаёт второй. Это защита от двойного списания у покупателя.

**Номер заказа обязан быть уникальным ГЛОБАЛЬНО.** Клиентский `order_id` (SS-12345)
уникален только в паре с пользователем — модель так и устроена. Если считать ключ
идемпотентности от него, два разных покупателя с одинаковым номером и одинаковой
суммой получат ОДИН платёж на двоих: второму вернётся чужая ссылка на оплату, а мы
свяжем чужой платёж не с тем заказом. Поэтому наружу уходит `reference` — номер
заказа плюс первичный ключ записи; его же передаём в metadata и описание.
"""
import base64
import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request

from .money import rub_str, to_kop

_API = "https://api.yookassa.ru/v3"

# Способ оплаты — только СБП (D-71, D-72). Не настраивается и не выбирается
# клиентом: владелец закрыл все остальные пути оплаты.
PAYMENT_METHOD = "sbp"
_TIMEOUT = 15  # сек: ЮKassa отвечает быстро, дольше держать воркер gunicorn незачем

# Статусы ЮKassa → наши (модель Order.payment_status).
_STATUS_MAP = {
    "succeeded": "paid",
    "canceled": "canceled",
    "pending": "pending",
    "waiting_for_capture": "pending",
}


class PaymentError(Exception):
    """Провайдер недоступен или отказал. Наверх — понятная ошибка, НЕ «оплачено»."""


class PaymentUncertain(PaymentError):
    """Ответа нет (таймаут, обрыв, 5xx) — операция у провайдера МОГЛА пройти.

    Для возврата это не «не прошёл»: считать его неудачным и дать сотруднику
    повторить значит рискнуть вернуть деньги дважды (аудит B04). Такой исход
    сверяем повтором с тем же ключом идемпотентности или запросом статуса.
    """


def payment_enabled() -> bool:
    return bool(os.environ.get("PAYMENT_PROVIDER"))


def dev_mode() -> bool:
    """Режим разработки — тот же признак, что у настроек (`DJANGO_DEBUG=1` по умолчанию).

    Читаем окружение, а не `settings.DEBUG`: тестовый прогон Django принудительно
    выключает DEBUG, и в тестах любой режим выглядел бы боевым.
    """
    return os.environ.get("DJANGO_DEBUG", "1") == "1"


def _creds():
    """(shop_id, secret_key) или None, если ключи не заданы."""
    shop = (os.environ.get("YOOKASSA_SHOP_ID") or "").strip()
    secret = (os.environ.get("YOOKASSA_SECRET_KEY") or "").strip()
    return (shop, secret) if shop and secret else None


def _http(method, url, payload=None, headers=None):
    """Единственная точка сетевого ввода-вывода — её и подменяют тесты."""
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        # Тело ошибки ЮKassa содержит описание — оно ценнее голого кода.
        try:
            detail = json.loads(e.read().decode("utf-8") or "{}").get("description", "")
        except Exception:
            detail = ""
        # 4xx — ЮKassa запрос разобрала и отклонила: операции нет. 5xx — сбой на её
        # стороне, исход неизвестен.
        cls = PaymentUncertain if e.code >= 500 else PaymentError
        raise cls(f"ЮKassa {e.code}: {detail or e.reason}") from e
    except Exception as e:  # таймаут, DNS, обрыв — запрос мог дойти
        raise PaymentUncertain(f"ЮKassa недоступна: {e}") from e


def _request(method, path, payload=None, idempotence_key=None):
    creds = _creds()
    if not creds:
        raise PaymentError("Не заданы YOOKASSA_SHOP_ID / YOOKASSA_SECRET_KEY")
    shop, secret = creds
    token = base64.b64encode(f"{shop}:{secret}".encode()).decode()
    headers = {"Authorization": f"Basic {token}", "Content-Type": "application/json"}
    if idempotence_key:
        headers["Idempotence-Key"] = idempotence_key
    return _http(method, f"{_API}{path}", payload, headers)


def _money(amount) -> str:
    """Сумма в формате ЮKassa: строка с двумя знаками ('1234.00').
    Через Decimal (ROUND_HALF_UP): та же сумма, что у заказа и в чеке (аудит B09)."""
    return rub_str(to_kop(amount))


def _idem_key(*parts) -> str:
    """Детерминированный ключ идемпотентности (≤64 символов по требованию API)."""
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()


def _result(data) -> dict:
    """Ответ ЮKassa → наш контракт {status, paymentId, confirmationUrl}.

    Плюс то, что сверяется с заказом перед «оплачено» (аудит B01): сумма, валюта
    и reference из metadata. Наружу (клиентам) эти поля не отдаются — см. views.
    """
    amount = data.get("amount") or {}
    return {
        "status": _STATUS_MAP.get(data.get("status"), "pending"),
        "paymentId": data.get("id") or "",
        "confirmationUrl": (data.get("confirmation") or {}).get("confirmation_url") or "",
        "amount": str(amount.get("value") or ""),
        "currency": str(amount.get("currency") or ""),
        "reference": str((data.get("metadata") or {}).get("reference") or ""),
    }


def payment_reference(order) -> str:
    """Глобально уникальный номер заказа для провайдера (см. шапку модуля)."""
    return f"{order.order_id}-{order.pk}"


def _kop(value):
    """Сумма в копейках (целое) или None, если это не число."""
    if value in (None, ""):
        return None
    try:
        return to_kop(value)
    except ValueError:
        return None


def payment_mismatch(order, info) -> str:
    """Почему этот платёж НЕЛЬЗЯ засчитать заказу; пустая строка — всё сходится.

    «Оплачено» ставим, только если провайдер подтвердил ровно то, что мы просили:
    тот же платёж, та же сумма до копейки, рубли и наш reference. Иначе (заказ
    успели поменять, платёж от другого заказа, сбой провайдера) заказ остаётся
    неоплаченным, а расхождение уходит в лог ошибок — разбирает человек.
    """
    pid = info.get("paymentId") or ""
    if order.payment_id and pid and pid != order.payment_id:
        return f"платёж {pid} не относится к заказу (ждали {order.payment_id})"
    if info.get("currency") != "RUB":
        return f"валюта платежа «{info.get('currency') or '—'}», ждали RUB"
    paid, due = _kop(info.get("amount")), order.amount_kop
    if paid is None or paid != due:
        return f"сумма платежа {info.get('amount') or '—'} ≠ сумме заказа {rub_str(due)}"
    ref = payment_reference(order)
    if info.get("reference") != ref:
        return f"reference платежа «{info.get('reference') or '—'}», ждали «{ref}»"
    return ""


def create_payment(order_id, amount, return_url="", reference=None,
                   receipt=None) -> dict:
    """Создать платёж. Возвращает {status, paymentId, confirmationUrl, method}.

    `reference` — глобально уникальный номер заказа для провайдера (см. модуль).
    Без него берём `order_id`, но это допустимо только там, где уникальность
    гарантирована иначе (например, в тестах с одним пользователем).

    `receipt` — состав чека по 54-ФЗ (`orders/receipt.py`), если фискализация включена.

    Dev (без провайдера) — сразу 'paid': оплата не требуется.
    Прод — реальный платёж ЮKassa; ошибка провайдера поднимается как PaymentError,
    чтобы заказ НЕ был помечен оплаченным по недоразумению.
    """
    if not payment_enabled():
        # Без провайдера платить некуда. В разработке это упрощение: заказ сразу
        # «оплачен», чтобы проходить путь целиком. На проде так нельзя — вышло бы
        # «оплачено» без денег (D-72). Номера платежа нет, поэтому и в разработке
        # такой заказ на сборку не уходит.
        if not dev_mode():
            raise PaymentError("Оплата временно недоступна")
        return {"status": "paid", "paymentId": "", "confirmationUrl": ""}

    # Куда ЮKassa вернёт покупателя после оплаты. Обязательное поле API.
    back = (return_url or os.environ.get("YOOKASSA_RETURN_URL") or "").strip()
    if not back:
        raise PaymentError(
            "Не задан returnUrl: передайте его в теле запроса или задайте YOOKASSA_RETURN_URL"
        )
    ref = str(reference or order_id)
    body = {
        "amount": {"value": _money(amount), "currency": "RUB"},
        "capture": True,  # одностадийная оплата: списываем сразу после подтверждения
        "confirmation": {"type": "redirect", "return_url": back},
        "description": f"Заказ {order_id}",
        # order_id — для чтения человеком, reference — то, по чему платёж однозначно
        # сопоставляется с записью заказа, если вдруг потеряем payment_id.
        "metadata": {"order_id": str(order_id), "reference": ref},
    }
    # Единственный способ — СБП (D-72). Для СБП ЮKassa возвращает ссылку
    # qr.nspk.ru: на телефоне она открывает банковское приложение, на компьютере
    # её показываем QR-кодом. Выбор клиента не принимаем — иначе подменой запроса
    # открывается оплата картой.
    body["payment_method_data"] = {"type": PAYMENT_METHOD}
    if receipt:
        body["receipt"] = receipt
    data = _request("POST", "/payments", body, _idem_key("payment", ref, _money(amount)))
    result = _result(data)
    result["method"] = PAYMENT_METHOD
    return result


def fetch_payment(payment_id) -> dict:
    """Актуальный статус платежа ПО ДАННЫМ ЮKassa.

    Используется вебхуком: тело уведомления приходит с публичного эндпоинта и
    подписи не имеет, поэтому верим не ему, а ответу API по нашим ключам.
    """
    return _result(_request("GET", f"/payments/{payment_id}"))


def create_refund(payment_id, amount, description="", key=None, receipt=None) -> dict:
    """Вернуть деньги покупателю (полностью или частично).

    `key` — ключ идемпотентности возврата. У частичных возвратов он обязан быть свой:
    ключ «платёж + сумма» склеил бы два возврата на равную сумму в один (D-73).
    `receipt` — чек возврата по 54-ФЗ, если фискализация включена.
    """
    body = {
        "payment_id": str(payment_id),
        "amount": {"value": _money(amount), "currency": "RUB"},
    }
    if description:
        body["description"] = description
    if receipt:
        body["receipt"] = receipt
    data = _request(
        "POST", "/refunds", body, _idem_key("refund", payment_id, key or _money(amount))
    )
    return _refund_result(data)


def _refund_result(data) -> dict:
    """Возврат ЮKassa → {status, refundId, paymentId, amount}.

    status — как у ЮKassa: pending (в обработке), succeeded (деньги ушли),
    canceled (отклонён). Окончателен только succeeded/canceled.
    """
    amount = data.get("amount") or {}
    return {
        "status": data.get("status") or "",
        "refundId": data.get("id") or "",
        "paymentId": data.get("payment_id") or "",
        "amount": str(amount.get("value") or ""),
    }


def fetch_receipts(payment_id) -> list:
    """Чеки, которые касса пробила по платежу (чек оплаты, чеки возвратов)."""
    query = urllib.parse.urlencode({"payment_id": payment_id})
    return _request("GET", f"/receipts?{query}").get("items") or []


def fetch_refund(refund_id) -> dict:
    """Актуальный статус возврата ПО ДАННЫМ ЮKassa (тело вебхука не подписано)."""
    return _refund_result(_request("GET", f"/refunds/{refund_id}"))
