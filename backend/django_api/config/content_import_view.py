"""Страница «Импорт контента»: фото и описания с сайтов брендов — после проверки человеком.

Зачем (24.11.2026). Фото есть у четверти карточек, описаний нет ни у одной. Владелец
поручил собрать их с официальных сайтов брендов (BMAI, ANTA, STAW) по артикулам и
написать описания по единому паспорту. Сборщик (скрипт вне сервера) кладёт пакет в
хранилище: `content-import/<пакет>/manifest.json` + картинки рядом. Здесь пакет
показывается целиком — что и в какую карточку ляжет, — и только по кнопке человека
попадает на витрину. Ошибка сопоставления иначе вывела бы чужую модель.

Правила загрузки:
- цвет определяет СЕРВЕР по артикулу цвета из 1С (XRMM002-4 → позиции этого
  артикула → их цвет), а не по названию цвета с сайта бренда: там оно по-китайски;
- фото добавляются только туда, где у модели и цвета снимков ещё нет — работу
  сотрудников не перетираем;
- описание пишется только в пустое поле и помечается «правлено владельцем», чтобы
  следующая выгрузка 1С его не стёрла.

Формат пакета:
    {"title": "...", "items": [{"article": "XRMM002", "description": "...",
      "source": "https://...", "missing": ["нет веса"],
      "photos": {"XRMM002-4": ["https://storage.yandexcloud.net/mata-media/content-import/..."]}}]}

    STAW: «"prefix": true» (позиции модели — по началу артикула) и ключи фото вида
    «26SADT003|Горчичный» (артикул модели + цвет из 1С).
"""
import json
import re
import secrets
import urllib.request

from django.conf import settings
from django.contrib import admin
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Q
from django.http import JsonResponse
from django.template.response import TemplateResponse

from catalog import photos as photolib
from catalog.models import Product, ProductPhoto
from staff.access import can, tab_required
from staff.models import LEVEL_EDIT, StaffAudit

# Брать пакеты можно ТОЛЬКО из нашего хранилища: иначе страница стала бы прокси на
# любой адрес (SSRF), а в карточки попало бы что угодно.
DEFAULT_PREFIX = "https://storage.yandexcloud.net/mata-media/content-import/"
BATCH_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,60}$")
MAX_IMAGE_BYTES = 15 * 1024 * 1024
TIMEOUT = 30


def _prefix() -> str:
    return getattr(settings, "CONTENT_IMPORT_PREFIX", DEFAULT_PREFIX)


def _fetch(url: str, limit: int) -> bytes:
    if not url.startswith(_prefix()) or ".." in url or "@" in url or "\\" in url:
        raise ValueError("адрес вне хранилища пакетов")
    with urllib.request.urlopen(url, timeout=TIMEOUT) as resp:   # noqa: S310 — адрес проверен выше
        data = resp.read(limit + 1)
    if len(data) > limit:
        raise ValueError("файл слишком большой")
    return data


def load_manifest(batch: str) -> dict:
    if not BATCH_RE.match(batch or ""):
        raise ValueError("неверное имя пакета")
    return json.loads(_fetch(f"{_prefix()}{batch}/manifest.json", 20 * 1024 * 1024))


def load_index() -> list:
    """Список пакетов (index.json рядом с пакетами); нет файла — пустой список."""
    try:
        return json.loads(_fetch(f"{_prefix()}index.json", 1024 * 1024)).get("batches", [])
    except Exception:
        return []


def _positions(code: str):
    """Позиции 1С с этим артикулом: сам артикул или он же с хвостом (-цвет, -размер)."""
    code = (code or "").strip()
    if not code:
        return Product.objects.none()
    return Product.objects.filter(Q(article__iexact=code) | Q(article__istartswith=code + "-"))


def _model_positions(item: dict):
    """Позиции модели пункта. У STAW код цвета вписан в артикул без дефиса
    (26SADT0031850), поэтому пункт может попросить искать по началу артикула."""
    article = (item.get("article") or "").strip()
    if item.get("prefix") and article:
        return Product.objects.filter(article__istartswith=article)
    return _positions(article)


def _color_positions(item: dict, code: str):
    """Позиции цвета: «XRMM002-4» — по артикулу цвета; «26SADT003|Горчичный» — по
    артикулу модели и названию цвета из 1С (когда код цвета в артикуле нам неизвестен)."""
    if "|" not in code:
        return list(_positions(code))
    article, color = (part.strip() for part in code.split("|", 1))
    want = photolib.norm_color(color)
    rows = Product.objects.filter(article__istartswith=article) if article else []
    return [p for p in rows
            if any(photolib.norm_color(str(c)) == want for c in (p.colors or []))]


def _first_color(products) -> str:
    for p in products:
        for c in p.colors or []:
            if str(c).strip():
                return str(c).strip()
    return ""


def resolve(item: dict) -> dict:
    """Куда ляжет пункт пакета: модели, цвета, что уже есть. Ничего не меняет."""
    article = (item.get("article") or "").strip()
    base = list(_model_positions(item))
    models = {}
    for p in base:
        key = p.shop_model_key or p.id
        m = models.setdefault(key, {"key": key, "name": p.shop_title, "positions": 0,
                                    "empty_desc": 0})
        m["positions"] += 1
        if not (p.description or "").strip():
            m["empty_desc"] += 1

    have = set()
    if models:
        for row in ProductPhoto.objects.filter(model_key__in=list(models)):
            have.add((row.model_key, photolib.norm_color(row.color)))

    colors = []
    for code, urls in (item.get("photos") or {}).items():
        rows = _color_positions(item, code)
        entry = {"code": code, "urls": list(urls or []), "color": "", "model": "",
                 "state": "none"}
        if not rows:
            entry["state"] = "none"          # такого артикула цвета у нас нет
        else:
            entry["color"] = _first_color(rows)
            entry["model"] = rows[0].shop_model_key or rows[0].id
            busy = (entry["model"], photolib.norm_color(entry["color"])) in have
            entry["state"] = "has" if busy else "fill"
        colors.append(entry)

    return {
        "article": article,
        "prefix": bool(item.get("prefix")),
        "description": item.get("description") or "",
        "source": item.get("source") or "",
        "missing": list(item.get("missing") or []),
        "models": list(models.values()),
        "colors": colors,
        "desc_state": ("none" if not models else
                       "fill" if any(m["empty_desc"] for m in models.values()) else "has"),
    }


def apply_item(request, item: dict) -> dict:
    """Загрузить один пункт пакета. Только в пустое: фото — где нет снимков, описание —
    где поле пустое. Возвращает, что сделано."""
    plan = resolve(item)
    added, skipped, errors = 0, 0, []
    for c in plan["colors"]:
        if c["state"] != "fill" or not c["urls"]:
            skipped += 1 if c["state"] == "has" else 0
            continue
        free = ProductPhoto.MAX_PER_COLOR
        for url in c["urls"][:free]:
            try:
                data = _fetch(url, MAX_IMAGE_BYTES)
                photolib.store_photo(c["model"], c["color"], data, secrets.token_hex(8))
                added += 1
            except Exception as e:      # битая картинка — не валим весь пункт
                errors.append(f"{c['code']}: {e}")

    described = 0
    text = plan["description"].strip()
    if text:
        for p in _model_positions(item):
            if (p.description or "").strip():
                continue
            p.description = text
            p.set_override("description", True)
            p.save(update_fields=["description", "overrides"])
            described += 1

    if added or described:
        StaffAudit.write(request, f"импорт контента {plan['article']}: фото {added}, "
                                  f"описаний {described}")
    return {"ok": not errors, "photos": added, "skipped": skipped,
            "described": described, "errors": errors[:5]}


@staff_member_required
@tab_required("content_import")
def content_import(request):
    batch = (request.POST.get("batch") or request.GET.get("batch") or "").strip()

    if request.method == "POST":
        if not can(request.user, "content_import", LEVEL_EDIT):
            return JsonResponse({"ok": False, "error": "нет права загружать"}, status=403)
        try:
            manifest = load_manifest(batch)
            idx = int(request.POST.get("item", "-1"))
            item = manifest["items"][idx]
        except (ValueError, KeyError, IndexError, TypeError) as e:
            return JsonResponse({"ok": False, "error": f"пакет не прочитан: {e}"}, status=400)
        except Exception:
            return JsonResponse({"ok": False, "error": "хранилище не ответило"}, status=502)
        return JsonResponse(apply_item(request, item))

    ctx = {**admin.site.each_context(request), "title": "Импорт контента",
           "batch": batch, "batches": load_index(), "rows": [], "error": ""}
    if batch:
        try:
            manifest = load_manifest(batch)
        except Exception as e:
            ctx["error"] = f"Пакет «{batch}» не открылся: {e}"
        else:
            rows = [resolve(item) for item in manifest.get("items", [])]
            for i, r in enumerate(rows):
                r["index"] = i
                r["ready"] = r["desc_state"] == "fill" or any(c["state"] == "fill"
                                                              for c in r["colors"])
            ctx.update({
                "manifest_title": manifest.get("title") or batch,
                "rows": rows,
                "total": len(rows),
                "ready": sum(1 for r in rows if r["ready"]),
                "not_found": sum(1 for r in rows if not r["models"]),
                "photo_colors": sum(1 for r in rows for c in r["colors"] if c["state"] == "fill"),
                "desc_count": sum(1 for r in rows if r["desc_state"] == "fill"),
            })
    return TemplateResponse(request, "admin/content_import.html", ctx)
