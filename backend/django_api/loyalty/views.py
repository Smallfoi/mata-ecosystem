from rest_framework.decorators import api_view
from rest_framework.response import Response

from common.cache import LOYALTY_TTL, cache_json, loyalty_key
from common.security import user_id_from_request

from .models import LoyaltyTransaction, add_txn, balance_of, level_for

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
    """Серверная трата баллов (Store-чекаут). Авторитетно проверяет баланс и
    идемпотентна по orderId — нельзя уйти в минус и нельзя списать дважды.
    body: {amount: >0, orderId, description}."""
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

    balance = balance_of(uid)
    order_id = d.get("orderId")

    # Идемпотентность: повторный redeem того же заказа не списывает второй раз.
    if order_id:
        dup = LoyaltyTransaction.objects.filter(
            user_id=uid, order_id=order_id, source="redeem"
        ).first()
        if dup:
            return Response(
                {"ok": True, "deduped": True, "balance": balance, "spent": -dup.amount}
            )

    if amount > balance:
        return Response(
            {"detail": "Недостаточно баллов", "balance": balance}, status=400
        )

    add_txn(uid, -amount, "redeem", d.get("description") or "Оплата баллами", order_id)
    new_balance = balance - amount
    return Response(
        {"ok": True, "balance": new_balance, "spent": amount, "level": level_for(new_balance)}
    )


# Баллы — это деньги в Store, поэтому начисляет их ТОЛЬКО сервер (анти-чит S-04).
#   runnerRun       → /v1/runs (расчёт по дистанции и времени);
#   runnerTerritory → /v1/territories/capture (после валидной геометрии захвата);
#   purchase/registration → /v1/orders (по сумме заказа / первому заказу);
#   runnerMilestone/runnerDivision/runnerSeason → league и runs.milestones;
#   redeem          → /v1/loyalty/redeem (там проверяется баланс).
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
