"""Универсальные промты «стиль МАТА» для фотопайплайна (v3).

УНИВЕРСАЛЬНЫЕ: конкретный принт/цвет/текст НЕ зашиваем — модель берёт их из
приложенного референса. Стиль (свет/фон) фиксированный — это и есть единый вид
каталога.

Почему по-английски и по пунктам: на живых прогонах 27.09 обе модели (gpt-image-1 и
gpt-image-2.5-flare) при русском промте «сохрани надписи как есть» выдумывали слова
(«Staw Running Member» → «Stow Runbing Member» / «Slaw Running Machine») и меняли ткань.
Жёсткие пункты на английском модели держат надёжнее, а буквальный текст принта (если
известен) передаётся отдельно — with_text().

Что нового в v3 (16.11.2026):
- основной текст говорит «product», а не «garment»: в каталоге 77 кроссовок, 18 ботинок,
  шиповки, бутылки, очки, рюкзаки — «невидимый манекен» для них бессмыслица;
- постановка кадра вынесена в STAGING и выбирается по виду товара (одежда / обувь /
  аксессуар), вид — из категории 1С;
- какую вещь брать с многопредметного кадра, решает карточка (with_item).

Основной текст можно править на странице «Промты» без выкладки; блоки WHICH ITEM и
STAGING код добавляет сам — на странице они показаны отдельно, для сведения.
"""

# Правила точности — общие для обоих треков и для любого вида товара.
_FIDELITY = (
    "PRODUCT FIDELITY (highest priority, never violate):\n"
    "- Use exactly ONE item from the reference: the one named in WHICH ITEM below. "
    "If WHICH ITEM is not given, take the most prominent item. "
    "Ignore everything else in the reference.\n"
    "- Keep the item identical to the reference: same colour and shade, same "
    "material and surface texture (knit stays knit, mesh stays mesh, leather stays "
    "leather, matte stays matte), same shape, cut, proportions, seams, panels, soles "
    "and trims.\n"
    "- Text, logos and graphics: reproduce them exactly as in the reference - the same "
    "letters and spelling, font style, size and position. Never invent, rephrase, "
    "translate or 'correct' any text. Do not add text or logos that are not in the "
    "reference. If the item has no print, keep it plain.\n"
    "- Keep the SAME SIDE of the item as in the reference: if the reference shows the "
    "back, show the back; if it shows the front, show the front. Never move prints, text "
    "or graphics to another side, and do not invent what is on the side that is not "
    "visible.\n"
)

# Трек 1 — каталог: товар без человека, точность важна.
CATALOG = (
    "Create a professional e-commerce catalog photo of the product from the reference "
    "image.\n"
    + _FIDELITY
    + "- Remove any person, body part, mannequin, hanger and the original background.\n"
    "STYLE:\n"
    "- Pure white seamless background, soft natural contact shadow under the product.\n"
    "- Large softbox key light plus fill, high-key, even exposure, crisp detail edge to "
    "edge, true-to-life colour, commercial catalog quality.\n"
    "- How the product is placed in the frame is given in STAGING below."
)

# Трек 2 — маркетинг: товар на модели (реклама, не карточка).
MODEL = (
    "Create a professional studio advertising photo of an athletic model with the "
    "product from the reference image.\n"
    + _FIDELITY
    + "STYLE:\n"
    "- Model: athletic build, neutral expression, natural relaxed pose, no extra "
    "accessories that are not the product.\n"
    "- Light-grey seamless studio background with a subtle gradient, large softbox key "
    "light and soft rim light, natural skin, sharp focus on the product, commercial "
    "quality.\n"
    "- How the model wears or uses the product, and the framing, is given in STAGING "
    "below."
)


# Постановка кадра по виду товара. Вид — из категории 1С (item_kind).
GARMENT, FOOTWEAR, ACCESSORY = "garment", "footwear", "accessory"

STAGING = {
    ("catalog", GARMENT): (
        "STAGING (clothing): ghost-mannequin (invisible mannequin), viewed straight on "
        "from the same side as in the reference; the garment keeps a natural worn shape, "
        "neatly smoothed, centred with even margins. Socks and briefs: laid flat, neatly "
        "shaped, no mannequin."
    ),
    # Разворот кроссовка БЕРЁТСЯ С ИСХОДНИКА (решение владельца 24.11.2026).
    # Прежняя редакция требовала «строго в профиль, носком влево» и спорила с
    # правилом FIDELITY «покажи ту же сторону, что на референсе»: снимок задника
    # модель разворачивала вбок, а замечание проверяющего не помогало — пожелание
    # против правила проигрывает. Единый вид каталога держат свет, фон и
    # кадрирование, а не одинаковый поворот: покупателю нужны и задник, и подошва.
    ("catalog", FOOTWEAR): (
        "STAGING (footwear): no foot, leg or mannequin. A single shoe, laces neatly "
        "tied, centred with even margins. KEEP THE VIEWPOINT OF THE REFERENCE: a side "
        "profile stays a side profile with the toe pointing the same way, a heel/back "
        "view stays heel/back, a three-quarter stays three-quarter, a top view stays "
        "top view, a sole shot stays a sole shot. Never rotate the shoe to another "
        "angle and never invent a side the reference does not show. For a side "
        "profile, keep the full sole edge visible."
    ),
    ("catalog", ACCESSORY): (
        "STAGING (accessory): the product alone in its natural resting position - a "
        "bottle or flask standing upright, a backpack or bag standing with its shape "
        "filled out, a cap at a three-quarter front view, glasses unfolded facing the "
        "camera, gloves, buffs, insoles and gel sachets laid flat. Centred with even "
        "margins."
    ),
    ("model", GARMENT): (
        "STAGING (clothing): the model wears the garment, standing straight, arms relaxed "
        "along the body, turned to the camera with the same side of the garment as in the "
        "reference (back to the camera if the reference shows the back). Framing so the "
        "whole garment is visible: from the thighs up for tops, from the waist down for "
        "shorts, tights and trousers."
    ),
    ("model", FOOTWEAR): (
        "STAGING (footwear): the model wears the shoes; framing from the knees down, "
        "both shoes sharp and fully visible, standing or in a calm running stance on the "
        "studio floor."
    ),
    ("model", ACCESSORY): (
        "STAGING (accessory): the model wears or uses the accessory naturally - a cap or "
        "beanie on the head, glasses on the face, a backpack on the shoulders, a bottle "
        "or gel in the hand, gloves on the hands, a buff on the neck. Framing so the "
        "accessory is prominent and sharp."
    ),
}


def with_details(prompt: str, count: int = 0) -> str:
    """Сказать модели, что после основного снимка идут крупные планы принта.

    Без пояснения модель может принять крупный план за отдельную вещь или показать его
    в кадре. Нет крупных планов — промт без изменений.
    """
    if not count:
        return prompt
    return (
        prompt
        + "\nREFERENCE IMAGES: the FIRST image shows the whole garment and which side to show. "
        "The next %d image(s) are close-ups of prints, labels or text on this same garment. "
        "Use the close-ups only to reproduce those details exactly (letters, shapes, colours); "
        "do not show the close-ups themselves and do not add their prints anywhere they are "
        "not on the garment." % count
    )


def with_text(prompt: str, text: str = "") -> str:
    """Добавить к промту буквальный текст принта, если он известен.

    Модели рисуют надпись точнее, когда строку им дают словами, а не просят срисовать
    с фото. Пустой текст — промт без изменений.
    """
    text = (text or "").strip()
    if not text:
        return prompt
    return (
        prompt
        + "\nPRINTED TEXT: the print on the garment reads exactly \"%s\". Render exactly "
        "these characters, letter for letter, in the same place and style as in the "
        "reference, and no other text." % text
    )


def with_note(prompt: str, note: str = "") -> str:
    """Добавить замечание проверяющего к промту повторной попытки («Переделать»).

    Замечание пишет человек на экране проверки («принт перенесён на перед», «не та
    ткань»); модель получает его как обязательную правку. Пустое — промт без изменений.
    """
    note = (note or "").strip()
    if not note:
        return prompt
    return (
        prompt
        + "\nREVIEWER FEEDBACK (overrides STAGING and STYLE where they conflict; never "
        "overrides PRODUCT FIDELITY). A human looked at the previous attempt and "
        "rejected it. The note often describes what went wrong rather than what to "
        "do - work out the required change and apply it (the note may be in "
        "Russian): %s" % note
    )

# Тип вещи. Нужен там, где на кадре несколько вещей сразу: маркетинговый снимок
# показывает лонгслив, шорты, кепку, носки и кроссовки, а карточка — про одну из них.
#
# Истина — КАТЕГОРИЯ: её ведёт 1С, и это настоящий справочник магазина. Разбор
# названия оставлен запасным путём и помогает всё реже: на ноябрь 2026 у 216 позиций
# из 667 в названии только бренд и модель («BMAI PURE 2.0 CORDURA», «ANTA WALK 2.0»,
# «Rockbros SHADOW») — там тип из названия не достать в принципе, а категория есть.
CATEGORY_TYPES = {
    # одежда
    "лонгслив": "long-sleeve athletic top",
    "футболка": "short-sleeve t-shirt",
    "футболки": "short-sleeve t-shirt",
    "топ": "sports bra top",
    "майка": "sleeveless tank top",
    "худи": "hoodie",
    "шорты": "shorts",
    "велосипедка": "cycling shorts",
    "тайтсы": "running tights",
    "леггинсы": "leggings",
    "брюки": "trousers",
    "ветровка": "lightweight windbreaker jacket",
    "куртка": "jacket",
    "куртки": "jacket",
    "жилет": "vest",
    "термобелье": "thermal base layer",
    "трусы": "briefs",
    "носки": "socks",
    # обувь
    "кроссовки": "running shoes",
    "шиповки": "track spikes",
    "ботинки": "boots",
    "тапочки": "slides",
    "стельки": "shoe insoles",
    # аксессуары и питание
    "перчатки": "gloves",
    "бафф": "tubular neck gaiter (buff)",
    "шапка": "beanie hat",
    "бейсболка": "baseball cap",
    "очки": "sunglasses",
    "рюкзак": "backpack",
    "сумка": "bag",
    "бутылка": "sports water bottle",
    "бутылки": "sports water bottle",
    "термос": "thermos flask",
    "гели": "energy gel sachet",
}

# Категории, которые ничего не уточняют: берём тип из названия.
VAGUE_CATEGORIES = {"все", "аксессуары", "all", "accessories"}

# Запасной путь: слово в названии карточки. Порядок важен — «футболка-поло»
# ищется раньше «футболки», иначе поло станет футболкой.
NAME_TYPES = (
    ("лонгслив", "long-sleeve athletic top"),
    ("футболка-поло", "polo shirt"),
    ("футболка", "short-sleeve t-shirt"),
    ("майка", "sleeveless tank top"),
    ("шорты", "shorts"),
    ("леггинсы", "leggings"),
    ("брюки", "trousers"),
    ("ветровка", "lightweight windbreaker jacket"),
    ("куртка", "jacket"),
    ("жилет", "vest"),
    ("кроссовки", "running shoes"),
    ("ботинки", "boots"),
    ("носки", "socks"),
    ("перчатки", "gloves"),
    ("бафф", "tubular neck gaiter (buff)"),
    ("нижнее белье", "briefs"),
    ("трусы", "briefs"),
    ("рюкзак", "backpack"),
    ("сумка", "bag"),
    ("очки", "sunglasses"),
    ("бутылка", "sports water bottle"),
)


def item_type(name: str = "", category: str = "") -> str:
    """Английское название типа вещи; «» — не распознали.

    Сначала категория (справочник 1С), затем название. Не распознали — лучше
    промолчать, чем подставить неверный тип: промт тогда просто назовёт карточку.
    """
    key = (category or "").strip().lower()
    if key and key not in VAGUE_CATEGORIES:
        english = CATEGORY_TYPES.get(key)
        if english:
            return english
    low = (name or "").lower()
    for russian, english in NAME_TYPES:
        if russian in low:
            return english
    return ""


# Вид товара — какая постановка кадра ему нужна. Определяется по английскому типу.
_FOOTWEAR_TYPES = {"running shoes", "track spikes", "boots", "slides"}
_ACCESSORY_TYPES = {
    "gloves", "tubular neck gaiter (buff)", "beanie hat", "baseball cap", "sunglasses",
    "backpack", "bag", "sports water bottle", "thermos flask", "energy gel sachet",
    "shoe insoles",
}


def item_kind(name: str = "", category: str = "") -> str:
    """Одежда, обувь или аксессуар. Не узнали — одежда: под неё промт писался
    изначально, и так ведёт себя всё, что было до v3."""
    kind = item_type(name, category)
    if kind in _FOOTWEAR_TYPES:
        return FOOTWEAR
    if kind in _ACCESSORY_TYPES:
        return ACCESSORY
    return GARMENT


def with_staging(prompt: str, track: str = "catalog", name: str = "",
                 category: str = "") -> str:
    """Добавить постановку кадра под вид товара. Неизвестный трек — без изменений."""
    block = STAGING.get((track, item_kind(name, category)))
    return prompt + "\n" + block if block else prompt


def with_item(prompt: str, name: str = "", category: str = "") -> str:
    """Сказать модели, КАКУЮ вещь брать с кадра — по названию карточки.

    Исходник часто маркетинговый: на человеке сразу лонгслив, шорты, кепка, носки
    и кроссовки. Правило «бери самую заметную» тут не работает — заметнее обычно
    не то, о чём карточка. Название товара и есть ответ, и оно у нас уже есть:
    задание сопоставлено с карточкой по артикулу.

    Название передаём как есть, по-русски: это истина из 1С, и модель его читает.
    Тип вещи добавляем по-английски, когда узнали, — так указание однозначнее.
    """
    name = (name or "").strip()
    if not name:
        return prompt
    kind = item_type(name, category)
    what = ('the %s' % kind) if kind else "the item"
    return (
        prompt
        + "\nWHICH ITEM: the reference may show several items worn together (top, "
        "shorts, cap, socks, shoes). This product card is about %s. Its name in the "
        "shop catalogue is \"%s\". Generate ONLY that item and nothing else: no other "
        "item from the reference - no other clothing, footwear or accessory. This "
        "overrides the "
        "\"most prominent item\" rule above." % (what, name)
    )
