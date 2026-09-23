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
    """Размеры позиции: из поля 1С, иначе один безразмерный вариант."""
    sizes = [str(s).strip() for s in (product.sizes or []) if str(s).strip()]
    return sizes or [""]


def build_card(items) -> dict:
    """Собрать карточку модели из складских позиций одной модели."""
    items = list(items)
    first = items[0]
    colors = OrderedDict()
    prices, in_stock_any = [], False

    for product in items:
        names = [str(c).strip() for c in (product.colors or []) if str(c).strip()]
        for color in names or [""]:
            entry = colors.setdefault(color, {"name": color, "imageUrl": "",
                                              "sizes": [], "inStock": False})
            if not entry["imageUrl"]:
                entry["imageUrl"] = product.network_image_url()
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
        "description": first.description,
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
    return [build_card(items) for items in groups.values()]


@api_view(["GET"])
@throttle_classes(PUBLIC_READ)
def models_list(request):
    """Витрина карточками моделей: `/v1/models`."""
    from .views import _platform_order, _visible_products

    qs = _visible_products(request)
    category = request.query_params.get("category")
    if category and category != "all":
        qs = qs.filter(category_id=category)
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
    items = list(qs.filter(model_key_override=key)) or list(
        qs.filter(model_key_override="", model_key=key))
    if not items:
        items = list(qs.filter(pk=key))
    if not items:
        return Response({"error": "not_found"}, status=404)
    return Response(build_card(items))
