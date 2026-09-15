"""Вес и габариты посылки для расчёта доставки (D-79).

СДЭК и Почта России считают цену по весу в граммах и размерам коробки в сантиметрах.
Откуда берём, по убыванию точности:

1. поля товара — из 1С (склад знает точный вес) или введённые вручную в админке;
2. типовые для категории, а если там пусто — для родительской категории;
3. общий запас, чтобы расчёт не падал на товаре, о котором не знаем ничего.

`source` в ответе говорит, какой уровень добил недостающее: так видно, сколько товаров
считается «на глаз», а не по складу.
"""
FIELDS = ("weight_g", "length_cm", "width_cm", "height_cm")

# Коробка с парой кроссовок: чуть больше средней, чтобы на незнакомом товаре не занизить цену.
FALLBACK = {"weight_g": 1000, "length_cm": 35, "width_cm": 25, "height_cm": 15}

_MAX_DEPTH = 3  # категория → родитель → родитель родителя; дальше не ходим (и от петель)


def _category_chain(category_id):
    from .models import Category

    chain, seen, cid = [], set(), category_id
    while cid and cid not in seen and len(chain) < _MAX_DEPTH:
        seen.add(cid)
        category = Category.objects.filter(id=cid).first()
        if category is None:
            break
        chain.append(category)
        cid = category.parent_id
    return chain


def parcel_for(product) -> dict:
    """Вес (г) и габариты (см) одной единицы товара + откуда они взяты."""
    values = {f: getattr(product, f) for f in FIELDS}
    if all(values.values()):
        return {**values, "source": "product"}
    for category in _category_chain(product.category_id):
        for f in FIELDS:
            values[f] = values[f] or getattr(category, f"default_{f}")
        if all(values.values()):
            return {**values, "source": "category"}
    for f in FIELDS:
        values[f] = values[f] or FALLBACK[f]
    return {**values, "source": "fallback"}
