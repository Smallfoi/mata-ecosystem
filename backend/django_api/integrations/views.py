"""Точки подключения часов: COROS и Suunto.

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
from django.core import signing
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from common.security import user_id_from_request
from integrations import suunto, tasks
from integrations.models import WatchAccount


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


# ─────────────────────────── Часы Suunto ─────────────────────────────────
# Подпись `state`: своя соль, чтобы ссылка подключения не годилась больше нигде.
SUUNTO_STATE_SALT = "mata.suunto.connect"
# Полчаса на то, чтобы разрешить доступ. Дольше — это уже чужая вкладка.
SUUNTO_STATE_MAX_AGE = 30 * 60

# Suunto приняли нас в партнёрскую программу 05.10.2026 и дали доступ к Cloud API.
# При настройке приложения в их кабинете спрашивают адрес возврата, а у вебхуков —
# адрес приёма тренировок. Адреса должны отвечать уже в момент настройки, поэтому
# они здесь в минимальном виде, как это было сделано для COROS.
#
# Разбор данных появится вместе с ключами (Client ID/Secret и subscription key):
# до этого проверить подпись запроса нечем, а принимать чужие тренировки без
# проверки нельзя.


@api_view(["GET"])
def suunto_connect(request):
    """Начало подключения: отправляем человека разрешать доступ.

    Отдаём ССЫЛКУ, а не редирект: приложение открывает её во внешнем браузере,
    иначе вход в чужой аккаунт шёл бы внутри нашего окна — так делать не принято,
    и Suunto этого не любит.

    В `state` кладём подписанный идентификатор пользователя: когда Suunto вернёт
    человека, мы должны знать, чей это аккаунт, и не поверить подставленному id.
    """
    me = user_id_from_request(request)
    if not me:
        return Response({"detail": "Нет токена"}, status=401)
    if not suunto.configured():
        return Response({"detail": "Подключение Suunto ещё не настроено"}, status=503)
    state = signing.dumps({"uid": me}, salt=SUUNTO_STATE_SALT)
    return Response({"url": suunto.authorize_url(state)})


@api_view(["GET"])
@permission_classes([AllowAny])
def suunto_callback(request):
    """Куда Suunto возвращает человека после разрешения доступа (OAuth redirect).

    Страница открыта во внешнем браузере, без нашего токена — поэтому доступ
    публичный, а кто именно подключается, узнаём из подписанного `state`.
    Отвечаем человеческим текстом: сюда смотрит живой человек, а не программа.
    """
    code = (request.query_params.get("code") or "").strip()
    state = (request.query_params.get("state") or "").strip()
    if not code or not state:
        # Сюда попадают и при отказе («я передумал») — это не ошибка.
        return Response({"ok": False, "detail": "Подключение отменено."})
    try:
        uid = signing.loads(state, salt=SUUNTO_STATE_SALT, max_age=SUUNTO_STATE_MAX_AGE)["uid"]
    except (signing.BadSignature, KeyError, TypeError):
        return Response({"ok": False, "detail": "Ссылка устарела. Начните подключение заново."},
                        status=400)

    try:
        tokens = suunto.exchange_code(code)
    except suunto.SuuntoError as e:
        return Response({"ok": False, "detail": "Suunto не подтвердила доступ: %s" % e}, status=502)

    access = (tokens.get("access_token") or "").strip()
    if not access:
        return Response({"ok": False, "detail": "Suunto не вернула токен."}, status=502)

    WatchAccount.objects.update_or_create(
        user_id=uid, source="suunto",
        defaults={
            "external_id": str(tokens.get("user") or tokens.get("username") or "")[:120],
            "access_token": access,
            "refresh_token": (tokens.get("refresh_token") or "").strip(),
            "expires_at": suunto.expires_at(tokens),
            "connected_at": timezone.now(),
        },
    )
    return Response({"ok": True, "detail": "Часы Suunto подключены. Вернитесь в приложение."})


@api_view(["DELETE"])
def suunto_disconnect(request):
    """Отключить часы: токен удаляем целиком, а не помечаем неактивным."""
    me = user_id_from_request(request)
    if not me:
        return Response({"detail": "Нет токена"}, status=401)
    removed, _ = WatchAccount.objects.filter(user_id=me, source="suunto").delete()
    return Response({"ok": True, "removed": bool(removed)})


@api_view(["POST"])
@permission_classes([AllowAny])
def suunto_push(request):
    """Уведомление Suunto: у человека появилась новая тренировка.

    В теле всего два поля — `username` и `workoutid` (их FAQ). Самих данных нет,
    поэтому верить уведомлению и не нужно: мы идём за тренировкой сами, своим
    токеном. Подделать уведомление можно, но смысла нет — максимум мы лишний раз
    спросим про тренировку, которая и так есть у этого человека.

    Отвечаем сразу и всегда 200: отправитель ждёт подтверждение доставки, а не
    результат разбора. Работа уходит в фон (`integrations.tasks`).
    """
    try:
        body = request.data if isinstance(request.data, (dict, list)) else json.loads(request.body or b"{}")
    except (ValueError, TypeError):
        return Response({"detail": "Некорректный JSON"}, status=400)

    events = body if isinstance(body, list) else [body]
    queued = 0
    for event in events:
        if not isinstance(event, dict):
            continue
        username = str(event.get("username") or event.get("user") or "").strip()[:120]
        workout_id = str(event.get("workoutid") or event.get("workoutId") or "").strip()[:120]
        if not username or not workout_id:
            continue
        account = WatchAccount.objects.filter(source="suunto", external_id=username).first()
        if account is None:
            # Часы отключили или это чужой username — молча пропускаем: отвечать
            # «такого нет» значит подтверждать чужому, кто у нас есть.
            continue
        tasks.fetch_suunto_workout.delay(account.pk, workout_id)
        queued += 1
    return Response({"ok": True, "received": len(events), "queued": queued})


@api_view(["GET"])
@permission_classes([AllowAny])
def suunto_status(request):
    """Проверка «сервис жив»."""
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
