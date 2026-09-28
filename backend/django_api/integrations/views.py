"""Точки подключения часов COROS.

Заявка в COROS требует указать три адреса ещё до выдачи ключей: куда вернуть
пользователя после разрешения доступа, куда присылать готовые тренировки и как
проверить, что наш сервис жив. Эти адреса должны существовать на момент
рассмотрения — поэтому они здесь, пусть пока и в минимальном виде.

Разбор данных появится, когда COROS выдаст Client ID и Secret: до этого проверить
подпись запроса нечем, а принимать чужие данные без проверки нельзя.
"""
import json
import secrets
import time

from django.conf import settings
from django.core.cache import cache

from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response


@api_view(["GET"])
@permission_classes([AllowAny])
def coros_callback(request):
    """Куда COROS возвращает человека после того, как он разрешил доступ.

    Придут `code` и `state`; на код меняется токен доступа — этот обмен добавим
    вместе с ключами. Сейчас отвечаем понятной страницей, а не ошибкой: человек
    не должен упереться в пустоту, если попал сюда раньше времени.
    """
    code = request.query_params.get("code", "")
    return Response({
        "ok": True,
        "received": bool(code),
        "detail": "Подключение COROS готовится. Вернитесь в приложение.",
    })


@api_view(["POST"])
@permission_classes([AllowAny])
def coros_push(request):
    """Сюда COROS присылает завершённые тренировки.

    Отвечаем 200 на любой корректный запрос: для отправителя это подтверждение
    доставки. Пока ключей нет, содержимое не разбираем — подпись проверить нечем,
    а верить неподписанным данным о чужих тренировках нельзя.
    """
    try:
        body = request.data if isinstance(request.data, (dict, list)) else json.loads(request.body or b"{}")
    except (ValueError, TypeError):
        return Response({"detail": "Некорректный JSON"}, status=400)
    count = len(body) if isinstance(body, list) else 1
    print(f"COROS push: получено записей {count} в {timezone.now().isoformat()}.")
    return Response({"ok": True, "received": count})


@api_view(["GET"])
@permission_classes([AllowAny])
def coros_status(request):
    """Проверка «сервис жив» — её COROS опрашивает сам."""
    return Response({"status": "ok", "service": "MATA integrations", "time": timezone.now().isoformat()})


# ─────────────────────────── Обмен с 1С (D-62) ───────────────────────────

def _onec_authorized(request) -> bool:
    """Токен обмена: заголовок Authorization: Bearer <токен>.
    Пустой токен в настройках = приём выключен."""
    expected = (settings.INTEGRATION_1C_TOKEN or "").strip()
    if not expected:
        return False
    got = (request.headers.get("Authorization") or "").strip()
    if got.lower().startswith("bearer "):
        got = got[7:].strip()
    return secrets.compare_digest(got, expected)


def _onec_items(request, key: str):
    """Принимаем и массив, и объект вида {"products": [...]} — 1С удобнее слать по-разному."""
    data = request.data
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in (key, "items", "data"):
            if isinstance(data.get(k), list):
                return data[k]
    return None


def _too_many(items) -> bool:
    """Защита от бессмысленно большой выгрузки: всё уже разобрано в память DRF,
    и дальше пачка такого размера будет только вредить. Порог высокий — полная
    выгрузка каталога в него укладывается."""
    from .onec import MAX_ITEMS
    return len(items) > MAX_ITEMS


def _reject(operation: str, detail: str, status: int):
    """Отказ + строка в журнале. Неудачную авторизацию пишем не чаще раза в 5 минут:
    иначе перебор токена превратился бы в способ забить базу."""
    from .log import record
    if status != 401 or cache.add(f"onec_authfail_{operation}", 1, 300):
        record(operation, detail=detail)
    return Response({"detail": detail}, status=status)


@api_view(["POST"])
@permission_classes([AllowAny])
def onec_categories(request):
    """Справочник категорий из 1С. Слать ПЕРЕД каталогом: товар с незаведённой
    категорией сохранится, но не покажется ни в одном разделе витрины."""
    started = time.monotonic()
    if not _onec_authorized(request):
        return _reject("categories", "Требуется токен обмена", 401)
    items = _onec_items(request, "categories")
    if items is not None and _too_many(items):
        from .onec import MAX_ITEMS
        return _reject("categories", f"Слишком большая выгрузка: {len(items)} категорий. "
                       f"Пришлите частями не больше {MAX_ITEMS} за раз.", 413)
    if items is None:
        return _reject("categories", "Ожидается массив категорий или {\"categories\": [...]}", 400)
    from .log import record
    from .onec import import_categories
    result = import_categories(items)
    record("categories", result, started=started)
    return Response(result)


@api_view(["POST"])
@permission_classes([AllowAny])
def onec_catalog(request):
    """Карточки товаров из 1С. Переопределённые владельцем поля не трогаем."""
    started = time.monotonic()
    if not _onec_authorized(request):
        return _reject("catalog", "Требуется токен обмена", 401)
    items = _onec_items(request, "products")
    if items is not None and _too_many(items):
        from .onec import MAX_ITEMS
        return _reject("catalog", f"Слишком большая выгрузка: {len(items)} товаров. "
                       f"Пришлите частями не больше {MAX_ITEMS} за раз.", 413)
    if items is None:
        return _reject("catalog", "Ожидается массив товаров или {\"products\": [...]}", 400)
    from .log import record
    from .onec import import_catalog
    result = import_catalog(items)
    record("catalog", result, started=started)
    return Response(result)


@api_view(["POST"])
@permission_classes([AllowAny])
def onec_prices(request):
    """Цены и остатки из 1С — частый поток."""
    started = time.monotonic()
    if not _onec_authorized(request):
        return _reject("prices", "Требуется токен обмена", 401)
    items = _onec_items(request, "prices")
    if items is not None and _too_many(items):
        from .onec import MAX_ITEMS
        return _reject("prices", f"Слишком большая выгрузка: {len(items)} позиций. "
                       f"Пришлите частями не больше {MAX_ITEMS} за раз.", 413)
    if items is None:
        return _reject("prices", "Ожидается массив позиций или {\"prices\": [...]}", 400)
    from .log import record
    from .onec import import_prices
    result = import_prices(items)
    record("prices", result, started=started)
    return Response(result)


@api_view(["GET"])
@permission_classes([AllowAny])
def onec_orders(request):
    """Очередь заказов для 1С. Заказ остаётся в очереди, пока 1С не подтвердит приём
    через `1c/orders/ack` — оборванная связь не должна стоить покупателю заказа."""
    started = time.monotonic()
    if not _onec_authorized(request):
        return _reject("orders", "Требуется токен обмена", 401)
    from .log import record
    from .onec_orders import MAX_ORDERS_PER_PULL, order_to_json, pending_orders

    try:
        limit = int(request.query_params.get("limit") or MAX_ORDERS_PER_PULL)
    except (TypeError, ValueError):
        limit = MAX_ORDERS_PER_PULL
    rows = pending_orders(limit)
    result = {"orders": [order_to_json(o) for o in rows]}
    record("orders", {"received": len(rows), "updated": len(rows)}, started=started)
    return Response(result)


@api_view(["POST"])
@permission_classes([AllowAny])
def onec_orders_ack(request):
    """1С подтверждает, что документы созданы: снимаем заказы с очереди."""
    started = time.monotonic()
    if not _onec_authorized(request):
        return _reject("orders", "Требуется токен обмена", 401)
    body = request.data if isinstance(request.data, dict) else {}
    ids = body.get("orderIds")
    # serverIds — глобальные номера заказов (аудит B06), однозначны; orderIds —
    # короткие номера, старый контракт. Можно прислать любое из двух или оба.
    server_ids = body.get("serverIds")
    if isinstance(request.data, list):
        ids = request.data
    if ids is None and isinstance(server_ids, list):
        ids = []
    if not isinstance(ids, list) or not isinstance(server_ids or [], list):
        return _reject("orders", "Ожидается {\"orderIds\": [...]} или {\"serverIds\": [...]}", 400)

    from .log import record
    from .onec_orders import _ambiguous_error, mark_taken

    result = mark_taken(ids, server_ids or [])
    errors = [f"{o}: заказ не найден" for o in result["unknown"]]
    errors += [f"serverId {o}: заказ не найден" for o in result["unknownServerIds"]]
    errors += [_ambiguous_error(o) for o in result["ambiguous"]]
    record("orders", {"received": len(ids) + len(server_ids or []),
                      "updated": result["acked"], "errors": errors},
           started=started)
    return Response(result)


@api_view(["POST"])
@permission_classes([AllowAny])
def onec_order_status(request):
    """Статусы заказов из 1С: принят → собран → отгружен → доставлен/отменён."""
    started = time.monotonic()
    if not _onec_authorized(request):
        return _reject("order-status", "Требуется токен обмена", 401)
    items = _onec_items(request, "orders")
    if items is not None and _too_many(items):
        from .onec import MAX_ITEMS
        return _reject("order-status", f"Слишком большая выгрузка: {len(items)} заказов. "
                       f"Пришлите частями не больше {MAX_ITEMS} за раз.", 413)
    if items is None:
        return _reject("order-status", "Ожидается массив статусов или {\"orders\": [...]}", 400)

    from .log import record
    from .onec_orders import apply_statuses

    result = apply_statuses(items)
    record("order-status", result, started=started)
    return Response(result)


@api_view(["GET"])
@permission_classes([AllowAny])
def onec_status(request):
    """Проверка «приём работает» — её опрашивает сторона 1С."""
    return Response({
        "status": "ok",
        "service": "MATA 1C exchange",
        "enabled": bool((settings.INTEGRATION_1C_TOKEN or "").strip()),
        "time": timezone.now().isoformat(),
    })
