"""Страница «Заполненность 1С»: чего не хватает в карточках товаров.

Зачем. Каталог ведёт 1С, и на 21.09.2026 заполнено там немного: из 3373 позиций
категория есть у 214, бренд — у одной. Со стороны витрины это выглядит так:
товар без категории не попадёт ни в один раздел, товар без фото и цены
бессмысленно показывать, а без веса доставка считается по типовой коробке.

Страница отвечает на один вопрос: что именно просить заполнить в 1С в первую
очередь. По каждому полю — сколько заполнено, сколько пусто и чем пустота
грозит; «показать» открывает список именно незаполненных карточек.
"""
from django.contrib import admin
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Count, Q
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils import timezone

from catalog.models import Category, Product
from integrations.models import OneCExchange
from staff.access import tab_required

# Поле → (заголовок, условие «пусто», чем грозит пустота).
# Условия описаны через Q, чтобы одним запросом посчитать всё сразу.
FIELDS = (
    ("category", "Категория", Q(category_id=""),
     "товар не попадёт ни в один раздел витрины"),
    ("photo", "Фото", Q(image="") & (Q(image_urls=[]) | Q(image_urls__isnull=True)),
     "карточка в каталоге без картинки"),
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


def _percent(part: int, whole: int) -> int:
    return round(part * 100 / whole) if whole else 0


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
    ready = (Product.objects.filter(category_id__in=known)
             .exclude(price__lte=0)
             .exclude(Q(image="") & (Q(image_urls=[]) | Q(image_urls__isnull=True)))
             .count())

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
    })
