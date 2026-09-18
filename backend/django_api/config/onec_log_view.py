"""Страница «Журнал обмена» в блоке «Мониторинг» (D-62).

Отвечает на три вопроса владельца: приходила ли сегодня выгрузка из 1С, сколько
товаров она добавила и обновила, и не ругался ли приём. Всё в одной таблице по
датам, время — якутское.
"""
import json
from datetime import timedelta

from django.conf import settings
from django.contrib import admin
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Sum
from django.template.response import TemplateResponse
from django.utils import timezone

from integrations.models import OneCExchange
from staff.access import tab_required

PAGE_SIZE = 200


def _local(dt):
    """Время по-якутски (settings.TIME_ZONE=Asia/Yakutsk) — как на остальных страницах."""
    if not dt:
        return ""
    return timezone.localtime(dt).strftime("%d.%m.%Y %H:%M:%S")


def _hours_since(dt):
    if not dt:
        return None
    return int((timezone.now() - dt).total_seconds() // 3600)


def _fields_line(report: dict) -> str:
    """«Заполнено: наименование 3373, категория 214…» — как идёт заполнение в 1С."""
    if not report:
        return ""
    parts = []
    for key, info in report.items():
        mark = "" if info.get("known") else " ⚠"
        parts.append(f"{key}{mark} {info.get('filled', 0)}/{info.get('of', 0)}")
    return " · ".join(parts)


@staff_member_required
@tab_required("onec_log")
def onec_log(request):
    op = (request.GET.get("op") or "all").strip()
    status = (request.GET.get("status") or "all").strip()

    qs = OneCExchange.objects.all()
    if op in ("catalog", "prices"):
        qs = qs.filter(operation=op)
    if status in ("ok", "partial", "error"):
        qs = qs.filter(status=status)

    rows = []
    for r in qs[:PAGE_SIZE]:
        rows.append({
            "when": _local(r.created_at),
            "operation": r.get_operation_display(),
            "op_code": r.operation,
            "status": r.get_status_display(),
            "status_code": r.status,
            "received": r.received,
            "created": r.created_count,
            "updated": r.updated_count,
            "skipped": r.skipped,
            "kept": r.kept_by_owner or [],
            "errors": (r.errors or [])[:3],
            "errors_more": max(0, len(r.errors or []) - 3),
            "duration": f"{r.duration_ms} мс" if r.duration_ms else "—",
            "detail": r.detail,
            "unknown_keys": r.unknown_keys or [],
            "sample": json.dumps(r.sample, ensure_ascii=False, indent=2) if r.sample else "",
            "fields": _fields_line(r.fields_report),
        })

    day = timezone.now() - timedelta(hours=24)
    d = OneCExchange.objects.filter(created_at__gte=day)
    agg = d.aggregate(c=Sum("created_count"), u=Sum("updated_count"))
    last_ok = OneCExchange.objects.filter(status__in=("ok", "partial")).first()
    silent_hours = _hours_since(last_ok.created_at if last_ok else None)

    ctx = {
        **admin.site.each_context(request),
        "title": "Журнал обмена с 1С",
        "rows": rows,
        "op": op,
        "status": status,
        "total": qs.count(),
        "page_size": PAGE_SIZE,
        "summary": {
            "runs": d.count(),
            "created": agg["c"] or 0,
            "updated": agg["u"] or 0,
            "errors": d.filter(status="error").count(),
        },
        "n_categories": OneCExchange.objects.filter(operation="categories").count(),
        "n_catalog": OneCExchange.objects.filter(operation="catalog").count(),
        "n_prices": OneCExchange.objects.filter(operation="prices").count(),
        "n_orders": OneCExchange.objects.filter(
            operation__in=("orders", "order-status")).count(),
        "enabled": bool((getattr(settings, "INTEGRATION_1C_TOKEN", "") or "").strip()),
        "last_ok": _local(last_ok.created_at) if last_ok else "",
        # Тишина дольше суток — повод разбираться: со стороны сервера молчание 1С
        # и сломанный обмен выглядят одинаково.
        "silent": silent_hours is not None and silent_hours >= 24,
        "silent_hours": silent_hours,
        "never": last_ok is None,
    }
    return TemplateResponse(request, "admin/onec_log.html", ctx)
