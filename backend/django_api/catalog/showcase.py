"""Вкладки витрины (D-132): категории 1С, разложенные по «Обувь / Одежда / …».

Считаем карточки (модели), а не позиции: покупатель видит модель одной карточкой,
и «Кроссовки · 62» должно совпасть с тем, что он насчитает на экране. Пустые
группы и вкладки не отдаём — «Шиповки» появятся сами, когда в них заведут товар.
"""
from collections import defaultdict

from .models import Category, ShowcaseTab


def models_by_category(products) -> dict:
    """{id категории: множество ключей моделей} по видимым позициям."""
    seen = defaultdict(set)
    for p in products.only("id", "category_id", "model_key", "model_key_override"):
        seen[p.category_id].add(p.shop_model_key or p.id)
    return seen


def tabs(products) -> list:
    """Вкладки → группы → id категорий, только непустые, с числом карточек."""
    seen = models_by_category(products)
    out = []
    for tab in ShowcaseTab.objects.prefetch_related("groups__categories"):
        groups, tab_models = [], set()
        for group in tab.groups.all():
            ids = [c.id for c in group.categories.all()]
            keys = set().union(*(seen.get(i, set()) for i in ids)) if ids else set()
            if not keys:
                continue
            tab_models |= keys
            groups.append({"id": group.id, "name": group.name, "count": len(keys),
                           "categoryIds": [i for i in ids if seen.get(i)]})
        if groups:
            out.append({"id": tab.id, "name": tab.name, "count": len(tab_models), "groups": groups})
    return out


def visible_categories(products) -> list:
    """Категории для старого `/v1/categories`: «Все» первой, дальше непустые в порядке
    вкладок и групп; без группы — в конце по алфавиту."""
    seen = models_by_category(products)
    rows = Category.objects.select_related("showcase_group__tab")
    out, rest = [], []
    for c in rows:
        if c.id == "all":
            continue
        if not seen.get(c.id):
            continue
        g = c.showcase_group
        if g:
            out.append(((g.tab.sort, g.tab.name, g.sort, g.name, c.name), c))
        else:
            rest.append((c.name.lower(), c))
    head = [c for c in Category.objects.filter(pk="all")]
    return head + [c for _, c in sorted(out, key=lambda x: x[0])] + [c for _, c in sorted(rest, key=lambda x: x[0])]


def unassigned_with_goods(products) -> list:
    """Категории с товарами на витрине, но без группы — напоминание в админке."""
    seen = models_by_category(products)
    return list(Category.objects.filter(showcase_group__isnull=True, pk__in=[k for k, v in seen.items() if v])
                .exclude(pk="all").order_by("name"))
