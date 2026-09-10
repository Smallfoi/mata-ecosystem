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
import urllib.request

_API = "https://api.yookassa.ru/v3"

# Способ оплаты: только СБП (D-71, решение владельца 10.09.2026).
#
# Цифры — из подписываемого договора ЮKassa, а не из интерфейса кабинета: там
# показана одна комиссия, а в договоре их две — оператора и отдельно платёжного
# агрегатора. С НДС на комиссию оператора выходит СБП ≈ 2,0%, карта ≈ 4,4%.
# SberPay и T-Pay стоят как карта, выгоды не дают.
#
# Принятый риск: покупателя без банковского приложения ведём в тупик. Если это
# проявится в доле брошенных оплат — `PAYMENT_METHOD=any` покажет все способы,
# правка кода не нужна.
def _default_method() -> str:
    return (os.environ.get("PAYMENT_METHOD") or "sbp").strip().lower()
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


def payment_enabled() -> bool:
    return bool(os.environ.get("PAYMENT_PROVIDER"))


# Оплата при получении: Store присылает `cash`, сайт — `cod`. Онлайн платить
# нечего — деньги берёт курьер или пункт выдачи.
ON_DELIVERY = frozenset({"cash", "cod"})


def pays_on_delivery(payload) -> bool:
    """Покупатель выбрал оплату при получении.

    Способ не указан — считаем онлайн: безопаснее придержать заказ до оплаты,
    чем отдать на сборку то, за что никто не заплатит.
    """
    checkout = (payload or {}).get("checkoutData") or {}
    return str(checkout.get("paymentType") or "").strip().lower() in ON_DELIVERY


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
        raise PaymentError(f"ЮKassa {e.code}: {detail or e.reason}") from e
    except Exception as e:  # таймаут, DNS, обрыв
        raise PaymentError(f"ЮKassa недоступна: {e}") from e


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
    """Сумма в формате ЮKassa: строка с двумя знаками ('1234.00')."""
    return f"{float(amount):.2f}"


def _idem_key(*parts) -> str:
    """Детерминированный ключ идемпотентности (≤64 символов по требованию API)."""
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()


def _result(data) -> dict:
    """Ответ ЮKassa → наш контракт {status, paymentId, confirmationUrl}."""
    return {
        "status": _STATUS_MAP.get(data.get("status"), "pending"),
        "paymentId": data.get("id") or "",
        "confirmationUrl": (data.get("confirmation") or {}).get("confirmation_url") or "",
    }


def create_payment(order_id, amount, return_url="", reference=None,
                   method=None, receipt=None) -> dict:
    """Создать платёж. Возвращает {status, paymentId, confirmationUrl, method}.

    `reference` — глобально уникальный номер заказа для провайдера (см. модуль).
    Без него берём `order_id`, но это допустимо только там, где уникальность
    гарантирована иначе (например, в тестах с одним пользователем).

    `method` — способ оплаты ("sbp", "bank_card"…); по умолчанию из `PAYMENT_METHOD`.
    `receipt` — состав чека по 54-ФЗ (`orders/receipt.py`), если фискализация включена.

    Dev (без провайдера) — сразу 'paid': оплата не требуется.
    Прод — реальный платёж ЮKassa; ошибка провайдера поднимается как PaymentError,
    чтобы заказ НЕ был помечен оплаченным по недоразумению.
    """
    if not payment_enabled():
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
    chosen = (method or _default_method()).strip().lower()
    if chosen and chosen != "any":
        # Сразу ведём покупателя в нужный способ: для СБП ЮKassa возвращает
        # ссылку qr.nspk.ru — на телефоне она открывает банковское приложение,
        # на компьютере её показываем QR-кодом.
        body["payment_method_data"] = {"type": chosen}
    if receipt:
        body["receipt"] = receipt
    data = _request("POST", "/payments", body, _idem_key("payment", ref, _money(amount)))
    result = _result(data)
    result["method"] = chosen or "any"
    return result


def fetch_payment(payment_id) -> dict:
    """Актуальный статус платежа ПО ДАННЫМ ЮKassa.

    Используется вебхуком: тело уведомления приходит с публичного эндпоинта и
    подписи не имеет, поэтому верим не ему, а ответу API по нашим ключам.
    """
    return _result(_request("GET", f"/payments/{payment_id}"))


def create_refund(payment_id, amount, description="") -> dict:
    """Вернуть деньги покупателю (полностью или частично)."""
    body = {
        "payment_id": str(payment_id),
        "amount": {"value": _money(amount), "currency": "RUB"},
    }
    if description:
        body["description"] = description
    data = _request(
        "POST", "/refunds", body, _idem_key("refund", payment_id, _money(amount))
    )
    return {"status": data.get("status") or "", "refundId": data.get("id") or ""}
