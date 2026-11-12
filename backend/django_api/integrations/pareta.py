"""Выдача Pareta — `/v1/analytics/*` (D-124, `docs/ANALYTICS_FOR_PARETA.md` §4).

Отдельный токен `PARETA_READ_TOKEN`, только чтение. Здесь себестоимость и продавцы,
поэтому каждое обращение пишем в журнал доступа (`ParetaAccess`), а сами данные —
никуда, кроме ответа.
"""
import secrets
from datetime import date

from django.conf import settings
from django.core.cache import cache
from django.utils.dateparse import parse_datetime
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .models import OneCDay, ParetaAccess

DAYS_LIMIT = 500
CATALOG_LIMIT = 1000


def _authorized(request) -> bool:
    expected = (getattr(settings, "PARETA_READ_TOKEN", "") or "").strip()
    if not expected:
        return False
    got = (request.headers.get("Authorization") or "").strip()
    if got.lower().startswith("bearer "):
        got = got[7:].strip()
    return secrets.compare_digest(got, expected)


def _log(request, status: int, rows: int = 0) -> None:
    """Строка в журнале доступа. Неудачные попытки — не чаще раза в 5 минут."""
    try:
        if status == 401 and not cache.add("pareta_authfail", 1, 300):
            return
        ParetaAccess.objects.create(path=request.get_full_path()[:200], status=status, rows=rows)
        if cache.add("pareta_access_pruned", 1, 24 * 3600):
            ParetaAccess.prune()
    except Exception:  # журнал не важнее ответа
        pass


def _deny(request):
    _log(request, 401)
    return Response({"detail": "Требуется токен Pareta"}, status=401)


def _limit(request, default):
    try:
        return max(1, min(int(request.query_params.get("limit") or default), default))
    except ValueError:
        return default


def _iso(dt):
    return dt.isoformat() if dt else None


def _cursor(day) -> str:
    """Курсор без «+»: в адресе он стал бы пробелом. Время — UTC с «Z»."""
    from datetime import timezone as dt_tz
    at = day.received_at.astimezone(dt_tz.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return f"{at}|{day.date.isoformat()}"


@api_view(["GET"])
@permission_classes([AllowAny])
def daily_list(request):
    """Дни, изменившиеся после момента. Курсор `next` — «отсюда продолжить»:
    перепроведённый задним числом день придёт снова, с новой version."""
    if not _authorized(request):
        return _deny(request)
    rows = OneCDay.objects.order_by("received_at", "date")
    cursor = (request.query_params.get("cursor") or "").strip()
    since = (request.query_params.get("updatedSince") or "").strip()
    if cursor:
        at, _, day = cursor.partition("|")
        at = parse_datetime(at)
        try:
            day = date.fromisoformat(day)
        except ValueError:
            day = None
        if at is None or day is None:
            _log(request, 400)
            return Response({"detail": "Некорректный cursor"}, status=400)
        from django.db.models import Q
        rows = rows.filter(Q(received_at__gt=at) | Q(received_at=at, date__gt=day))
    elif since:
        at = parse_datetime(since)
        if at is None:
            _log(request, 400)
            return Response({"detail": "updatedSince — дата-время ISO 8601"}, status=400)
        rows = rows.filter(received_at__gt=at)
    limit = _limit(request, DAYS_LIMIT)
    page = list(rows.only("date", "version", "generated_at", "received_at", "totals",
                          "counts")[:limit + 1])
    more = len(page) > limit
    page = page[:limit]
    days = [{
        "date": d.date.isoformat(), "version": d.version, "generatedAt": _iso(d.generated_at),
        "receivedAt": _iso(d.received_at), "totals": d.totals, "rows": d.counts,
    } for d in page]
    last = page[-1] if page else None
    _log(request, 200, len(days))
    return Response({
        "days": days,
        "next": _cursor(last) if more else None,
    })


@api_view(["GET"])
@permission_classes([AllowAny])
def daily_detail(request, day):
    """День как прислала 1С — `payload` байт в байт с тем, что пришло."""
    if not _authorized(request):
        return _deny(request)
    try:
        when = date.fromisoformat(day)
    except ValueError:
        _log(request, 400)
        return Response({"detail": "День — ГГГГ-ММ-ДД"}, status=400)
    row = OneCDay.objects.filter(date=when).first()
    if row is None:
        _log(request, 404)
        return Response({"detail": "Итогов за этот день нет"}, status=404)
    _log(request, 200, sum((row.counts or {}).values()))
    return Response({"date": row.date.isoformat(), "version": row.version,
                     "generatedAt": _iso(row.generated_at), "receivedAt": _iso(row.received_at),
                     "payload": row.payload})


def _variants(product, held):
    """Сколько можно продать по размерам: остаток 1С минус придержанное под заказами."""
    from orders.pricing import _left

    by_size = product.stock_by_size or {}
    if by_size:
        sizes = [str(s) for s in by_size]
    else:
        sizes = [""]
    out = []
    for size in sizes:
        left = _left(product, size)
        if left is None:
            out.append({"size": size, "available": None})
            continue
        out.append({"size": size, "available": max(0, left - held.get((product.id, size), 0))})
    return out


def _color(product) -> str:
    """Цвет позиции — только из поля 1С (как на витрине, `models_api`)."""
    return next((str(c).strip() for c in (product.colors or []) if str(c).strip()), "")


def _photos(product, gallery):
    """Фото именно этой модели и этого цвета — из той же галереи, что видит
    покупатель на витрине (`ProductPhoto`, до 6 на цвет). Нет галереи — старое
    фото позиции. По этим фото Pareta показывает клиенту «вы про эту модель?»,
    так что фото чужого цвета здесь недопустимо."""
    from catalog import photos as photolib

    shots = photolib.pick(gallery.get(product.shop_model_key or product.id), _color(product))
    if shots:
        return [s.to_json()["url"] for s in shots]
    main = product.network_image_url()
    return [main] if main else []


@api_view(["GET"])
@permission_classes([AllowAny])
def catalog(request):
    """Все позиции, включая снятые с витрины: Pareta видит историю продаж и тех
    товаров, что уже не продаются. Связь — по `id` из 1С, не по названию."""
    if not _authorized(request):
        return _deny(request)
    from catalog.models import Category, Product
    from orders.pricing import reserved_units

    rows = Product.objects.order_by("id").prefetch_related("barcodes")
    cursor = (request.query_params.get("cursor") or "").strip()
    if cursor:
        rows = rows.filter(id__gt=cursor)
    limit = _limit(request, CATALOG_LIMIT)
    page = list(rows[:limit + 1])
    more = len(page) > limit
    page = page[:limit]
    held = reserved_units({p.id: p for p in page})
    names = dict(Category.objects.values_list("id", "name"))
    from catalog import photos as photolib
    gallery = photolib.by_model({p.shop_model_key or p.id for p in page})
    items = []
    for p in page:
        src = p.from_1c or {}
        items.append({
            "id": p.external_id or None,          # ключ позиции в 1С — общий с итогами дня
            "productId": p.id,                    # ключ в МАТА
            # Модель целиком: все размеры и цвета одной модели — один modelKey.
            # Клиент спрашивает про модель, а 1С ведёт каждую пару отдельной позицией.
            "modelKey": p.shop_model_key or p.id,
            "color": _color(p),
            "article": p.article,
            "name": p.name,                       # как в 1С
            "title": p.shop_title,                # как видит покупатель
            "brand": p.brand,
            "category": names.get(p.category_id, ""),
            "categoryId": p.category_id,
            "sizes": p.sizes or [],
            "colors": p.colors or [],
            "barcodes": [b.barcode for b in p.barcodes.all()],
            "active": p.is_active_1c,
            "published": p.is_published,
            # Цена клиенту — из 1С (D-124), не переопределённая в Конструкторе.
            "price1c": src.get("price"),
            "oldPrice1c": src.get("oldPrice"),
            "variants": _variants(p, held),
            "photos": _photos(p, gallery),
            "updatedAt": _iso(p.source_updated_at),
        })
    _log(request, 200, len(items))
    return Response({"items": items, "next": page[-1].id if more and page else None})
