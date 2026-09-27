"""Экраны фотопайплайна в админке: загрузка партии и проверка результатов.

«Фотопайплайн» — работник выбирает папки (имя папки = артикул), видит, какая папка к
какому товару привязалась, и жмёт «Загрузить и обработать». Файлы уходят по одному
(браузер заранее уменьшает их до 2560 px — быстро и не упирается в лимит nginx), затем
генерация идёт в фоне (Celery).

«Проверка» — исходник и результат рядом; «Принять» выкладывает снимок на витрину,
«Переделать» с замечанием отправляет на новую генерацию (замечание уходит в промт),
«Отклонить» — брак. Без «Принять» на витрину ничего не попадает.
"""
import json

from django.contrib import admin
from django.contrib.admin.views.decorators import staff_member_required
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.template.response import TemplateResponse
from django.urls import reverse

from catalog import photos as photolib
from catalog.models import Product, ProductPhoto
from productmedia import service, tasks
from productmedia.matching import match_folders_to_products
from productmedia.models import PhotoBatch, PhotoJob
from staff.access import can, tab_required
from staff.models import LEVEL_EDIT, StaffAudit

TAB = "photo_pipeline"
MAX_BYTES = 8 * 1024 * 1024          # браузер ужимает до 2560 px — в 8 МБ влезает с запасом
ALLOWED = {"image/jpeg", "image/png", "image/webp"}
PER_PAGE = 24


def _err(text, status=400):
    return JsonResponse({"ok": False, "error": text}, status=status)


def _can_edit(request):
    return can(request.user, TAB, LEVEL_EDIT)


def _url(field):
    try:
        return field.url if field else ""
    except Exception:                            # noqa: BLE001 — нет файла в хранилище
        return ""


def _color(product):
    colors = (product.colors or []) if product else []
    return colors[0] if colors else ""


# ── «Фотопайплайн»: загрузка партии ─────────────────────────────────────────

def _match(request):
    """Какие папки нашли свой товар: имя, цвет, сколько мест в галерее цвета уже занято."""
    try:
        folders = json.loads(request.POST.get("folders") or "[]")
    except ValueError:
        return _err("не удалось прочитать список папок")
    res = match_folders_to_products([str(f) for f in folders][:500])

    ids = [m["productId"] for m in res["matched"]]
    products = {p.pk: p for p in Product.objects.filter(pk__in=ids)}
    keys = {(p.shop_model_key or str(p.pk)) for p in products.values()}
    have = photolib.by_model(keys)

    for m in res["matched"]:
        p = products.get(m["productId"])
        color = _color(p)
        key = (p.shop_model_key or str(p.pk)) if p else ""
        used = len(photolib.pick(have.get(key), color)) if p else 0
        m.update({"color": color, "used": used, "max": ProductPhoto.MAX_PER_COLOR})
    return JsonResponse({"ok": True, **res})


def _create(request):
    track = request.POST.get("track") or PhotoBatch.TRACK_CATALOG
    if track not in dict(PhotoBatch.TRACK_CHOICES):
        return _err("неизвестный трек")
    batch = PhotoBatch.objects.create(
        track=track, created_by=request.user if request.user.is_authenticated else None,
        note=(request.POST.get("note") or "")[:200])
    StaffAudit.write(request, "фотопайплайн: новая партия #%s" % batch.pk)
    return JsonResponse({"ok": True, "batch": batch.pk})


def _upload(request):
    batch = PhotoBatch.objects.filter(pk=request.POST.get("batch")).first()
    if batch is None:
        return _err("партия не найдена", 404)
    photo = request.FILES.get("photo")
    if photo is None:
        return _err("файл не пришёл")
    if photo.size > MAX_BYTES:
        return _err("файл больше %d МБ" % (MAX_BYTES // 1024 // 1024))
    if photo.content_type not in ALLOWED:
        return _err("нужен JPEG, PNG или WEBP")
    attach_as = request.POST.get("attach_as") or PhotoJob.ATTACH_GALLERY
    if attach_as not in dict(PhotoJob.ATTACH_CHOICES):
        attach_as = PhotoJob.ATTACH_GALLERY
    job = service.intake(batch, [{
        "article": request.POST.get("article") or "",
        "content": photo, "filename": photo.name or "source.jpg",
        "attach_as": attach_as, "text": request.POST.get("text") or "",
    }])[0]
    return JsonResponse({"ok": True, "job": job.pk, "status": job.status})


def _start(request):
    batch = PhotoBatch.objects.filter(pk=request.POST.get("batch")).first()
    if batch is None:
        return _err("партия не найдена", 404)
    tasks.process_batch.delay(batch.pk)
    StaffAudit.write(request, "фотопайплайн: запуск партии #%s" % batch.pk)
    return JsonResponse({"ok": True, "review": reverse("photo_review") + "?batch=%s" % batch.pk})


@staff_member_required
@tab_required(TAB)
def photo_pipeline(request):
    if request.method == "POST":
        if not _can_edit(request):
            return _err("нет прав на загрузку", 403)
        action = request.POST.get("action")
        if action == "match":
            return _match(request)
        if action == "create":
            return _create(request)
        if action == "upload":
            return _upload(request)
        if action == "start":
            return _start(request)
        return _err("неизвестное действие")

    batches = []
    for b in PhotoBatch.objects.select_related("created_by").order_by("-created_at")[:20]:
        c = service.counts(b)
        batches.append({
            "id": b.pk, "created_at": b.created_at, "track": b.get_track_display(),
            "who": b.created_by.get_username() if b.created_by else "",
            "total": sum(c.values()), "c": c,
        })
    return TemplateResponse(request, "admin/photo_pipeline.html", {
        **admin.site.each_context(request),
        "title": "Фотопайплайн",
        "batches": batches,
        "tracks": PhotoBatch.TRACK_CHOICES,
        "review_link": reverse("photo_review"),
        "can_edit": _can_edit(request),
        "max_mb": MAX_BYTES // 1024 // 1024,
    })


# ── «Проверка» ──────────────────────────────────────────────────────────────

SHOW = {
    "review": ([PhotoJob.STATUS_REVIEW], "На проверке"),
    "work": ([PhotoJob.STATUS_PENDING, PhotoJob.STATUS_PROCESSING], "В работе"),
    "failed": ([PhotoJob.STATUS_FAILED], "Ошибки"),
    "done": ([PhotoJob.STATUS_DONE], "На витрине"),
    "rejected": ([PhotoJob.STATUS_REJECTED], "Отклонено"),
}


def _decide(request):
    if not _can_edit(request):
        return _err("нет прав на проверку", 403)
    job = PhotoJob.objects.select_related("product").filter(pk=request.POST.get("job")).first()
    if job is None:
        return _err("снимок не найден", 404)
    action = request.POST.get("action")
    note = (request.POST.get("note") or "").strip()
    label = job.article or job.pk

    if action == "approve":
        err = service.approve(job, request.user)
        if err:
            return _err(err)
        StaffAudit.write(request, "фотопайплайн: принят снимок %s" % label)
    elif action in ("redo", "retry"):
        if job.status not in (PhotoJob.STATUS_REVIEW, PhotoJob.STATUS_FAILED,
                              PhotoJob.STATUS_REJECTED):
            return _err("снимок уже в работе")
        service.redo(job, note or (job.note if action == "retry" else ""), request.user)
        tasks.regenerate_job.delay(job.pk)
        StaffAudit.write(request, "фотопайплайн: переделать %s (%s)" % (label, note[:80]))
    elif action == "reject":
        service.reject(job, note, request.user)
        StaffAudit.write(request, "фотопайплайн: отклонён %s (%s)" % (label, note[:80]))
    else:
        return _err("неизвестное действие")
    job.refresh_from_db()
    return JsonResponse({"ok": True, "status": job.status,
                         "label": job.get_status_display()})


@staff_member_required
@tab_required(TAB)
def photo_review(request):
    if request.method == "POST":
        return _decide(request)

    show = request.GET.get("show") if request.GET.get("show") in SHOW else "review"
    batch_id = request.GET.get("batch") or ""
    qs = PhotoJob.objects.select_related("product", "batch")
    if batch_id.isdigit():
        qs = qs.filter(batch_id=int(batch_id))
    tab_counts = {k: qs.filter(status__in=v[0]).count() for k, v in SHOW.items()}
    qs = qs.filter(status__in=SHOW[show][0]).order_by("-updated_at")

    page = Paginator(qs, PER_PAGE).get_page(request.GET.get("page"))
    items = []
    for j in page:
        p = j.product
        items.append({
            "id": j.pk, "article": j.article, "status": j.status,
            "status_label": j.get_status_display(),
            "name": (p.shop_title if p else "") or j.article,
            "color": _color(p), "attach": j.get_attach_as_display(),
            "attempts": j.attempts, "note": j.note, "error": j.error, "text": j.text,
            "source": _url(j.source), "result": _url(j.webp),
            "batch": j.batch_id,
        })
    return TemplateResponse(request, "admin/photo_review.html", {
        **admin.site.each_context(request),
        "title": "Проверка фото",
        "items": items,
        "page": page,
        "show": show,
        "tabs": [(k, v[1], tab_counts[k]) for k, v in SHOW.items()],
        "batch": batch_id if batch_id.isdigit() else "",
        "pipeline_link": reverse("photo_pipeline"),
        "can_edit": _can_edit(request),
    })
