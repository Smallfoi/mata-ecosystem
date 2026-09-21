"""Страница «Фото товаров»: заливка картинок плиткой, без захода в карточки.

Фото ведём мы сами (D-91), а карточек 3373 и фото нет ни у одной. Через обычную
карточку это открыть — загрузить — сохранить — вернуться, минута на товар: месяцы
работы. Здесь видно сразу шесть десятков карточек без фото, картинка ставится
перетаскиванием и сохраняется сразу, страница не перезагружается.
"""
import json

from django.contrib import admin
from django.contrib.admin.views.decorators import staff_member_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import JsonResponse
from django.template.response import TemplateResponse
from django.urls import reverse

from catalog.models import Product
from staff.access import tab_required
from staff.models import StaffAudit

PER_PAGE = 60
MAX_BYTES = 12 * 1024 * 1024          # 12 МБ — фотоаппарат влезает, «архив» нет
ALLOWED = {"image/jpeg", "image/png", "image/webp"}
NO_PHOTO = Q(image="") & (Q(image_urls=[]) | Q(image_urls__isnull=True))


def _upload(request):
    """Приём одной картинки. Возвращает JSON — страница не перезагружается."""
    product = Product.objects.filter(pk=request.POST.get("id")).first()
    if product is None:
        return JsonResponse({"ok": False, "error": "товар не найден"}, status=404)

    photo = request.FILES.get("photo")
    if photo is None:
        return JsonResponse({"ok": False, "error": "файл не пришёл"}, status=400)
    if photo.size > MAX_BYTES:
        return JsonResponse({"ok": False,
                             "error": f"файл больше {MAX_BYTES // 1024 // 1024} МБ"}, status=400)
    if photo.content_type not in ALLOWED:
        return JsonResponse({"ok": False, "error": "нужен JPEG, PNG или WEBP"}, status=400)

    product.image = photo
    product.save(update_fields=["image"])
    StaffAudit.write(request, f"фото товара {product.id} ({product.name[:60]})")
    return JsonResponse({"ok": True, "url": product.network_image_url()})


@staff_member_required
@tab_required("product_photos")
def product_photos(request):
    if request.method == "POST":
        return _upload(request)

    query = (request.GET.get("q") or "").strip()
    only = request.GET.get("only", "empty")          # empty | all

    qs = Product.objects.all()
    if only != "all":
        qs = qs.filter(NO_PHOTO)
    if query:
        qs = qs.filter(Q(name__icontains=query) | Q(article__icontains=query)
                       | Q(global_name__icontains=query) | Q(brand__icontains=query))
    qs = qs.order_by("name")

    page = Paginator(qs, PER_PAGE).get_page(request.GET.get("page"))
    items = [{
        "id": p.id,
        "name": p.name,
        "meta": " · ".join(x for x in (p.brand, p.article) if x),
        "url": p.network_image_url(),
    } for p in page]

    return TemplateResponse(request, "admin/product_photos.html", {
        **admin.site.each_context(request),
        "title": "Фото товаров",
        "items": items,
        "page": page,
        "query": query,
        "only": only,
        "left": Product.objects.filter(NO_PHOTO).count(),
        "total": Product.objects.count(),
        "max_mb": MAX_BYTES // 1024 // 1024,
        "fill_link": reverse("onec_fill"),
    })
