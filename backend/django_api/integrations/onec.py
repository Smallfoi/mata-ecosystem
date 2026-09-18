"""Приём каталога из 1С (D-62).

Источник правды по номенклатуре — 1С, но владелец может точечно переопределить
поле в Конструкторе. Правило одно: импорт обновляет поле, ТОЛЬКО если владелец
его не трогал. Что пришло из 1С, всегда сохраняем в `from_1c` — чтобы показать
расхождение и дать кнопку «вернуть как в 1С».

Остаток владельцу переопределять нельзя: показать размер, которого нет на складе,
дороже, чем неудобство. Поэтому `stock` всегда пишется из 1С.
"""
import hashlib

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from catalog.models import Category, Product

# Поле в JSON от 1С → поле модели. Ключи совпадают с Product.OVERRIDABLE.
FIELD_MAP = {
    # 1С шлёт ключ строчными буквами (`globalname`), в договорённости был
    # `globalName` — принимаем оба написания, чтобы не зависеть от их правки.
    "globalName": "global_name",
    "globalname": "global_name",
    "price": "price",
    "oldPrice": "old_price",
    "description": "description",
    "sizes": "sizes",
    "colors": "colors",
    "images": "image_urls",
}


# Вес и габариты в упаковке (D-79): граммы и сантиметры — в них считают службы
# доставки. Владелец их не переопределяет: склад знает вес точнее.
PARCEL_MAP = {
    "weightG": "weight_g",
    "lengthCm": "length_cm",
    "widthCm": "width_cm",
    "heightCm": "height_cm",
}


def _parcel_errors(product: Product, raw: dict, who: str) -> list:
    """Записать вес и габариты, если 1С их прислала. Не прислала — не трогаем:
    там может быть ручной ввод из админки. Мусор — в отчёт, поле без изменений."""
    errors = []
    for key, field in PARCEL_MAP.items():
        value = raw.get(key)
        if value is None or value == "":
            continue
        try:
            number = round(float(value))
        except (TypeError, ValueError):
            errors.append(f"{who}: {key} не число")
            continue
        if number <= 0:
            errors.append(f"{who}: {key} должен быть больше нуля")
            continue
        setattr(product, field, number)
    return errors


# Поля, которые мы читаем в каждом потоке. Всё остальное 1С присылает зря — и это
# должно быть видно, а не теряться молча.
CATALOG_KEYS = {"id", "article", "name", "globalName", "globalname", "categoryId",
                "brand", "active", "updatedAt",
                "price", "oldPrice", "description", "sizes", "colors", "images",
                "weightG", "lengthCm", "widthCm", "heightCm"}
PRICE_KEYS = {"id", "article", "price", "oldPrice", "stock", "variants"}
CATEGORY_KEYS = {"id", "name", "parentId", "sort"}

SAMPLE_VALUE = 200     # длина строкового значения в примере
MAX_REPORTED = 40      # сколько полей показываем в отчёте


def _is_filled(value) -> bool:
    """Значение непустое: пустая строка, null и список из пустот не считаются."""
    if value is None or value == "" or value == [] or value == {}:
        return False
    if isinstance(value, list):
        return any(_is_filled(v) for v in value)
    if isinstance(value, str):
        return value.strip().lower() not in {"", "none", "null", "не указан", "не указано"}
    return True


def _diagnostics(items, known: set) -> tuple:
    """Что пришло: пример позиции, незнакомые поля и заполненность каждого поля.

    Смотрим ВСЮ пачку, а не первые позиции: новое поле в 1С сначала заполняют у
    нескольких карточек, и они запросто окажутся в конце выгрузки. Пример берём
    самый «полный»: у бедной строки половины полей нет, и по ней не понять, что 1С
    умеет присылать. Заполненность («непусто у N из M») показывает, как идёт
    заполнение карточек в 1С, — без неё «мы уже завели поле» не проверить.
    """
    best, unknown, filled, total = {}, set(), {}, 0
    for raw in items:
        if not isinstance(raw, dict):
            continue
        total += 1
        for key, value in raw.items():
            if key not in known:
                unknown.add(key)
            if _is_filled(value):
                filled[key] = filled.get(key, 0) + 1
        if len(raw) > len(best):
            best = raw

    sample = {}
    for key, value in list(best.items())[:MAX_REPORTED]:
        sample[key] = value[:SAMPLE_VALUE] if isinstance(value, str) else value
    report = {key: {"filled": filled.get(key, 0), "of": total, "known": key in known}
              for key in sorted(set(list(best.keys()) + list(filled.keys()) + list(unknown)))[:MAX_REPORTED]}
    return sample, sorted(unknown), report


# Сколько позиций принимаем за один запрос. Выгрузка целиком тоже не редкость,
# поэтому потолок высокий — он защищает от бессмысленного, а не от большого.
# Всё, что приходит, разбирается пачками по CHUNK, а не построчно.
MAX_ITEMS = 20_000
CHUNK = 500


class _Index:
    """Что уже есть в базе — одним запросом на всю выгрузку.

    Раньше на каждую позицию уходило по два-три обращения к базе (найти по id 1С,
    найти по артикулу, проверить свободен ли внутренний id). На тысяче товаров это
    тысячи запросов, и выгрузка упиралась в таймаут.
    """

    def __init__(self, items):
        ext, art = set(), set()
        for raw in items:
            if not isinstance(raw, dict):
                continue
            e = str(raw.get("id") or "").strip()
            a = str(raw.get("article") or "").strip()
            if e:
                ext.add(e)
            if a:
                art.add(a)

        rows = Product.objects.filter(Q(external_id__in=ext) | Q(article__in=art))
        self.by_ext, self.by_art = {}, {}
        for p in rows:
            if p.external_id:
                self.by_ext[p.external_id] = p
            if p.article:
                self.by_art.setdefault(p.article, p)
        # Занятые внутренние id: проверяем по множеству, а не запросом на товар.
        self.taken = set(
            Product.objects.filter(id__in=(ext | art)).values_list("id", flat=True)
        )

    def find(self, external_id: str, article: str):
        if external_id and external_id in self.by_ext:
            return self.by_ext[external_id]
        if article:
            return self.by_art.get(article)
        return None

    def make_id(self, external_id: str, article: str) -> str:
        """Внутренний id для НОВОГО товара. Идентификатор 1С в первичный ключ не кладём:
        на него уже ссылаются заказы и отзывы, менять их формат нельзя."""
        base = (article or external_id or "").strip()
        if base and len(base) <= 40 and base not in self.taken:
            self.taken.add(base)
            return base
        return "p_" + hashlib.sha1((external_id or article).encode("utf-8")).hexdigest()[:16]

    def remember(self, product: Product) -> None:
        """Новый товар — чтобы дубль внутри ОДНОЙ выгрузки не создался дважды."""
        if product.external_id:
            self.by_ext[product.external_id] = product
        if product.article:
            self.by_art.setdefault(product.article, product)
        self.taken.add(product.id)


# Списочные поля карточки: размеры, цвета, фото. 1С заводит их у каждой позиции, но
# пока большинство карточек не заполнено — приходит [null]. Пустое должно оставаться
# пустым: [null] на витрине превращается в пустую «плашку» размера.
LIST_FIELDS = {"sizes", "colors", "images"}
# Текстовые поля: 1С присылает незаполненное как null, а в базе у них NOT NULL —
# без приведения к пустой строке выгрузка падала бы на первой пустой карточке.
TEXT_FIELDS = {"globalName", "globalname", "description"}
_EMPTY = {"", "none", "null", "не указан", "не указано", "-", "—"}


def _clean_list(value) -> list:
    """Значения из 1С: без пустот и повторов, обрезанные по краям, порядок сохранён."""
    if not isinstance(value, list):
        value = [value]
    out: list = []
    for item in value:
        if item is None:
            continue
        text = str(item).strip()
        if not text or text.lower() in _EMPTY:
            continue
        text = text[:80]
        if text not in out:
            out.append(text)
    return out


def _apply(product: Product, payload: dict, fields: dict) -> list:
    """Записать пришедшие поля: эффективное значение — только если не переопределено.
    Возвращает список полей, которые владелец удержал за собой (для отчёта)."""
    kept = []
    src = dict(product.from_1c or {})
    for json_field, model_field in fields.items():
        if json_field not in payload:
            continue
        value = payload[json_field]
        src[json_field] = value                      # в from_1c кладём как прислали
        if product.is_overridden(json_field):
            kept.append(json_field)
            continue
        if json_field in LIST_FIELDS:
            value = _clean_list(value)
        elif json_field in TEXT_FIELDS:
            value = str(value).strip() if value is not None else ""
        setattr(product, model_field, value)
    product.from_1c = src
    return kept


def import_categories(items) -> dict:
    """Справочник категорий из 1С.

    Что ведёт 1С: название, порядок, родитель. Что остаётся нашим: эмодзи и фото
    категории — их в 1С нет, и затирать их пустотой при каждой выгрузке нельзя.

    Пропавшие из выгрузки категории НЕ удаляем: на категорию ссылаются товары, и
    молчаливое удаление увело бы их с витрины. Категория — вещь редкая, убрать её
    осознанно проще в админке, чем разбираться, почему исчез раздел.
    """
    errors = []
    ids = [str(r.get("id") or "").strip() for r in items if isinstance(r, dict)]
    existing = {c.id: c for c in Category.objects.filter(id__in=[i for i in ids if i])}
    to_create, to_update = [], []

    for raw in items:
        if not isinstance(raw, dict):
            errors.append("элемент не объект")
            continue
        cid = str(raw.get("id") or "").strip()
        if not cid:
            errors.append("нет id категории")
            continue
        if len(cid) > 40:
            errors.append(f"{cid[:20]}…: id длиннее 40 символов")
            continue

        category = existing.get(cid)
        is_new = category is None
        if is_new:
            if not raw.get("name"):
                errors.append(f"{cid}: нет названия")
                continue
            category = Category(id=cid)
            existing[cid] = category   # дубль внутри одной выгрузки не создастся дважды

        if raw.get("name"):
            category.name = str(raw["name"])[:120]
        if "parentId" in raw:
            category.parent_id = str(raw.get("parentId") or "")[:40]
        if raw.get("sort") is not None:
            try:
                category.sort = int(raw["sort"])
            except (TypeError, ValueError):
                errors.append(f"{cid}: порядок не число")
        (to_create if is_new else to_update).append(category)

    with transaction.atomic():
        Category.objects.bulk_create(to_create, batch_size=CHUNK)
        if to_update:
            # Только то, что ведёт 1С: эмодзи и фото категории остаются нашими.
            Category.objects.bulk_update(to_update, ["name", "parent_id", "sort"],
                                         batch_size=CHUNK)

    sample, unknown, report = _diagnostics(items, CATEGORY_KEYS)
    return {"received": len(items), "created": len(to_create), "updated": len(to_update),
            "errors": errors[:20], "sample": sample, "unknownKeys": unknown, "fields": report}


# Что переписывает выгрузка карточек. Поля витрины (публикация, новинка,
# рекомендуемое, порядок, рейтинг) в списке отсутствуют намеренно — это зона МАТА.
CATALOG_FIELDS = [
    "external_id", "article", "name", "global_name", "category_id", "brand", "is_active_1c",
    "source_updated_at", "from_1c", "price", "old_price", "description",
    "sizes", "colors", "image_urls", "weight_g", "length_cm", "width_cm", "height_cm",
]

# Что переписывает выгрузка цен и остатков.
PRICE_FIELDS = ["price", "old_price", "from_1c", "stock_count", "stock_by_size", "in_stock"]


def import_catalog(items) -> dict:
    """Карточки товаров: наименование, категория, бренд, описание, размеры, фото."""
    skipped = 0
    kept_fields: set = set()
    errors = []
    # Категория — простая строка, а не внешний ключ, поэтому товар с незнакомой
    # категорией сохранится молча и пропадёт из разделов витрины. Молчать об этом
    # нельзя: со стороны это выглядит как «товар не выгрузился».
    known = set(Category.objects.values_list("id", flat=True))
    unknown: set = set()
    index = _Index(items)
    # Словари, а не списки: проверка «этот товар уже в пачке» по ключу, иначе на
    # тысячах позиций получится квадрат — ровно то, что мы здесь и чиним.
    to_create: dict = {}
    to_update: dict = {}

    for raw in items:
        if not isinstance(raw, dict):
            errors.append("элемент не объект")
            continue
        external_id = str(raw.get("id") or "").strip()
        article = str(raw.get("article") or "").strip()
        if not external_id and not article:
            errors.append("нет id и артикула")
            continue

        product = index.find(external_id, article)
        is_new = product is None
        if is_new:
            if not raw.get("name"):
                errors.append(f"{external_id or article}: нет наименования")
                continue
            product = Product(id=index.make_id(external_id, article), price=0)

        # Поля, которые ведёт только 1С.
        product.external_id = external_id or product.external_id
        product.article = article or product.article
        if raw.get("name"):
            product.name = raw["name"]
        if raw.get("categoryId"):
            product.category_id = str(raw["categoryId"])
            if product.category_id not in known:
                unknown.add(product.category_id)
        if "brand" in raw:
            product.brand = raw.get("brand") or ""
        if "active" in raw:
            product.is_active_1c = bool(raw["active"])
        if raw.get("updatedAt"):
            product.source_updated_at = parse_datetime(raw["updatedAt"]) or timezone.now()

        kept_fields.update(_apply(product, raw, FIELD_MAP))
        errors.extend(_parcel_errors(product, raw, external_id or article))
        if is_new:
            index.remember(product)
            to_create[product.id] = product
        elif product.id not in to_create:
            to_update[product.id] = product

    with transaction.atomic():
        Product.objects.bulk_create(list(to_create.values()), batch_size=CHUNK)
        if to_update:
            Product.objects.bulk_update(list(to_update.values()), CATALOG_FIELDS,
                                        batch_size=CHUNK)
    created, updated = len(to_create), len(to_update)

    for cid in sorted(unknown):
        errors.append(f"категория «{cid}» не заведена — товары не попадут в раздел")

    sample, unknown_keys, report = _diagnostics(items, CATALOG_KEYS)
    return {
        "received": len(items), "created": created, "updated": updated,
        "skipped": skipped, "keptByOwner": sorted(kept_fields),
        "unknownCategories": sorted(unknown), "errors": errors[:20],
        "sample": sample, "unknownKeys": unknown_keys, "fields": report,
    }


def import_prices(items) -> dict:
    """Цены и остатки — частый поток. Остаток пишем всегда, цену — если не переопределена."""
    kept_fields: set = set()
    errors = []
    index = _Index(items)
    touched: dict = {}

    for raw in items:
        if not isinstance(raw, dict):
            errors.append("элемент не объект")
            continue
        external_id = str(raw.get("id") or "").strip()
        article = str(raw.get("article") or "").strip()
        product = index.find(external_id, article)
        if product is None:
            errors.append(f"{external_id or article}: товар не найден")
            continue

        kept_fields.update(_apply(product, raw, {"price": "price", "oldPrice": "old_price"}))

        variants = raw.get("variants")
        if isinstance(variants, list):
            total = 0
            by_size: dict = {}
            for v in variants:
                if not isinstance(v, dict):
                    continue
                try:
                    stock = int(v.get("stock") or 0)
                except (TypeError, ValueError):
                    errors.append(f"{external_id or article}: остаток варианта не число")
                    continue
                total += stock
                size = str(v.get("size") or "").strip()
                if size:
                    # Один размер может прийти несколькими строками (разные цвета
                    # или склады) — складываем, а не перетираем.
                    by_size[size] = by_size.get(size, 0) + stock
            product.stock_count = total
            product.stock_by_size = by_size
            src = dict(product.from_1c or {})
            src["variants"] = variants
            product.from_1c = src
        elif "stock" in raw:
            try:
                product.stock_count = int(raw.get("stock") or 0)
            except (TypeError, ValueError):
                errors.append(f"{external_id or article}: остаток не число")
                continue
            # Общий остаток без разбивки: старую разбивку держать нельзя, она
            # уже неправда.
            product.stock_by_size = {}

        if product.stock_count is not None:
            product.in_stock = product.stock_count > 0

        touched[product.id] = product

    with transaction.atomic():
        Product.objects.bulk_update(list(touched.values()), PRICE_FIELDS, batch_size=CHUNK)

    sample, unknown, report = _diagnostics(items, PRICE_KEYS)
    return {"received": len(items), "updated": len(touched),
            "keptByOwner": sorted(kept_fields), "errors": errors[:20],
            "sample": sample, "unknownKeys": unknown, "fields": report}
