# -*- coding: utf-8 -*-
"""Страница «Проверка данных»: что в каталоге похоже на ошибку.

Данные ведёт 1С и заполняют их руками — опечатки неизбежны. Сервер принимает
их молча, и ошибка живёт на витрине, пока её случайно не заметят. Эта страница
смотрит на каталог целиком и говорит, на что обратить внимание: у одного
артикула разный пол в названиях, в размере оказалась длина, цвет в строке
не тот, что в названии.

Ничего не исправляется автоматически: правим в 1С, страница перепроверит.
"""
from django.contrib import admin
from django.contrib.admin.views.decorators import staff_member_required
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils import timezone

from catalog import audit
from catalog.models import Product
from integrations.models import OneCExchange
from staff.access import tab_required


@staff_member_required
@tab_required("data_check")
def data_check(request):
    total = Product.objects.count()
    sections = audit.run_all()

    # К каждой находке — ссылки на карточки, чтобы открыть и сверить.
    for section in sections:
        for item in section["items"]:
            item["links"] = [{
                "id": p.id,
                "name": p.name,
                "url": reverse("admin:catalog_product_change", args=[p.pk]),
            } for p in item.get("products", [])]

    last = (OneCExchange.objects.filter(operation="catalog", status__in=("ok", "partial"))
            .order_by("-created_at").first())
    return TemplateResponse(request, "admin/data_check.html", {
        **admin.site.each_context(request),
        "title": "Проверка данных каталога",
        "total": total,
        "sections": sections,
        "found": sum(s["total"] for s in sections),
        "checked_at": timezone.localtime(timezone.now()).strftime("%d.%m.%Y %H:%M"),
        "last_exchange": (timezone.localtime(last.created_at).strftime("%d.%m.%Y %H:%M")
                          if last else ""),
        "fill_link": reverse("onec_fill"),
    })
