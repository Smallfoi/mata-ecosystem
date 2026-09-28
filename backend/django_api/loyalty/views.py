from rest_framework.decorators import api_view
from rest_framework.response import Response

from common.cache import LOYALTY_TTL, cache_json, loyalty_key
from common.security import user_id_from_request

from .models import (
    LoyaltyPartner,
    LoyaltyTransaction,
    add_txn,
    balance_of,
    level_for,
)

_TX_LIMIT = 200  # история: отдаём последние N (баланс считается по ВСЕМ через SQL)


@api_view(["GET"])
def account(request):
    uid = user_id_from_request(request)
    if not uid:
        return Response({"detail": "Нет токена"}, status=401)
    # Read-only показ карточки лояльности — кэш по uid + инвалидация из add_txn (D-29).
    # Redeem/add_txn НЕ читают этот кэш — там авторитетный balance_of.
    data = cache_json(loyalty_key(uid), LOYALTY_TTL, lambda: _account_payload(uid))
    return Response(data)


def _account_payload(uid):
    """Баланс (SQL-агрегат по всем транзакциям) + уровень + последние N операций + код."""
    from accounts.models import ensure_loyalty_code

    balance = balance_of(uid)
    rows = LoyaltyTransaction.objects.filter(user_id=uid).order_by("-created_at")[
        :_TX_LIMIT
    ]
    return {
        "balance": balance,
        "level": level_for(balance),
        "code": ensure_loyalty_code(uid),  # постоянный 6-значный код лояльности (для QR/кассы)
        "transactions": [r.to_json() for r in rows],
    }


@api_view(["POST"])
def redeem(request):
    """Прежний адрес траты баллов (выпущенные сборки Store зовут его ПОСЛЕ заказа).

    Баллы списывает сервер при оформлении заказа (D-72), поэтому обычно здесь
    просто подтверждается уже сделанное списание (`deduped`). Если списания по
    заказу ещё нет — работает тот же единый сервис `loyalty.wallet.redeem`, что и
    при оформлении (аудит B02): заказ должен существовать, сумма — совпадать со
    скидкой заказа, минимум и 30% — те же. Без заказа баллы не списываются вовсе:
    раньше здесь можно было списать сколько угодно на выдуманный orderId, а потом
    оформить заказ с этим id — и 30% уже не проверялись.

    body: {amount: >0, orderId, description}. Ответ прежний:
    {ok, balance, spent, level} или {ok, deduped, balance, spent}; ошибка — 400/404
    c `detail` (Store показывает его текстом) и `balance`.
    """
    from django.db import transaction

    from orders.models import Order

    from .wallet import lock_wallet, redeem as wallet_redeem, redeemed_on_order

    uid = user_id_from_request(request)
    if not uid:
        return Response({"detail": "Нет токена"}, status=401)
    d = request.data
    try:
        amount = int(d.get("amount") or 0)
    except (TypeError, ValueError):
        amount = 0
    if amount <= 0:
        return Response({"detail": "Некорректное количество баллов"}, status=400)
    order_id = str(d.get("orderId") or "").strip()

    def fail(detail, status=400):
        return Response({"detail": detail, "balance": balance_of(uid)}, status=status)

    if not order_id:
        return fail("Баллы списываются только при оформлении заказа")

    with transaction.atomic():
        lock_wallet(uid)
        # Идемпотентность: заказ уже оплачен баллами — второй раз не списываем.
        spent = redeemed_on_order(uid, order_id)
        if spent:
            return Response(
                {"ok": True, "deduped": True, "balance": balance_of(uid), "spent": spent}
            )
        order = Order.objects.filter(user_id=uid, order_id=order_id).first()
        if not order:
            return fail("Заказ не найден", status=404)
        if order.payment_status == "canceled" or order.status == "cancelled":
            return fail("Заказ отменён — баллы не списываются")
        if amount != int(order.points_redeemed or 0):
            return fail("Сумма списания не совпадает с заказом")
        order_sum = float(order.total or 0) + int(order.points_redeemed or 0)
        problem = wallet_redeem(
            uid, order_id, amount, order_sum, d.get("description") or "Оплата баллами"
        )
        if problem:
            return fail(problem)
    new_balance = balance_of(uid)
    return Response(
        {"ok": True, "balance": new_balance, "spent": amount, "level": level_for(new_balance)}
    )


# Баллы — это деньги в Store, поэтому начисляет их ТОЛЬКО сервер (анти-чит S-04).
#   runnerRun       → /v1/runs (расчёт по дистанции и времени);
#   runnerTerritory → /v1/territories/capture (после валидной геометрии захвата);
#   purchase/registration → /v1/orders (по сумме заказа / первому заказу);
#   runnerMilestone/runnerDivision/runnerSeason → league и runs.milestones;
#   redeem          → при оформлении заказа (loyalty.wallet.redeem; прежний
#                     /v1/loyalty/redeem — тот же сервис).
#
# Здесь БЕЛЫЙ список, а не чёрный — и это принципиально. Раньше стоял чёрный из
# четырёх источников, и он устарел молча: Квартал 2.0 добавил награды за вехи,
# дивизионы и сезоны, и ни один в список не попал. Клиент мог прислать
# `{"source": "runnerDivision", "amount": 999999}` и выписать себе денег.
# Хуже того, проходил и `redeem` с ПОЛОЖИТЕЛЬНОЙ суммой: списание превращалось
# в начисление.
#
# Чёрный список требует помнить о нём при каждом новом источнике. Белый —
# наоборот: новый источник по умолчанию запрещён, и чтобы его разрешить, надо
# прийти сюда и объяснить зачем. Сейчас клиенту не нужен ни один: всё, что
# приносит баллы, считает сервер.
_CLIENT_ALLOWED_SOURCES: set[str] = set()

# Потолок на случай, если в белый список когда-нибудь что-то добавят: даже
# разрешённый источник не должен уметь выписать состояние одной строкой.
MAX_CLIENT_AMOUNT = 1000


@api_view(["POST"])
def transactions(request):
    uid = user_id_from_request(request)
    if not uid:
        return Response({"detail": "Нет токена"}, status=401)
    d = request.data
    run_id = d.get("runId")
    order_id = d.get("orderId")
    source = str(d.get("source") or "")
    if source not in _CLIENT_ALLOWED_SOURCES:
        return Response(
            {"detail": "Баллы начисляет сервер — клиентские начисления не принимаются"},
            status=403,
        )
    try:
        amount = int(d.get("amount") or 0)
    except (TypeError, ValueError):
        return Response({"detail": "Сумма должна быть числом"}, status=400)
    if not 0 < amount <= MAX_CLIENT_AMOUNT:
        # Отрицательная сумма — это списание, у него свой адрес с проверкой баланса.
        return Response({"detail": "Недопустимая сумма начисления"}, status=400)
    # Идемпотентность: по (user, runId, source) для забегов и
    # по (user, orderId, source) для покупок/начислений за заказ — без дублей.
    if run_id and LoyaltyTransaction.objects.filter(
        user_id=uid, run_id=run_id, source=source
    ).exists():
        return Response({"ok": True, "deduped": True})
    if order_id and LoyaltyTransaction.objects.filter(
        user_id=uid, order_id=order_id, source=source
    ).exists():
        return Response({"ok": True, "deduped": True})
    add_txn(
        uid,
        amount,
        source,
        d.get("description") or "",
        order_id,
        run_id,
    )
    return Response({"ok": True})


@api_view(["GET"])
def partners(request):
    """Партнёры лояльности на карте (D-81). Публично, без токена: слой «Карты»
    показывает эти точки. Отдаём только активных; можно сузить по городу."""
    qs = LoyaltyPartner.objects.filter(is_active=True)
    city = (request.query_params.get("city") or "").strip()
    if city:
        qs = qs.filter(city__iexact=city)
    return Response({"partners": [p.to_json() for p in qs[:500]]})
