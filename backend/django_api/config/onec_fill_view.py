"""Страница «Заполненность 1С»: чего не хватает в карточках товаров.

Зачем. Каталог ведёт 1С, и на 21.09.2026 заполнено там немного: из 3373 позиций
категория есть у 214, бренд — у одной. Со стороны витрины это выглядит так:
товар без категории не попадёт ни в один раздел, товар без цены нельзя
продать, а без веса доставка считается по типовой коробке.

Строка «Фото» есть с 24.11.2026 (просьба владельца — видеть фото рядом с ценой и
описанием), но без метки «1С»: в 1С фото не будет, снимки ведём в своей системе
(Фото товаров / Фотопайплайн). Проверяем фото так же, как витрина; ниже — блок
«Фото по брендам» со ссылками на загрузку.

Страница отвечает на один вопрос: что именно просить заполнить в 1С в первую
очередь. По каждому полю — сколько заполнено, сколько пусто и чем пустота
грозит; «показать» открывает список именно незаполненных карточек.
"""
from urllib.parse import quote

from django.contrib import admin
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Count, Q
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils import timezone

from catalog import photos as photolib
from catalog.models import Category, Product
from integrations.models import OneCExchange
from staff.access import tab_required

# Поле → (заголовок, условие «пусто», чем грозит пустота).
# Условия описаны через Q, чтобы одним запросом посчитать всё сразу.
FIELDS = (
    ("category", "Категория", Q(category_id=""),
     "товар не попадёт ни в один раздел витрины"),
    ("price", "Цена", Q(price__lte=0),
     "нельзя продать: цена ноль"),
    ("brand", "Бренд", Q(brand=""),
     "не работает фильтр по бренду"),
    ("article", "Артикул", Q(article=""),
     "труднее сверять со складом"),
    ("sizes", "Размеры", Q(sizes=[]) | Q(sizes__isnull=True),
     "покупатель не выберет размер"),
    ("colors", "Цвета", Q(colors=[]) | Q(colors__isnull=True),
     "не показать цвет модели"),
    ("description", "Описание", Q(description=""),
     "пустая карточка товара"),
    ("parcel", "Вес и габариты", Q(weight_g__isnull=True) | Q(weight_g=0),
     "доставка считается по типовой коробке категории"),
    ("stock", "Остаток", Q(stock_count__isnull=True),
     "витрина не знает, есть ли товар в наличии"),
)

# Эти поля ведёт 1С — их и просить заполнять там. Остальное можем вести сами.
FROM_1C = {"category", "price", "brand", "article", "sizes",
           "colors", "description", "parcel", "stock"}


def _has_photo(product, photos: dict) -> bool:
    """Есть ли у товара снимок на витрине — по тем же правилам, что у витрины.

    Снимки нашей системы лежат у модели и цвета (Фото товаров / Фотопайплайн); нет
    их — витрина покажет старое фото карточки. Цветов несколько — снимок нужен у
    каждого: покупатель переключит цвет и увидит пустоту.
    """
    colors = [str(c).strip() for c in (product.colors or []) if str(c).strip()] or [""]
    if all(photolib.pick(photos, c) for c in colors):
        return True
    return bool(product.image) or bool(product.image_urls)


def _percent(part: int, whole: int) -> int:
    return round(part * 100 / whole) if whole else 0


def without_photo_ids(products=None) -> set:
    """Позиции без снимка на витрине — для строки «Фото» и фильтра «Не заполнено».

    Условие нельзя выразить одним Q: снимки лежат у модели и цвета, а не у позиции.
    Поэтому считаем в Python — тем же `_has_photo`, что и «готовы к витрине», чтобы
    цифра в сводке и список по «Показать» не разошлись.
    """
    products = list(Product.objects.all() if products is None else products)
    shots = photolib.by_model({p.shop_model_key or p.id for p in products})
    return {p.pk for p in products
            if not _has_photo(p, shots.get(p.shop_model_key or p.id))}


def _photo_by_brand(products, missing: set) -> list:
    """Фото по брендам в моделях: сколько моделей совсем без снимков и сколько в наличии.

    Модель «без фото», если ни у одной её позиции нет снимка; «частично» — снимки
    есть не у всех цветов. Сотрудник снимает модель целиком, поэтому считаем модели.
    """
    models = {}
    for p in products:
        key = p.shop_model_key or p.id
        m = models.setdefault(key, {"brand": (p.brand or "").strip(), "has": False,
                                    "miss": False, "stock": False})
        m["brand"] = m["brand"] or (p.brand or "").strip()
        if p.pk in missing:
            m["miss"] = True
        else:
            m["has"] = True
        if p.in_stock:
            m["stock"] = True

    brands = {}
    for m in models.values():
        b = brands.setdefault(m["brand"], {"brand": m["brand"], "models": 0, "full": 0,
                                          "partial": 0, "empty": 0, "empty_in_stock": 0})
        b["models"] += 1
        if not m["has"]:
            b["empty"] += 1
            if m["stock"]:
                b["empty_in_stock"] += 1
        elif m["miss"]:
            b["partial"] += 1
        else:
            b["full"] += 1

    rows = sorted(brands.values(), key=lambda b: (-b["empty"], -b["models"], b["brand"]))
    photos = reverse("product_photos")
    changelist = reverse("admin:catalog_product_changelist")
    for b in rows:
        b["percent"] = _percent(b["full"], b["models"])
        b["upload_link"] = f"{photos}?q={quote(b['brand'])}" if b["brand"] else photos
        b["list_link"] = (f"{changelist}?missing=photo&brand__exact={quote(b['brand'])}")
    return rows


@staff_member_required
@tab_required("onec_fill")
def onec_fill(request):
    total = Product.objects.count()
    # Один запрос на все поля: на тысячах карточек это заметно быстрее, чем count() по каждому.
    empty = Product.objects.aggregate(**{
        key: Count("pk", filter=cond) for key, _, cond, _ in FIELDS
    }) if total else {}

    rows = []
    for key, title, _cond, risk in FIELDS:
        blank = empty.get(key, 0)
        rows.append({
            "key": key,
            "title": title,
            "filled": total - blank,
            "blank": blank,
            "percent": _percent(total - blank, total),
            "risk": risk,
            "from_1c": key in FROM_1C,
            "link": f"{reverse('admin:catalog_product_changelist')}?missing={key}",
        })

    # Фото — не поле 1С (снимки ведём сами), но владелец хочет видеть его в той же
    # таблице, рядом с ценой и описанием (24.11.2026).
    products = list(Product.objects.all())
    missing_photo = without_photo_ids(products)
    rows.append({
        "key": "photo",
        "title": "Фото",
        "filled": total - len(missing_photo),
        "blank": len(missing_photo),
        "percent": _percent(total - len(missing_photo), total),
        "risk": "покупатель видит пустую карточку",
        "from_1c": False,
        "link": f"{reverse('admin:catalog_product_changelist')}?missing=photo",
    })
    rows.sort(key=lambda r: (-r["blank"], r["title"]))

    # Категория указана, но такой категории у нас нет — товар потеряется так же,
    # как и без категории, но по журналу это видно только в замечаниях обмена.
    known = set(Category.objects.values_list("id", flat=True))
    lost = (Product.objects.exclude(category_id="")
            .exclude(category_id__in=known)
            .values("category_id")
            .annotate(n=Count("pk")).order_by("-n")[:10])

    last = OneCExchange.objects.filter(operation="catalog",
                                       status__in=("ok", "partial")).first()
    # «Готов к витрине» = есть цена, фото и категория, КОТОРАЯ У НАС ЕСТЬ. Чужая
    # категория не считается: на витрине такой товар теряется ровно так же, как без неё.
    # Цена и категория — из 1С, фото — из нашей системы (в 1С их не будет).
    ready = sum(1 for p in products
                if p.category_id in known and p.price > 0 and p.pk not in missing_photo)

    return TemplateResponse(request, "admin/onec_fill.html", {
        **admin.site.each_context(request),
        "title": "Заполненность карточек 1С",
        "total": total,
        "rows": rows,
        "ready": ready,
        "ready_percent": _percent(ready, total),
        "categories": len(known),
        "lost": list(lost),
        "lost_total": sum(r["n"] for r in lost),
        "last_at": timezone.localtime(last.created_at).strftime("%d.%m.%Y %H:%M")
        if last else "",
        "log_link": reverse("onec_log"),
        "photo_brands": _photo_by_brand(products, missing_photo),
        "photos_link": reverse("product_photos"),
    })
