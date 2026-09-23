# -*- coding: utf-8 -*-
"""Витринное название товара: чистое имя модели из складского названия 1С.

1С намеренно дублирует в названии всё — артикул, цвет, размер:
«ЖИЛЕТ Жен. BMAI арт. FRWK006-1 цвет ЧЕРНЫЙ р. XL». Так удобно в офлайн-магазине
и на термоэтикетке: видно, что за товар, не открывая карточку. Менять это нельзя —
это их рабочий процесс. Но покупателю такое имя показывать нельзя.

Поэтому здесь вычитание, а не угадывание: цвет, размер и артикул 1С присылает
ОТДЕЛЬНЫМИ полями, их и убираем из названия. На живых данных (787 позиций витрины)
размер из поля нашёлся в названии в 100% случаев, цвет — в 95%; остаток добираем
словарём цветов, а что не поддалось — правится руками (`display_name_override`).

Решения владельца (24.09.2026):
- бренд оставляем: по нему ищут;
- пол оставляем и разворачиваем: «Жен.» → «женский», не переставляя слова;
- регистр приводим к общему виду: капс выглядит как складской код;
- при расхождении поля и названия верим ПОЛЮ: оно из справочника.
"""
from __future__ import annotations

import re

# Корни цветов — добираем то, что в поле «Черный», а в названии «Черное серебро».
COLOR_ROOTS = (
    "ЧЕРН", "БЕЛ", "СЕР", "СИН", "ГОЛУБ", "КРАСН", "БОРДОВ", "РОЗОВ", "МЯТН", "ОЛИВК",
    "ЗЕЛЕН", "ЖЕЛТ", "ОРАНЖ", "ФИОЛЕТ", "БЕЖЕВ", "КОРИЧН", "ХАКИ", "СЕРЕБР", "ЗОЛОТ",
    "БИРЮЗ", "ЛАЙМ", "ПУДР", "ГРАФИТ", "АНТРАЦИТ", "ИНДИГО", "МОЛОЧН", "ПЕСОЧН",
    "ТЕРРАКОТ", "ЛИЛОВ", "ИЗУМРУД", "ПУРПУР", "МАЛИНОВ", "САЛАТОВ", "ВАСИЛЬК",
)
COLOR_PREFIX = ("ТЕМНО", "СВЕТЛО", "ЯРКО", "НЕОН")

LETTER_SIZES = {"XXS", "XS", "S", "M", "L", "XL", "XXL", "XXXL", "2XL", "3XL", "4XL", "5XL"}

# Пол разворачиваем на месте: «ЖИЛЕТ Жен. BMAI» → «Жилет женский BMAI»,
# «BMAI футболка мужская» остаётся как есть.
# Разворачиваем ТОЛЬКО сокращения: «Жен.» → «женский». Нормальные слова
# («футболка женская») не трогаем — иначе получится «футболка женский».
GENDER = (
    (r"\bжен\.?(?=\s|$)", "женский"),
    (r"\bмуж\.?(?=\s|$)", "мужской"),
    (r"\bдет\.?(?=\s|$)", "детский"),
)

_NUM_SIZE = re.compile(r"^\d{2}([.,]5)?$")
# Русские буквы-двойники: «р. М» — это размер M, набранный кириллицей.
_LOOKALIKE = str.maketrans({"М": "M", "С": "S", "Х": "X", "Л": "L", "м": "M", "с": "S"})
_LAT = re.compile(r"[A-Za-z]")
_CYR = re.compile(r"[А-Яа-яЁё]")


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def _drop(text: str, value: str) -> str:
    """Убрать значение как отдельный кусок: «...ЧЕРНЫЙ 42.5р.» → «...»."""
    value = (value or "").strip()
    if len(value) < 2:
        return text
    pattern = re.escape(value).replace(r"\ ", r"\s+")
    return re.sub(r"[\s,;]*(?:цвет\s*)?" + pattern + r"\s*[рp]?\.?(?=$|[\s,;])",
                  " ", text, flags=re.I)


def _is_color_word(word: str) -> bool:
    parts = [re.sub(r"[^A-ZА-Я]", "", p)
             for p in re.split(r"[/\-]", word.upper().replace("Ё", "Е")) if p]
    parts = [p for p in parts if p]
    if not parts:
        return False
    return all(any(p.startswith(root) for root in COLOR_ROOTS + COLOR_PREFIX) for p in parts)


def _strip_color_tail(text: str) -> str:
    """Убрать цвет, оставшийся хвостом («Черное серебро» при поле «Черный»).
    Только с конца и только цветными словами: «Бутылка … 750мл» не трогаем."""
    words = text.split()
    while len(words) > 1 and _is_color_word(words[-1]):
        words.pop()
    return " ".join(words)


def _strip_sizes(text: str) -> str:
    """Убрать размер, если 1С не прислала его полем: хвост «42.5р.», «XL» или «(3XL)»."""
    text = re.sub(r"\s*\((?:" + "|".join(sorted(LETTER_SIZES, key=len, reverse=True)) +
                  r"|\d{2}(?:[.,]5)?)\)\s*$", " ", text, flags=re.I).strip()
    words = text.split()
    while len(words) > 1:
        last = words[-1].upper().rstrip(".").rstrip("РP").translate(_LOOKALIKE)
        if _NUM_SIZE.match(last) or last in LETTER_SIZES:
            words.pop()
            continue
        break
    return " ".join(words)


def _case(text: str) -> str:
    """Общий стиль: латиницу и бренды не трогаем, русский капс гасим.

    «БЛУЗКА Муж. BMAI» → «Блузка мужской BMAI»; «BMAI EXPEDITION CORDURA» остаётся
    как есть — это название модели латиницей. Слова с цифрами («45Г») просто
    опускаем в нижний регистр: это единицы измерения, заглавная им не нужна.
    """
    out = []
    for word in text.split():
        if _LAT.search(word) or not _CYR.search(word):
            out.append(word)                       # бренд, модель, размерность
        elif word.isupper():
            lower = word.lower()
            if any(ch.isdigit() for ch in word):
                out.append(lower)                  # «(45Г)» → «(45г)»
            else:
                out.append(_upper_first(lower))    # «ЖИЛЕТ» → «Жилет»
        else:
            out.append(word)
    return _upper_first(" ".join(out))


def _upper_first(text: str) -> str:
    """Заглавной — первую БУКВУ, а не первый символ: «(очищение)» → «(Очищение)».
    Если первая буква уже заглавная, ничего не трогаем."""
    m = re.search(r"[A-Za-zА-Яа-яЁё]", text)
    if not m or not m.group(0).islower():
        return text
    i = m.start()
    return text[:i] + text[i].upper() + text[i + 1:]


# Род слова-предмета: «Блузка мужская», но «Жилет мужской» и «Бельё мужское».
# Без этого получается «Блузка мужской» — сразу видно машину.
_FEMININE = ("блузка", "футболка", "куртка", "майка", "шапка", "толстовка", "ветровка",
             "рубашка", "жилетка", "кофта", "юбка", "повязка", "бандана", "сумка",
             "панама", "кепка", "водолазка", "олимпийка", "ветровка")
_NEUTER = ("бельё", "белье", "платье", "поло", "худи")
_PLURAL = ("шорты", "брюки", "носки", "тайтсы", "перчатки", "леггинсы", "кроссовки",
           "штаны", "трусы", "гетры", "бриджи", "варежки", "тапочки")


def _agree(word: str, text: str) -> str:
    """Согласовать «мужской/женский/детский» с предметом.

    Предмет ищем среди всех слов, а не только первого: в «Нижнее бельё ANTA»
    предмет — «бельё», и правильно «мужское», а не «мужской».
    """
    stem = word[:-2]                                   # мужск-ой → мужск
    words = [w.strip(",.;()").lower() for w in (text or "").split()]
    for head in words:
        if head in _PLURAL:
            return stem + "ие"
        if head in _NEUTER:
            return stem + "ое"
        if head in _FEMININE:
            return stem + "ая"
    return word


def _gender(text: str) -> str:
    """«Жен.» → «женский», согласуя с предметом: «Блузка женская», «Жилет женский»."""
    for pattern, full in GENDER:
        if re.search(pattern, text, flags=re.I):
            text = re.sub(pattern, _agree(full, text), text, flags=re.I)
    return _norm(text)


def shop_name(name: str, sizes=None, colors=None, article: str = "") -> str:
    """Витринное имя: складское название без артикула, цвета и размера."""
    text = _norm(name)
    if not text:
        return ""

    # Складской формат одежды: «ЖИЛЕТ Жен. BMAI арт. FRWK006-1 цвет ЧЕРНЫЙ р. XL».
    # Всё от «арт.» — это артикул, цвет и размер: режем целиком, одним правилом.
    text = re.sub(r"\s*\bарт\.?\s*[A-Za-z0-9].*$", " ", text, flags=re.I | re.S)
    # Тот же формат без артикула: «… цвет ЧЕРНЫЙ р. XL».
    text = re.sub(r"\s*\bцвет\b\s+.*$", " ", text, flags=re.I | re.S)
    if article:
        text = _drop(text, article)

    for value in list(colors or []) + list(sizes or []):
        text = _drop(text, str(value))

    # Чистим по кругу: размер мог прятаться за цветом и наоборот.
    for _ in range(3):
        before = text
        text = _norm(text)
        text = re.sub(r"[\s,;]*\bр\.?\s*$", " ", text, flags=re.I)
        text = _strip_sizes(text)
        text = _strip_color_tail(text)
        if _norm(text) == _norm(before):
            break

    text = re.sub(r"\s*[,;]+\s*", ", ", _norm(text))       # «пластиковая , 800 мл»
    text = re.sub(r"\s*[-–—]\s*(?=[(,]|$)", " ", text)     # «(Очищение) - (45г)»
    text = re.sub(r"\(\s*\)", " ", text)                   # пустые скобки
    text = _norm(text).strip(" ,;-.")
    text = _gender(text)
    text = _case(text)
    return _norm(text)


# ── Объединение карточек в модель ──────────────────────────────────────────
# В 1С каждый размер и цвет — отдельная карточка: так ведётся склад и печатаются
# этикетки. Покупателю нужна ОДНА карточка модели, внутри которой он выбирает
# цвет и размер.
#
# Ключ объединения — АРТИКУЛ ИЗ ПОЛЯ, суффикс цвета отрезаем: «FRWK006-1» и
# «FRWK006-2» — одна модель, разные цвета. Из названия артикул НЕ достаём
# (D-95): там встречаются числа, которые артикулом не являются — «Шорты мужские
# BMAI темно-синий 3.5», где 3.5 это длина шорт.
#
# Пока артикул не заполнен, ключ — витринное название. Для обуви это работает
# точно («BMAI EXPEDITION CORDURA»), у одежды до заполнения артикулов модели с
# одинаковым названием окажутся в одной карточке — разъедутся сами, как только
# артикул появится.

_COLOR_SUFFIX = re.compile(r"[-_]\d{1,2}$")


def model_base(article: str) -> str:
    """База модели: отрезаем суффикс цвета. «FRWK006-1» → «FRWK006»."""
    article = (article or "").strip()
    return _COLOR_SUFFIX.sub("", article) if article else ""


def model_key(name: str, sizes=None, colors=None, article: str = "",
              display_name: str = "") -> str:
    """Ключ карточки на витрине: по нему складские позиции собираются в модель."""
    base = model_base(article)
    if base:
        return base.upper()
    title = display_name or shop_name(name, sizes, colors, article)
    return re.sub(r"\s+", " ", title).strip().upper()
