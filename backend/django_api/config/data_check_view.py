# -*- coding: utf-8 -*-
"""Страницы «Проверка данных»: что в каталоге похоже на ошибку и что с этим делать.

Данные ведёт 1С и заполняют их руками — опечатки неизбежны. Сервер принимает их
молча, и ошибка живёт на витрине, пока её случайно не заметят.

Здесь три страницы:
- список замечаний по видам проверок;
- разбор одного замечания: позиции рядом, поле к полю, чтобы сразу увидеть, где
  расхождение, и открыть нужную карточку;
- закрытые замечания — те, что посмотрели и признали не ошибкой.

Ничего не исправляется автоматически: правим в 1С или в карточке, страница
перепроверит. Кнопка «Проверено» закрывает не замечание вообще, а КОНКРЕТНОЕ
состояние данных: изменились — замечание вернётся.
"""
from django.contrib import admin
from django.contrib.admin.views.decorators import staff_member_required
from django.http import Http404
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils import timezone

from catalog import audit
from catalog.models import CheckDismissal, Product
from integrations.models import OneCExchange
from staff.access import tab_required
from staff.models import StaffAudit


def _hidden():
    """Что уже помечено «проверено» — вместе с отпечатком данных."""
    return {(d.check_id, d.key, d.fingerprint)
            for d in CheckDismissal.objects.all().only("check_id", "key", "fingerprint")}


@staff_member_required
@tab_required("data_check")
def data_check(request):
    sections = audit.run_all(hidden=_hidden())
    for section in sections:
        for item in section["items"]:
            item["links"] = [{
                "id": p.id,
                "name": p.name,
                "url": reverse("admin:catalog_product_change", args=[p.pk]),
            } for p in item.get("products", [])]
            item["open_url"] = (f"{reverse('data_check_item')}?check={item['check']}"
                                f"&key={item['key']}")

    last = (OneCExchange.objects.filter(operation="catalog", status__in=("ok", "partial"))
            .order_by("-created_at").first())
    return TemplateResponse(request, "admin/data_check.html", {
        **admin.site.each_context(request),
        "title": "Проверка данных каталога",
        "total": Product.objects.count(),
        "sections": sections,
        "found": sum(s["total"] for s in sections),
        "dismissed": CheckDismissal.objects.count(),
        "checked_at": timezone.localtime(timezone.now()).strftime("%d.%m.%Y %H:%M"),
        "last_exchange": (timezone.localtime(last.created_at).strftime("%d.%m.%Y %H:%M")
                          if last else ""),
        "fill_link": reverse("onec_fill"),
        "closed_link": reverse("data_check_closed"),
        "note": request.session.pop("data_check_note", ""),
    })


def _find(check_id: str, key: str):
    """Найти замечание по проверке и ключу — уже с отпечатком данных."""
    for item in audit.run_check(check_id):
        if item["key"] == key:
            return item
    return None


@staff_member_required
@tab_required("data_check")
def data_check_item(request):
    """Разбор одного замечания: позиции рядом, поле к полю."""
    check_id = (request.GET.get("check") or request.POST.get("check") or "").strip()
    key = (request.GET.get("key") or request.POST.get("key") or "").strip()
    if check_id not in audit.BY_ID:
        raise Http404("Нет такой проверки")

    item = _find(check_id, key)

    if request.method == "POST":
        if item is None:
            request.session["data_check_note"] = "Замечание уже неактуально — данные изменились."
            return redirect("data_check")
        CheckDismissal.objects.get_or_create(
            check_id=check_id, key=key, fingerprint=item["fingerprint"],
            defaults={
                "note": (request.POST.get("note") or "").strip()[:300],
                "actor": request.user.get_username(),
            },
        )
        StaffAudit.write(request, f"проверка данных: закрыто {check_id}:{key}")
        request.session["data_check_note"] = f"Закрыто: {item['title']}"
        return redirect("data_check")

    if item is None:
        request.session["data_check_note"] = (
            "Замечание больше не воспроизводится — похоже, данные уже поправили.")
        return redirect("data_check")

    # Поля рядом: так видно, где именно расхождение.
    rows = [{
        "id": product.id,
        "name": product.name,
        "shop_title": product.shop_title,
        "article": product.article,
        "sizes": ", ".join(map(str, product.sizes or [])),
        "colors": ", ".join(map(str, product.colors or [])),
        "price": product.price,
        "stock": product.stock_count,
        "url": reverse("admin:catalog_product_change", args=[product.pk]),
    } for product in item.get("products", [])]

    title, _func = audit.BY_ID[check_id]
    return TemplateResponse(request, "admin/data_check_item.html", {
        **admin.site.each_context(request),
        "title": item["title"],
        "check_title": title,
        "check_id": check_id,
        "key": key,
        "item": item,
        "rows": rows,
        "back_link": reverse("data_check"),
    })


@staff_member_required
@tab_required("data_check")
def data_check_closed(request):
    """Закрытые замечания: что признали не ошибкой, кто и когда."""
    if request.method == "POST":
        pk = request.POST.get("id")
        CheckDismissal.objects.filter(pk=pk).delete()
        StaffAudit.write(request, f"проверка данных: замечание возвращено ({pk})")
        request.session["data_check_note"] = "Замечание возвращено в список."
        return redirect("data_check_closed")

    rows = []
    for row in CheckDismissal.objects.all()[:300]:
        title, _func = audit.BY_ID.get(row.check_id, (row.check_id, None))
        rows.append({
            "id": row.pk,
            "check": title,
            "key": row.key,
            "note": row.note,
            "actor": row.actor,
            "when": timezone.localtime(row.created_at).strftime("%d.%m.%Y %H:%M"),
        })
    return TemplateResponse(request, "admin/data_check_closed.html", {
        **admin.site.each_context(request),
        "title": "Закрытые замечания",
        "rows": rows,
        "back_link": reverse("data_check"),
        "note": request.session.pop("data_check_note", ""),
    })
