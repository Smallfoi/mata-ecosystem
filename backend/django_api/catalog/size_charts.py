"""Таблица размеров к карточке модели (D-138, владелец 25.11.2026).

Порядок поиска:
1. своя таблица модели (`models` в size_chart_data.json, ключ — начало артикула 1С;
   мерки изделий STAW с их сайта; у BMAI — таблица со страницы каждой модели на bmai.com,
   26.11.2026: у карбоновых и обычных колодок сетки разные);
2. таблица бренда по типу вещи (обувь / верх) и полу.

Пол: у ANTA его видно по артикулу (812… — мужская обувь, 822… — женская, 852…/862… —
мужская/женская одежда; сверено с anta-sport.ru), у остальных — по словам «муж»/«жен»
в названии. Пол не определили — отдаём обе таблицы, человек выберет сам.
Таблицы для брюк/шорт у брендов по обхвату груди не подходят — их не показываем.

Данные — только опубликованные брендами, без пересчётов (см. `_comment` в JSON).
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).with_name("size_chart_data.json")

FOOTWEAR = {"кроссовки", "ботинки", "кеды", "обувь"}
TOPS = {"майка", "футболка", "лонгслив", "ветровка", "жилет", "куртка", "термобелье", "поло", "толстовка"}
# Низ — своя таблица (талия и рост), таблица по обхвату груди к нему не подходит.
# Бельё здесь же: размер трусов бренды дают по обхвату талии, как у низа (26.11.2026 —
# четыре карточки белья ANTA стояли совсем без таблицы).
BOTTOMS = {"шорты", "брюки", "тайтсы", "леггинсы", "велосипедка", "трусы", "бельё", "белье"}

# Артикул ANTA: первые две цифры — группа товара.
_ANTA_GENDER = {"81": ("footwear", "men"), "82": ("footwear", "women"),
                "85": ("apparel", "men"), "86": ("apparel", "women")}


@lru_cache(maxsize=1)
def _data() -> dict:
    return json.loads(DATA.read_text(encoding="utf-8"))


def _kind(category_name: str) -> str:
    name = (category_name or "").strip().lower()
    if name in FOOTWEAR:
        return "footwear"
    if name in TOPS:
        return "top"
    if name in BOTTOMS:
        return "bottom"
    return ""


def _gender(brand: str, article: str, name: str, kind: str) -> str:
    if brand == "ANTA":
        hit = _ANTA_GENDER.get((article or "").strip()[:2])
        # 85/86 — одежда целиком: и верх, и низ.
        if hit and (hit[0] == kind or (hit[0] == "apparel" and kind in ("top", "bottom"))):
            return hit[1]
    low = (name or "").lower()
    if "жен" in low:
        return "women"
    if "муж" in low:
        return "men"
    return ""


def gender_of(*, brand: str, article: str, name: str) -> str:
    """Для кого модель — для фильтра «Пол» на витрине (аудит 25.11.2026, D-139).

    men / women / unisex / kids / "" (не определить). ANTA — по артикулу
    (81/85 — мужское, 82/86 — женское), остальные — по словам в названии из 1С.
    """
    low = (name or "").lower()
    if "детск" in low or "дет." in low:
        return "kids"
    if "унисекс" in low or "unisex" in low:
        return "unisex"
    if (brand or "").upper() == "ANTA":
        prefix = (article or "").strip()[:2]
        if prefix in ("81", "85"):
            return "men"
        if prefix in ("82", "86"):
            return "women"
    if "жен" in low:
        return "women"
    if "муж" in low:
        return "men"
    return ""


def _table(t: dict) -> dict:
    return {
        "title": t.get("title", ""),
        "columns": t["columns"],
        "rows": t["rows"],
        "match": t.get("match", 0),
        "note": t.get("note", ""),
        "source": t.get("source", ""),
    }


def chart_for(*, brand: str, article: str, name: str, category_name: str) -> dict | None:
    """Таблица для карточки: {"tables": [...]} или None, если её нет."""
    data = _data()
    art = (article or "").strip().upper()
    for prefix, entry in data.get("models", {}).items():
        if art.startswith(prefix.upper()):
            # Своя таблица модели: одна или несколько ({"tables": [...]}, напр. муж + жен,
            # когда пол модели из 1С не определить).
            tables = entry["tables"] if "tables" in entry else [entry]
            return {"tables": [_table(t) for t in tables]}

    brand = (brand or "").strip().upper()
    kind = _kind(category_name)
    group = data.get("brands", {}).get(brand, {}).get(kind)
    if not group:
        return None
    gender = _gender(brand, article, name, kind)
    if gender and gender in group:
        return {"tables": [_table(group[gender])]}
    order = [g for g in ("men", "women") if g in group]
    return {"tables": [_table(group[g]) for g in order]} if order else None
