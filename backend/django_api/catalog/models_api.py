# -*- coding: utf-8 -*-
"""Карточки моделей для витрины: один товар — много вариантов.

В 1С каждый размер и цвет — отдельная позиция: так ведётся склад и печатаются
этикетки. Покупателю это показывать нельзя — он видит одну карточку модели и
выбирает внутри цвет и размер, а чего нет на складе, то недоступно (D-94).

Склад и админка не меняются: карточки там остаются раздельными. Здесь только
сборка для витрины.
"""
from collections import OrderedDict

from rest_framework.decorators import api_view, throttle_classes
from rest_framework.response import Response

from common.throttling import PUBLIC_READ

from . import photos as photolib
from .models import Product

# Порядок размеров: по алфавиту вышло бы «L, M, S, XL».
_SIZE_ORDER = {s: i for i, s in enumerate(
    ["XXS", "XS", "S", "M", "L", "XL", "XXL", "XXXL", "2XL", "3XL", "4XL", "5XL"])}


def _size_sort(size: str):
    text = str(size).strip()
    if text.upper() in _SIZE_ORDER:
        return (0, _SIZE_ORDER[text.upper()], text)
    try:
        return (1, float(text.replace(",", ".")), text)
    except ValueError:
        return (2, 0, text)


def _in_stock(product: Product, size: str = "") -> bool:
    """Есть ли вариант в наличии. Пусто в остатках = 1С не присылала разбивку."""
    if not product.in_stock:
        return False
    by_size = product.stock_by_size or {}
    if size and by_size:
        return int(by_size.get(str(size), 0) or 0) > 0
    if product.stock_count is None:
        return True
    return product.stock_count > 0


def _variant_sizes(product: Product):
    """Размеры позиции — ТОЛЬКО из поля 1С.

    Решение владельца (24.09.2026): размер и цвет берём строго из строк, из
    названия не вытягиваем. Названия сейчас дублируют всё подряд, а строки в
    1С заполняются вручную — и это единственный достоверный источник. Пока
    строка пуста, на витрине у товара просто нет выбора размера; заполнили —
    выбор появился сам, без правок в коде.
    """
    sizes = [str(s).strip() for s in (product.sizes or []) if str(s).strip()]
    return sizes or [""]


def _variant_colors(product: Product):
    """Цвета позиции — ТОЛЬКО из поля 1С (см. `_variant_sizes`)."""
    colors = [str(c).strip() for c in (product.colors or []) if str(c).strip()]
    return colors or [""]


def positions_of_model(key: str, qs=None):
    """Все складские позиции одной модели по её ключу.

    Ключ может быть переопределён руками, поэтому сначала ищем по переопределению,
    потом по вычисленному ключу, и только в крайнем случае считаем, что нам дали
    id самой позиции (товар заведён руками, модели у него нет).
    """
    base = Product.objects.all() if qs is None else qs
    items = list(base.filter(model_key_override=key))
    if not items:
        items = list(base.filter(model_key_override="", model_key=key))
    if not items:
        items = list(base.filter(pk=key))
    return items


def siblings_of(pid: str, qs=None):
    """Позиции той же модели, что и `pid` — где `pid` либо id позиции, либо ключ.

    Нужно там, где покупатель имеет дело с моделью, а купил конкретный размер:
    например, отзыв он пишет на модель, а в заказе лежит одна позиция.
    """
    base = Product.objects.all() if qs is None else qs
    product = base.filter(pk=pid).first()
    key = (product.shop_model_key if product else "") or pid
    items = positions_of_model(key, qs=base)
    if not items and product:
        items = [product]
    return items


def _model_rating(items):
    """Рейтинг модели. После пересчёта отзывов все позиции модели держат одно и
    то же значение, поэтому берём позицию с максимумом отзывов — складывать
    нельзя, иначе один отзыв превратится в три."""
    best = max(items, key=lambda p: (p.review_count or 0))
    return round(best.rating or 0, 1), (best.review_count or 0)


def build_card(items, photos: dict | None = None) -> dict:
    """Собрать карточку модели из складских позиций одной модели.

    `photos` — снимки этой модели по цветам (`catalog.photos.by_model`). Их отдают
    заранее одним запросом: в списке из двух сотен карточек ходить в базу за каждой
    значило бы две сотни запросов.
    """
    items = list(items)
    first = items[0]
    colors = OrderedDict()
    prices, in_stock_any = [], False

    for product in items:
        for color in _variant_colors(product):
            entry = colors.setdefault(color, {"name": color, "imageUrl": "",
                                              "thumbUrl": "", "photos": [],
                                              "sizes": [], "inStock": False})
            if not entry["photos"]:
                entry["photos"] = [p.to_json() for p in photolib.pick(photos, color)]
            if not entry["imageUrl"]:
                # Обложка цвета: первый снимок галереи, иначе старое фото позиции.
                entry["imageUrl"] = (entry["photos"][0]["url"] if entry["photos"]
                                     else product.network_image_url())
                # Миниатюра — для ленты каталога и кружков выбора цвета: две сотни
                # полноразмерных снимков в списке качать незачем.
                entry["thumbUrl"] = (entry["photos"][0]["thumb"] if entry["photos"]
                                     else entry["imageUrl"])
            for size in _variant_sizes(product):
                available = _in_stock(product, size)
                entry["sizes"].append({
                    "size": size,
                    "productId": product.id,
                    "price": product.price,
                    "oldPrice": product.old_price,
                    "inStock": available,
                })
                entry["inStock"] = entry["inStock"] or available
                in_stock_any = in_stock_any or available
                if available:
                    prices.append(product.price)

    for entry in colors.values():
        entry["sizes"].sort(key=lambda v: _size_sort(v["size"]))

    all_prices = prices or [p.price for p in items]
    sizes_all = sorted({v["size"] for c in colors.values() for v in c["sizes"] if v["size"]},
                       key=_size_sort)
    image = next((c["imageUrl"] for c in colors.values() if c["imageUrl"]), "")
    thumb = next((c["thumbUrl"] for c in colors.values() if c["thumbUrl"]), image)
    rating, review_count = _model_rating(items)

    return {
        "key": first.shop_model_key or first.id,
        "name": first.shop_title,
        "brand": first.brand,
        # Артикул модели: у одежды он и есть ключ — показываем подписью, иначе
        # три разные модели шорт выглядят одинаково.
        "article": first.shop_model_key if first.article or "арт" in first.name.lower() else "",
        "categoryId": first.category_id,
        "price": min(all_prices) if all_prices else 0,
        "oldPrice": first.old_price,
        "imageUrl": image,
        "thumbUrl": thumb,
        "description": first.description,
        "rating": rating,
        "reviewCount": review_count,
        "isNew": any(p.is_new for p in items),
        "isFeatured": any(p.is_featured for p in items),
        "inStock": in_stock_any,
        "variantCount": len(items),
        "sizes": sizes_all,
        "colors": list(colors.values()),
    }


def build_cards(queryset):
    """Сгруппировать позиции в карточки, сохранив порядок витрины."""
    groups = OrderedDict()
    for product in queryset:
        groups.setdefault(product.shop_model_key or product.id, []).append(product)
    photos = photolib.by_model(groups.keys())
    return [build_card(items, photos.get(key))
            for key, items in groups.items()]


@api_view(["GET"])
@throttle_classes(PUBLIC_READ)
def models_list(request):
    """Витрина карточками моделей: `/v1/models`.

    `q` — поиск. Он здесь, а не отдельным адресом, потому что результат поиска
    обязан выглядеть как витрина: одна карточка модели, а не шесть одинаковых
    позиций разных размеров.
    """
    from django.db.models import Q

    from .views import _platform_order, _visible_products

    qs = _visible_products(request)
    category = request.query_params.get("category")
    if category and category != "all":
        qs = qs.filter(category_id=category)
    query = (request.query_params.get("q") or "").strip()
    if query:
        qs = qs.filter(
            Q(name__icontains=query)
            | Q(display_name__icontains=query)
            | Q(display_name_override__icontains=query)
            | Q(description__icontains=query)
            | Q(brand__icontains=query)
            | Q(article__icontains=query)
        )
    if request.query_params.get("new") in ("1", "true", "yes"):
        qs = qs.filter(is_new=True)
    if request.query_params.get("featured") in ("1", "true", "yes"):
        qs = qs.filter(is_featured=True)
    return Response(build_cards(qs.order_by(*_platform_order(request))))


@api_view(["GET"])
@throttle_classes(PUBLIC_READ)
def model_card(request, key):
    """Одна карточка модели со всеми цветами и размерами: `/v1/models/<key>`."""
    from .views import _visible_products

    qs = _visible_products(request)
    items = positions_of_model(key, qs=qs)
    if not items:
        return Response({"error": "not_found"}, status=404)
    model_key = items[0].shop_model_key or items[0].id
    return Response(build_card(items, photolib.by_model([model_key]).get(model_key)))
