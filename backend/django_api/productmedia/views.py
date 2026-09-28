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
import os
import re

from django.contrib import admin
from django.contrib.admin.views.decorators import staff_member_required
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.template.response import TemplateResponse
from django.urls import reverse

from catalog import photos as photolib
from catalog.models import Product, ProductPhoto
from common.uploads import prepare_image
from productmedia import processing, service, tasks
from productmedia.matching import _norm, match_folders_to_products
from productmedia.models import PhotoBatch, PhotoDetail, PhotoJob, PhotoPrompt
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


def _safe_name(name, ext, fallback):
    """Имя файла для хранилища: основа из имени клиента без опасных символов,
    расширение — по содержимому (клиентскому «.html» в хранилище не бывать)."""
    stem = os.path.splitext(os.path.basename(name or ""))[0]
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip(".-")[:60] or fallback
    return "%s.%s" % (stem, ext)


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
    # Тип — по содержимому с полным декодированием (D-37/D07): заголовок и имя шлёт клиент.
    # Дальше идёт копия без EXIF/GPS/XMP; archival — без потерь, её ещё обрабатывает ИИ.
    ext, clean, bad = prepare_image(photo, allowed={"jpg", "png", "webp"}, archival=True)
    if bad:
        return _err(bad)
    attach_as = request.POST.get("attach_as") or PhotoJob.ATTACH_GALLERY
    if attach_as == "detail":
        # Крупный план принта: не снимок витрины, а справка для генерации этого артикула.
        row = service.add_detail(batch, request.POST.get("article") or "", clean,
                                 _safe_name(photo.name, ext, "detail"))
        return JsonResponse({"ok": True, "detail": row.pk})
    if attach_as not in dict(PhotoJob.ATTACH_CHOICES):
        attach_as = PhotoJob.ATTACH_GALLERY
    job = service.intake(batch, [{
        "article": request.POST.get("article") or "",
        "content": clean, "filename": _safe_name(photo.name, ext, "source"),
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
    # Прогоны командой photo_test — технические проверки, не работа с товарами.
    for b in (PhotoBatch.objects.exclude(note=PhotoBatch.NOTE_TEST)
              .select_related("created_by").order_by("-created_at")[:20]):
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
        "prompts_link": reverse("photo_prompts"),
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
    else:
        # Технические прогоны photo_test на экран проверки не выносим: там исходник часто
        # не от этого товара, и случайное «Принять» повесило бы чужое фото на карточку.
        qs = qs.exclude(batch__note=PhotoBatch.NOTE_TEST)
    tab_counts = {k: qs.filter(status__in=v[0]).count() for k, v in SHOW.items()}
    qs = qs.filter(status__in=SHOW[show][0]).order_by("-updated_at")

    page = Paginator(qs.select_related("prompt"), PER_PAGE).get_page(request.GET.get("page"))

    # Крупные планы принтов для карточек страницы — одним запросом.
    details = {}
    for row in PhotoDetail.objects.filter(batch_id__in={j.batch_id for j in page}):
        details.setdefault((row.batch_id, _norm(row.article)), []).append(_url(row.image))

    items = []
    for j in page:
        p = j.product
        usage = j.usage if isinstance(j.usage, dict) else {}
        items.append({
            "id": j.pk, "article": j.article, "status": j.status,
            "status_label": j.get_status_display(),
            "name": (p.shop_title if p else "") or j.article,
            "color": _color(p), "attach": j.get_attach_as_display(),
            "attempts": j.attempts, "note": j.note, "error": j.error, "text": j.text,
            "source": _url(j.source), "result": _url(j.webp),
            "details": [u for u in details.get((j.batch_id, _norm(j.article)), []) if u],
            "prompt": ("версия #%s" % j.prompt_id) if j.prompt_id else "встроенный",
            "tokens": usage.get("total_tokens"),
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
        "prompts_link": reverse("photo_prompts"),
        "can_edit": _can_edit(request),
    })


# ── «Промты» ────────────────────────────────────────────────────────────────

def _prompt_action(request):
    if not can(request.user, TAB, LEVEL_EDIT):
        return _err("нет прав на правку промтов", 403)
    action = request.POST.get("action")
    user = request.user if request.user.is_authenticated else None
    if action == "save":
        track = request.POST.get("track")
        text = (request.POST.get("text") or "").strip()
        if track not in processing.TRACKS:
            return _err("неизвестный трек")
        if len(text) < 20:
            return _err("промт слишком короткий")
        row = PhotoPrompt.objects.create(track=track, text=text, created_by=user,
                                         comment=(request.POST.get("comment") or "")[:200])
    elif action == "restore":
        old = PhotoPrompt.objects.filter(pk=request.POST.get("id")).first()
        if old is None:
            return _err("версия не найдена", 404)
        row = PhotoPrompt.objects.create(track=old.track, text=old.text, created_by=user,
                                         comment="возврат к версии #%s" % old.pk)
    elif action == "reset":
        track = request.POST.get("track")
        if track not in processing.TRACKS:
            return _err("неизвестный трек")
        row = PhotoPrompt.objects.create(track=track, text=processing.TRACKS[track][0],
                                         created_by=user, comment="встроенный промт")
    else:
        return _err("неизвестное действие")
    StaffAudit.write(request, "фотопайплайн: промт %s → версия #%s" % (row.track, row.pk))
    return JsonResponse({"ok": True, "id": row.pk})


@staff_member_required
@tab_required(TAB)
def photo_prompts(request):
    if request.method == "POST":
        return _prompt_action(request)

    tracks = []
    for code, label in PhotoBatch.TRACK_CHOICES:
        active = PhotoPrompt.active(code)
        history = list(PhotoPrompt.objects.filter(track=code)
                       .select_related("created_by")[:10])
        tracks.append({
            "code": code, "label": label,
            "text": active.text if active else processing.TRACKS[code][0],
            "active": active,
            "history": [{
                "id": h.pk, "when": h.created_at, "comment": h.comment,
                "who": h.created_by.get_username() if h.created_by else "",
                "current": active is not None and h.pk == active.pk,
            } for h in history],
        })

    # Замечания проверяющих — из них видно, что стоит поправить в промте.
    notes = []
    for j in (PhotoJob.objects.exclude(note="").select_related("product")
              .order_by("-reviewed_at", "-updated_at")[:30]):
        notes.append({"when": j.reviewed_at or j.updated_at, "article": j.article,
                      "status": j.get_status_display(), "note": j.note,
                      "link": reverse("photo_review") + "?show=%s" % (
                          "rejected" if j.status == PhotoJob.STATUS_REJECTED else "review")})

    return TemplateResponse(request, "admin/photo_prompts.html", {
        **admin.site.each_context(request),
        "title": "Промты фотопайплайна",
        "tracks": tracks,
        "notes": notes,
        "pipeline_link": reverse("photo_pipeline"),
        "review_link": reverse("photo_review"),
        "can_edit": _can_edit(request),
    })


# ── «Как снимать» — ТЗ для фотографа ───────────────────────────────────────

@staff_member_required
@tab_required(TAB)
def photo_guide(request):
    """Памятка работнику: что снимать, как называть папки и файлы, что считать браком.

    Лежит рядом с загрузкой (просьба владельца 27.09), чтобы у того, кто снимает и
    загружает, правила были под рукой.
    """
    return TemplateResponse(request, "admin/photo_guide.html", {
        **admin.site.each_context(request),
        "title": "Как снимать товары",
        "pipeline_link": reverse("photo_pipeline"),
        "review_link": reverse("photo_review"),
        "prompts_link": reverse("photo_prompts"),
    })
