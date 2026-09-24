"""Страница «Фото товаров»: заливка галереи по модели и цвету.

Фото ведём мы сами (D-91), а снимки зависят от ЦВЕТА, а не от размера (D-99):
в 1С каждый размер — своя карточка, но чёрные кроссовки выглядят одинаково и в
41-м, и в 42-м. Поэтому плитка здесь — это «модель + цвет», внутри шесть мест;
что зальёшь, то увидят все размеры этого цвета.

Заходить в карточки не нужно: перетащил файлы на плитку — сохранились сразу,
страница не перезагружается.
"""
import json
import secrets
from collections import OrderedDict

from django.contrib import admin
from django.contrib.admin.views.decorators import staff_member_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import JsonResponse
from django.template.response import TemplateResponse
from django.urls import reverse

from catalog import photos as photolib
from catalog.models import Product, ProductPhoto
from staff.access import tab_required
from staff.models import StaffAudit

PER_PAGE = 24
MAX_BYTES = 12 * 1024 * 1024          # 12 МБ — фотоаппарат влезает, «архив» нет
ALLOWED = {"image/jpeg", "image/png", "image/webp"}


def _pairs(qs):
    """Пары «модель + цвет» в порядке витрины — по ним и раскладывают фото.

    Цвета берём строго из поля 1С (D-95). Строка пуста — у модели одна плитка «без
    цвета»: показывать снимки всё равно нужно, пока цвета не заполнили.
    """
    groups = OrderedDict()
    for product in qs:
        key = product.shop_model_key or product.id
        entry = groups.setdefault(key, {"key": key, "name": product.shop_title,
                                        "meta": [], "colors": []})
        if not entry["meta"]:
            entry["meta"] = [x for x in (product.brand, product.article) if x]
        for color in (product.colors or []):
            color = str(color).strip()
            if color and color not in entry["colors"]:
                entry["colors"].append(color)

    out = []
    for entry in groups.values():
        for color in (entry["colors"] or [""]):
            out.append({"key": entry["key"], "name": entry["name"],
                        "meta": " · ".join(entry["meta"]), "color": color})
    return out


def _upload(request):
    """Приём одного снимка в галерею модели и цвета. Ответ — JSON, без перезагрузки."""
    model_key = (request.POST.get("key") or "").strip()
    color = (request.POST.get("color") or "").strip()
    if not model_key:
        return JsonResponse({"ok": False, "error": "не указана модель"}, status=400)

    photo = request.FILES.get("photo")
    if photo is None:
        return JsonResponse({"ok": False, "error": "файл не пришёл"}, status=400)
    if photo.size > MAX_BYTES:
        return JsonResponse({"ok": False,
                             "error": f"файл больше {MAX_BYTES // 1024 // 1024} МБ"}, status=400)
    if photo.content_type not in ALLOWED:
        return JsonResponse({"ok": False, "error": "нужен JPEG, PNG или WEBP"}, status=400)

    try:
        row = photolib.store_photo(model_key, color, photo.read(),
                                   f"{secrets.token_hex(8)}")
    except ValueError as e:
        return JsonResponse({"ok": False, "error": str(e)}, status=400)
    except Exception:
        # Битый файл: PIL не открыл. Сообщаем человеку, а не 500-ой страницей.
        return JsonResponse({"ok": False, "error": "не удалось прочитать картинку"},
                            status=400)

    StaffAudit.write(request, f"фото модели {model_key} ({color or 'без цвета'})")
    return JsonResponse({"ok": True, "id": row.pk, **row.to_json()})


def _drop(request):
    row = ProductPhoto.objects.filter(pk=request.POST.get("id")).first()
    if row is None:
        return JsonResponse({"ok": False, "error": "фото не найдено"}, status=404)
    key, color = row.model_key, row.color
    row.delete()
    photolib.renumber(key, color)
    StaffAudit.write(request, f"удалено фото модели {key} ({color or 'без цвета'})")
    return JsonResponse({"ok": True})


def _main(request):
    row = ProductPhoto.objects.filter(pk=request.POST.get("id")).first()
    if row is None:
        return JsonResponse({"ok": False, "error": "фото не найдено"}, status=404)
    photolib.make_main(row)
    StaffAudit.write(request, f"главное фото модели {row.model_key} ({row.color or 'без цвета'})")
    return JsonResponse({"ok": True})


@staff_member_required
@tab_required("product_photos")
def product_photos(request):
    if request.method == "POST":
        action = request.POST.get("action") or "upload"
        if action == "delete":
            return _drop(request)
        if action == "main":
            return _main(request)
        return _upload(request)

    query = (request.GET.get("q") or "").strip()
    only = request.GET.get("only", "empty")          # empty | all

    qs = Product.objects.all()
    if query:
        qs = qs.filter(Q(name__icontains=query) | Q(display_name__icontains=query)
                       | Q(article__icontains=query) | Q(brand__icontains=query))
    pairs = _pairs(qs.order_by("name"))

    # Сколько снимков уже лежит у каждой пары — одним запросом на всю страницу.
    have = {}
    for row in ProductPhoto.objects.filter(model_key__in={p["key"] for p in pairs}):
        have.setdefault((row.model_key, photolib.norm_color(row.color)), []).append(row)

    all_count = len(pairs)
    empty_count = sum(
        1 for p in pairs if not have.get((p["key"], photolib.norm_color(p["color"])))
    )
    if only != "all":
        pairs = [p for p in pairs
                 if not have.get((p["key"], photolib.norm_color(p["color"])))]

    page = Paginator(pairs, PER_PAGE).get_page(request.GET.get("page"))
    items = []
    for p in page:
        rows = have.get((p["key"], photolib.norm_color(p["color"]))) or []
        rows.sort(key=lambda r: (r.order, r.pk))
        items.append({**p,
                      "photos": [{"id": r.pk, **r.to_json()} for r in rows],
                      "free": range(ProductPhoto.MAX_PER_COLOR - len(rows))})

    return TemplateResponse(request, "admin/product_photos.html", {
        **admin.site.each_context(request),
        "title": "Фото товаров",
        "items": items,
        "page": page,
        "query": query,
        "only": only,
        "left": empty_count,
        "total": all_count,
        "max_photos": ProductPhoto.MAX_PER_COLOR,
        "max_mb": MAX_BYTES // 1024 // 1024,
        "fill_link": reverse("onec_fill"),
    })
