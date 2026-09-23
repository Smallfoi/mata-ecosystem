# -*- coding: utf-8 -*-
"""Проверка данных каталога: что похоже на ошибку и требует глаз человека.

Данные ведёт 1С, заполняют их руками, и опечатки неизбежны: у одного артикула
часть позиций названа женскими, а одна мужской; в строку размера попала длина
шорт; цвет в строке не тот, что в названии. Сервер такие вещи молча принимает —
и ошибка живёт на витрине, пока её случайно не заметят.

Здесь набор проверок. Каждая возвращает находки: что не так, чем грозит и какие
карточки смотреть. Ничего не исправляется автоматически: данные ведёт 1С, решение
за человеком.
"""
from __future__ import annotations

import re
from collections import defaultdict

from .models import Product

# Размеры, которые считаем нормальными: буквенные и числовые (обувь, одежда).
LETTER_SIZES = {"XXS", "XS", "S", "M", "L", "XL", "XXL", "XXXL", "2XL", "3XL", "4XL",
                "5XL", "ONE SIZE", "ONESIZE", "Б/Р", "БЕЗ РАЗМЕРА"}
_NUM_SIZE = re.compile(r"^\d{2}([.,]5)?$")            # 36, 42.5
_RANGE_SIZE = re.compile(r"^\d{2}\s*-\s*\d{2}$")      # 39-41 (носки)
# Объём и вес: у бутылок и питания «размер» — это 750мл или 45г. Не ошибка.
_UNIT_SIZE = re.compile(r"^\d+[.,]?\d*\s*(мл|л|г|кг|шт|см|мм)\.?$", re.I)
_GOOD_ARTICLE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-/._]*$")
_GENDER = ((r"\bжен", "женский"), (r"\bмуж", "мужской"), (r"\bдет", "детский"))

_COLOR_ROOTS = ("ЧЕРН", "БЕЛ", "СЕР", "СИН", "ГОЛУБ", "КРАСН", "БОРДОВ", "РОЗОВ", "МЯТН",
                "ОЛИВК", "ЗЕЛЕН", "ЖЕЛТ", "ОРАНЖ", "ФИОЛЕТ", "БЕЖЕВ", "КОРИЧН", "ХАКИ",
                "СЕРЕБР", "ЗОЛОТ", "БИРЮЗ", "ЛАЙМ", "ГРАФИТ", "ИНДИГО", "МОЛОЧН")


def _gender_of(text: str) -> str:
    low = (text or "").lower()
    for pattern, label in _GENDER:
        if re.search(pattern, low):
            return label
    return ""


_ARTICLE_IN_NAME = re.compile(r"\bарт\.?\s*([A-Za-z][A-Za-z0-9\-/]*)", re.I)


def _model_of(product: Product) -> str:
    """Модель позиции: артикул без суффикса цвета.

    Здесь — в отличие от витрины (D-95) — можно заглянуть и в название: задача
    проверки как раз в том, чтобы сверять одно с другим и находить расхождения.
    На витрину эти значения не попадают, они только подсказывают, куда смотреть.
    Берём лишь явную пометку «арт.», чтобы не принять за артикул длину шорт.
    """
    article = (product.article or "").strip()
    if not article:
        match = _ARTICLE_IN_NAME.search(product.name or "")
        article = match.group(1) if match else ""
    return re.sub(r"[-_]\d{1,2}$", "", article).upper() if article else ""


def _color_root(value: str) -> str:
    bare = re.sub(r"[^А-ЯA-Z]", "", (value or "").upper().replace("Ё", "Е"))
    for root in _COLOR_ROOTS:
        if bare.startswith(root):
            return root
    return ""


def check_gender_mismatch(products):
    """У одного артикула часть позиций названа женскими, часть мужскими.

    Сильный признак опечатки: артикул — это модель, пол у неё один.
    """
    by_model = defaultdict(list)
    for product in products:
        model = _model_of(product)
        if model and _gender_of(product.name):
            by_model[model].append(product)

    found = []
    for model, items in by_model.items():
        counts = defaultdict(list)
        for product in items:
            counts[_gender_of(product.name)].append(product)
        if len(counts) > 1:
            rare = min(counts.values(), key=len)
            found.append({
                "title": f"Артикул {model}: в названиях разный пол",
                "detail": " · ".join(f"{g} — {len(v)}" for g, v in counts.items()),
                "hint": "Скорее всего, опечатка в названии у меньшинства позиций.",
                "products": rare,
            })
    return found


def check_model_name_differs(products):
    """У одного артикула разные витринные названия — опечатка в одном из них."""
    titles = defaultdict(set)
    samples = defaultdict(list)
    for product in products:
        model = _model_of(product)
        # Пока витринное название не посчитано, сравнивать нечего: складские имена
        # различаются цветом и размером всегда, и это не ошибка.
        if not model or not (product.display_name or "").strip():
            continue
        titles[model].add(product.shop_title.strip().lower())
        samples[model].append(product)

    found = []
    for model, values in titles.items():
        if len(values) > 1:
            found.append({
                "title": f"Артикул {model}: разные названия модели",
                "detail": " | ".join(sorted(values)[:4]),
                "hint": "У одной модели название должно быть одним — сверьте написание.",
                "products": samples[model][:12],
            })
    return found


def check_strange_size(products):
    """Размер не похож на размер: «3.5» у шорт — это длина, а не размер."""
    found = []
    for product in products:
        for size in (product.sizes or []):
            value = str(size).strip()
            if not value:
                continue
            if (value.upper() in LETTER_SIZES or _NUM_SIZE.match(value)
                    or _RANGE_SIZE.match(value) or _UNIT_SIZE.match(value)):
                continue
            found.append({
                "title": f"Странный размер: «{value}»",
                "detail": product.name,
                "hint": "Похоже, в строку размера попало другое — длина, объём или номер.",
                "products": [product],
            })
    return found


def check_color_mismatch(products):
    """Цвет в строке не совпадает с цветом в названии — одно из двух неверно."""
    found = []
    for product in products:
        colors = [str(c).strip() for c in (product.colors or []) if str(c).strip()]
        if not colors:
            continue
        name_upper = product.name.upper().replace("Ё", "Е")
        for color in colors:
            root = _color_root(color)
            # В названии цвет часто сокращают: «фиол/оранж» вместо
            # «Фиолетовый/Оранжевый». Сверяем по началу слова, иначе получаем шум.
            if not root or root[:4] in name_upper:
                continue
            if any(other[:4] in name_upper for other in _COLOR_ROOTS):
                found.append({
                    "title": f"Цвет в строке «{color}», а в названии другой",
                    "detail": product.name,
                    "hint": "Проверьте, какой цвет верный: на витрину идёт строка.",
                    "products": [product],
                })
    return found


def check_bad_article(products):
    """Артикул странного вида: кириллица, пробел, лишние знаки."""
    found = []
    for product in products:
        article = (product.article or "").strip()
        if article and not _GOOD_ARTICLE.match(article):
            found.append({
                "title": f"Артикул странного вида: «{article}»",
                "detail": product.name,
                "hint": "Кириллица, пробел или лишний знак в артикуле — обычно опечатка.",
                "products": [product],
            })
    return found


def check_duplicate_variant(products):
    """Один и тот же цвет и размер у модели встречается дважды — дубль позиции."""
    seen = defaultdict(list)
    for product in products:
        model = _model_of(product)
        if not model:
            continue
        colors = [str(c).strip() for c in (product.colors or [])] or [""]
        sizes = [str(s).strip() for s in (product.sizes or [])] or [""]
        for color in colors:
            for size in sizes:
                # Ни цвета, ни размера — это незаполненные строки, а не повтор.
                # Про пустоту рассказывает страница «Заполненность 1С».
                if not color and not size:
                    continue
                seen[(model, color, size)].append(product)

    found = []
    for (model, color, size), items in seen.items():
        if len(items) > 1:
            found.append({
                "title": f"Повтор варианта: {model}, цвет «{color}», размер «{size}»",
                "detail": f"позиций: {len(items)}",
                "hint": "Две карточки на один вариант — покупатель увидит дубль.",
                "products": items[:10],
            })
    return found


def check_price_differs(products):
    """Внутри одной модели цена отличается в разы — похоже на лишний ноль."""
    by_model = defaultdict(list)
    for product in products:
        model = _model_of(product)
        if model and product.price:
            by_model[model].append(product)

    found = []
    for model, items in by_model.items():
        prices = [p.price for p in items]
        low, high = min(prices), max(prices)
        if low and high / low >= 3:
            found.append({
                "title": f"Артикул {model}: цены расходятся в {round(high / low)} раза",
                "detail": f"от {low:.0f} ₽ до {high:.0f} ₽",
                "hint": "Внутри модели цены обычно близки — проверьте, нет ли лишнего нуля.",
                "products": sorted(items, key=lambda p: p.price)[:6],
            })
    return found


CHECKS = (
    ("Разный пол у одного артикула", check_gender_mismatch),
    ("Разные названия у одного артикула", check_model_name_differs),
    ("Странный размер", check_strange_size),
    ("Цвет в строке и в названии расходятся", check_color_mismatch),
    ("Артикул странного вида", check_bad_article),
    ("Повтор варианта", check_duplicate_variant),
    ("Цены внутри модели расходятся", check_price_differs),
)


def run_all(queryset=None, limit_per_check: int = 50):
    """Все проверки разом. Возвращает разделы с находками, самые важные — первыми."""
    products = list(queryset if queryset is not None else Product.objects.all())
    sections = []
    for title, check in CHECKS:
        found = check(products)
        sections.append({
            "title": title,
            "total": len(found),
            "items": found[:limit_per_check],
        })
    return sections
