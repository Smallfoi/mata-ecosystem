"""Коды групп 1С, на которые нельзя списывать бонусы (ТЗ §4, EXCLUDED_CATEGORIES_1C).

ТЗ перечисляет группы НАЗВАНИЯМИ, а правило работает по КОДАМ (Category.id — код
группы из 1С; подгруппы исключаются вместе с группой). Команда ищет категории по
названиям из ТЗ и показывает найденные коды.

По умолчанию — только показывает. `--apply` пишет найденные коды в настройку
(с историей изменений). В настройку идут только точные совпадения — по названию
группы или по пути «Родитель / Группа»; похожие показываются для ручной проверки.

Пример: manage.py loyalty_find_excluded_categories
        manage.py loyalty_find_excluded_categories --apply
        manage.py loyalty_find_excluded_categories --name "Протеин" (свои названия)
"""
import re

from django.core.management.base import BaseCommand

from catalog.models import Category, Product
from loyalty import config

# Названия из ТЗ v1 (§4).
TZ_NAMES = [
    "SIS — спортивное питание",
    "Средства для чистки",
    "RUNGEL PRO-SPORT",
    "Одежда / Спортивные костюмы",
    "Термо-комплекты",
    "Физические сертификаты",
    "Электронные сертификаты",
    "Будет архив",
    "Архивные карточки",
]


def norm(text) -> str:
    """Для сравнения: регистр, ё/е, любые тире и пробелы вокруг «/» и «-»."""
    s = str(text or "").lower().replace("ё", "е")
    s = re.sub(r"[‒–—―−]", "-", s)
    s = re.sub(r"\s*/\s*", " / ", s)
    s = re.sub(r"\s*-\s*", "-", s)
    return re.sub(r"\s+", " ", s).strip()


def _paths(categories):
    by_id = {c.id: c for c in categories}
    out = {}
    for c in categories:
        names, seen, cur = [], set(), c
        while cur is not None and cur.id not in seen:
            seen.add(cur.id)
            names.append(cur.name)
            cur = by_id.get(cur.parent_id) if cur.parent_id else None
        out[c.id] = " / ".join(reversed(names))
    return out


class Command(BaseCommand):
    help = "Найти коды групп 1С из списка ТЗ (исключения списания бонусов); --apply — записать"

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="записать найденные коды в настройку")
        parser.add_argument("--name", action="append", default=[],
                            help="искать эти названия вместо списка ТЗ (можно несколько раз)")

    def handle(self, *args, **opts):
        names = opts["name"] or TZ_NAMES
        categories = list(Category.objects.all())
        paths = _paths(categories)
        counts = {}
        for cid in Product.objects.values_list("category_id", flat=True):
            counts[cid] = counts.get(cid, 0) + 1

        found, missing = set(), []
        for name in names:
            wanted = norm(name)
            exact = [c for c in categories
                     if norm(c.name) == wanted or norm(paths[c.id]) == wanted
                     or norm(paths[c.id]).endswith(" / " + wanted)]
            if not exact and " / " in wanted:
                # «Одежда / Спортивные костюмы» — достаточно совпадения группы и родителя.
                parent, child = wanted.rsplit(" / ", 1)
                exact = [c for c in categories if norm(c.name) == child
                         and parent in norm(paths[c.id])]
            if exact:
                for c in exact:
                    found.add(c.id)
                    self.stdout.write(f"  ✔ «{name}» → код {c.id}: {paths[c.id]} "
                                      f"(товаров: {counts.get(c.id, 0)})")
                continue
            missing.append(name)
            key = wanted.split(" / ")[-1]
            words = [w for w in re.split(r"[\s\-/]+", key) if len(w) > 3]
            similar = [c for c in categories if words and any(w in norm(c.name) for w in words)]
            self.stdout.write(self.style.WARNING(f"  ✘ «{name}» — точного совпадения нет"))
            for c in similar[:10]:
                self.stdout.write(f"      похоже: код {c.id}: {paths[c.id]} "
                                  f"(товаров: {counts.get(c.id, 0)})")

        current = config.get("EXCLUDED_CATEGORIES_1C")
        self.stdout.write(f"Найдено кодов: {len(found)}; не найдено названий: {len(missing)}")
        self.stdout.write(f"Сейчас в настройке: {current or 'пусто'}")
        if not opts["apply"]:
            self.stdout.write("Ничего не записано. --apply — записать найденные коды "
                              "(к тем, что уже есть в настройке).")
            return
        value = sorted(set(current) | found)
        config.set_value("EXCLUDED_CATEGORIES_1C", value, by="loyalty_find_excluded_categories",
                         comment="Коды по названиям из ТЗ v1")
        self.stdout.write(self.style.SUCCESS(f"Записано в EXCLUDED_CATEGORIES_1C: {value}"))
