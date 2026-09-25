"""Кастомные страницы админки (вне ModelAdmin): «Конструктор» — live-превью сайта/
приложения + правка (раздельный порядок по площадкам) + публикация с подтверждением.
Отдельные страницы «Превью» убраны — конструктор их заменяет."""
import json

from django.conf import settings
from django.contrib import admin
from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from staff.access import tab_required
from staff.models import LEVEL_EDIT


# ── Конструктор витрины (мерчендайзинг) ──────────────────────────────────────
# Данные товара ОБЩИЕ (одна запись), а порядок раскладки РАЗДЕЛЬНЫЙ по площадкам
# (sort_site / sort_app). Правка товара пишет в центральный Product → меняется везде.

_PLATFORM_FIELD = {"site": "sort_site", "app": "sort_app"}


# Поля, которые ведёт 1С и которые владелец может перебить в Конструкторе (D-62).
# Ключ — как в JSON конструктора и в Product.OVERRIDABLE, значение — поле модели.
_OVERRIDABLE = {"price": "price", "oldPrice": "old_price",
                "description": "description", "sizes": "sizes"}


def _norm(field, value):
    """Привести значение к сравнимому виду: 1С шлёт цену числом, форма — строкой."""
    if field in ("price", "oldPrice"):
        if value in (None, "", 0, "0"):
            return None if field == "oldPrice" else 0.0
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    if field == "sizes":
        return [str(x).strip() for x in (value or []) if str(x).strip()]
    return str(value or "")


def _onec_json(p):
    """Что показать в Конструкторе рядом с полями: значение 1С и след правки владельца."""
    src = p.from_1c or {}
    from_1c = {f: src[f] for f in _OVERRIDABLE if f in src}
    return {
        "linked": bool(p.external_id or p.article),
        "article": p.article or "",
        "externalId": p.external_id or "",
        "stock": p.stock_count,
        "activeIn1c": p.is_active_1c,
        "overrides": [f for f in (p.overrides or []) if f in _OVERRIDABLE],
        "from1c": from_1c,
    }


def _merch_json(p):
    return {
        "id": p.id,
        "name": p.name,
        "imageUrl": p.network_image_url(),
        "price": p.price,
        "oldPrice": p.old_price,
        "inStock": p.in_stock,
        "isPublished": p.is_published,
        "isFeatured": p.is_featured,
        "description": p.description,
        "sizes": p.sizes or [],
        "categoryId": p.category_id,
        "onec": _onec_json(p),
    }


@staff_member_required
@tab_required("merch")
def merch_console(request):
    """«Конструктор витрины»: перетаскивание порядка товаров раздельно для сайта и
    приложения + правка товара (цена/старая цена/описание/наличие/публикация) прямо в
    превью. Данные общие, порядок раздельный."""
    site = getattr(settings, "SITE_PREVIEW_URL", "http://localhost:5577").rstrip("/")
    app = getattr(settings, "APP_PREVIEW_URL", "http://localhost:5578").rstrip("/")
    # APP_PREVIEW_URL на проде указывает ПРЯМО на index.html web-сборки в S3
    # (объектное хранилище не отдаёт index.html по «каталогу» без website-hosting),
    # тогда слэш в конце не добавляем. В dev это http://localhost:5578 → +"/".
    app_url = app if app.endswith(".html") else app + "/"
    return render(request, "admin/merch_console.html", {
        "site_preview_url": site + "/?preview=1&platform=site",
        "app_preview_url": app_url,
    })


@staff_member_required
@tab_required("merch")
@require_http_methods(["GET"])
def merch_products(request):
    """Список товаров для конструктора в порядке выбранной площадки."""
    from catalog.models import Product

    platform = (request.GET.get("platform") or "site").strip().lower()
    field = _PLATFORM_FIELD.get(platform, "sort")
    qs = Product.objects.all().order_by(field, "sort", "id")
    return JsonResponse({"products": [_merch_json(p) for p in qs]})


@staff_member_required
@tab_required("merch", LEVEL_EDIT)
@require_http_methods(["POST"])
def merch_reorder(request):
    """Сохранить новый порядок для площадки: {platform, order:[id,...]} → sort_site/app."""
    from catalog.models import Product

    try:
        data = json.loads(request.body or b"{}")
    except ValueError:
        return JsonResponse({"detail": "Некорректный JSON"}, status=400)
    field = _PLATFORM_FIELD.get((data.get("platform") or "").strip().lower())
    if not field:
        return JsonResponse({"detail": "Неизвестная площадка"}, status=400)
    order = data.get("order") or []
    for i, pid in enumerate(order):
        Product.objects.filter(id=pid).update(**{field: i})
    return JsonResponse({"ok": True, "count": len(order)})


@staff_member_required
@tab_required("merch", LEVEL_EDIT)
@require_http_methods(["POST"])
def merch_product(request, pid):
    """Правка ЦЕНТРАЛЬНОГО товара (меняется на всех площадках)."""
    from catalog.models import Product

    p = Product.objects.filter(id=pid).first()
    if not p:
        return JsonResponse({"detail": "Товар не найден"}, status=404)
    try:
        d = json.loads(request.body or b"{}")
    except ValueError:
        return JsonResponse({"detail": "Некорректный JSON"}, status=400)
    # Значения ДО правки — чтобы отличить «владелец изменил» от «просто переслал форму»:
    # конструктор отправляет все поля разом, даже нетронутые.
    before = {f: _norm(f, getattr(p, m)) for f, m in _OVERRIDABLE.items()}
    if "price" in d:
        try:
            p.price = float(d["price"])
        except (TypeError, ValueError):
            return JsonResponse({"detail": "Некорректная цена"}, status=400)
    if "oldPrice" in d:
        v = d["oldPrice"]
        try:
            p.old_price = float(v) if v not in (None, "", 0, "0") else None
        except (TypeError, ValueError):
            return JsonResponse({"detail": "Некорректная старая цена"}, status=400)
    if "description" in d:
        p.description = str(d["description"] or "")
    if "inStock" in d:
        p.in_stock = bool(d["inStock"])
    if "isPublished" in d:
        p.is_published = bool(d["isPublished"])
    if "isFeatured" in d:
        p.is_featured = bool(d["isFeatured"])
    if isinstance(d.get("sizes"), list):
        p.sizes = [str(s).strip() for s in d["sizes"] if str(s).strip()]
    _sync_overrides(p, d, before)
    p.save()
    return JsonResponse({"ok": True, "product": _merch_json(p)})


def _sync_overrides(p, incoming: dict, before: dict) -> None:
    """Правка поля в Конструкторе = «веду сам», возврат к значению 1С = «веди из 1С».

    Отдельной кнопки-переключателя нет намеренно: владелец думает про цену, а не про
    режим поля. Поставил своё — 1С это поле больше не трогает; вернул как в 1С —
    обновления снова приходят автоматически.
    """
    if not (p.from_1c or p.external_id or p.article):
        return  # товар не из 1С — переопределять нечего
    src = p.from_1c or {}
    for field, model_field in _OVERRIDABLE.items():
        if field not in incoming:
            continue
        now = _norm(field, getattr(p, model_field))
        if field in src and now == _norm(field, src[field]):
            p.set_override(field, False)
        elif now != before.get(field):
            p.set_override(field, True)


# ── Контент сайта (мини-CMS): тексты и фото шапки/hero/секций ────────────────

def _delete_media_url(url):
    """Удалить файл из хранилища по его /media/-URL. Чистим ТОЛЬКО загрузки (uploads/…),
    чтобы случайно не снести чужое. Тихо игнорируем ошибки (уборка не должна ронять запрос)."""
    from django.conf import settings
    from django.core.files.storage import default_storage
    try:
        u = (url or "").split("?")[0].strip()
        if not u:
            return
        prefix = settings.MEDIA_URL or "/media/"
        if u.startswith(prefix):
            name = u[len(prefix):]
        elif "/media/" in u:
            name = u.split("/media/", 1)[1]
        else:
            return
        name = name.lstrip("/")
        if not name.startswith("uploads/"):
            return  # только наши загрузки
        if default_storage.exists(name):
            default_storage.delete(name)
    except Exception:
        pass


@staff_member_required
@tab_required("merch", LEVEL_EDIT)
@require_http_methods(["POST"])
def merch_site_content(request):
    """Правка текста блока сайта: {key, value} → SiteContent (публикуется на сайт)."""
    from catalog.models import SiteContent

    try:
        d = json.loads(request.body or b"{}")
    except ValueError:
        return JsonResponse({"detail": "Некорректный JSON"}, status=400)
    key = (d.get("key") or "").strip()[:80]
    if not key:
        return JsonResponse({"detail": "Нет ключа"}, status=400)
    obj, _ = SiteContent.objects.get_or_create(key=key)
    if d.get("clearImage"):
        # «Удалить фотографию» в окне «Фон»: стереть хранимое фото (bg.<key>),
        # чтобы оно не «возвращалось» при переоткрытии. Значение не трогаем.
        if obj.image:
            obj.image.delete(save=False)
        obj.image = None
    else:
        new_val = str(d.get("value") or "")
        # Видео на фон (bgvid.<key>): при СМЕНЕ или ОЧИСТКЕ ссылки удаляем старый
        # видеофайл с диска — иначе он остаётся «сиротой».
        if key.startswith("bgvid.") and obj.value and obj.value != new_val:
            _delete_media_url(obj.value)
        obj.value = new_val
    obj.save()
    return JsonResponse({"ok": True, "content": {key: obj.to_json()}})


@staff_member_required
@tab_required("merch", LEVEL_EDIT)
@require_http_methods(["POST"])
def merch_site_image(request):
    """Замена фото блока сайта: multipart image + key → SiteContent.image."""
    from catalog.models import SiteContent

    key = (request.POST.get("key") or "").strip()[:80]
    if not key:
        return JsonResponse({"detail": "Нет ключа"}, status=400)
    f = request.FILES.get("image")
    if not f:
        return JsonResponse({"detail": "Нет файла"}, status=400)
    if f.size > 40 * 1024 * 1024:
        return JsonResponse({"detail": "Файл слишком большой (макс 40 МБ)"}, status=400)
    if not (f.content_type or "").startswith("image/"):
        return JsonResponse({"detail": "Нужен файл-изображение"}, status=400)
    obj, _ = SiteContent.objects.get_or_create(key=key)
    if obj.image:
        try:
            obj.image.delete(save=False)   # убрать старый файл при замене (не копить сирот)
        except Exception:
            pass
    obj.image = _webify_image(f)   # даунскейл больших фото + пережатие → быстрый старт
    obj.save()
    return JsonResponse({"ok": True, "content": {key: obj.to_json()}})


# Оптимизация загружаемых фото для web: большие камерные снимки (5000×3500, 15+ МБ)
# грузятся на сайте секундами. Даунскейлим до 2560px по длинной стороне (ретина-качество
# для героя/секций) и пережимаем: JPEG q85 (без альфы) / PNG (с прозрачностью). Загружать
# можно крупные (лимит 40 МБ) — на сайт уходит лёгкая версия. Ошибка/нет Pillow → оригинал.
_IMG_MAXDIM = 2560


def _webify_image(f):
    try:
        import io

        from django.core.files.base import ContentFile
        from PIL import Image, ImageOps

        f.seek(0)
        img = Image.open(f)
        img = ImageOps.exif_transpose(img)  # ориентация с телефона
        has_alpha = img.mode in ("RGBA", "LA") or (
            img.mode == "P" and "transparency" in img.info
        )
        w, h = img.size
        scale = min(1.0, _IMG_MAXDIM / float(max(w, h)))
        if scale < 1.0:
            img = img.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)
        buf = io.BytesIO()
        base = (getattr(f, "name", None) or "image").rsplit(".", 1)[0]
        if has_alpha:
            img.save(buf, format="PNG", optimize=True)
            name = base + "_web.png"
        else:
            img.convert("RGB").save(buf, format="JPEG", quality=85, optimize=True, progressive=True)
            name = base + "_web.jpg"
        buf.seek(0)
        return ContentFile(buf.read(), name=name)
    except Exception:
        try:
            f.seek(0)
        except Exception:
            pass
        return f


@staff_member_required
@tab_required("merch", LEVEL_EDIT)
@require_http_methods(["POST"])
def merch_site_video(request):
    """Загрузка короткого видео на фон блока: multipart video → сохраняем в
    хранилище и возвращаем URL. URL кладётся фронтом в bgvid.<key> через /site-content
    (как обычная ссылка) — отдельная модель/миграция не нужны."""
    from django.core.files.storage import default_storage
    from django.utils.text import get_valid_filename

    f = request.FILES.get("video")
    if not f:
        return JsonResponse({"detail": "Нет файла"}, status=400)
    if f.size > 200 * 1024 * 1024:
        return JsonResponse({"detail": "Файл слишком большой (макс 200 МБ)"}, status=400)
    ct = (f.content_type or "").lower()
    name = (f.name or "").lower()
    if not (ct.startswith("video/") or name.endswith((".mp4", ".webm", ".ogg", ".mov"))):
        return JsonResponse({"detail": "Нужен видео-файл (.mp4/.webm)"}, status=400)
    safe = get_valid_filename(f.name or "clip.mp4") or "clip.mp4"
    saved = default_storage.save("uploads/site-video/" + safe, f)
    # Качество (управляет владелец при загрузке): web — лёгкое для сайта; high — 1080p;
    # original — без сжатия (4K, полное качество, но грузится дольше).
    quality = (request.POST.get("quality") or "web").lower()
    if quality != "original":
        web = _webify_video(saved, quality)
        if web:
            saved = web
        elif f.size > _HEAVY_VIDEO_BYTES:
            # Сжать не вышло, а исходник тяжёлый. Молча отдать его — значит получить
            # страницу, которая «жёстко тормозит у всех»: ровно это и случилось с
            # роликом на 100 МБ в окне входа. Лучше честный отказ.
            try:
                default_storage.delete(saved)
            except Exception:
                pass
            return JsonResponse({
                "detail": "Не удалось сжать видео, а исходник слишком тяжёлый "
                          "(%d МБ). Такой файл будет тормозить у всех. Сожмите ролик "
                          "примерно до %d МБ или загрузите с качеством «оригинал», "
                          "если это осознанное решение."
                          % (f.size // 1024 // 1024, _HEAVY_VIDEO_BYTES // 1024 // 1024),
            }, status=400)
    return JsonResponse({"ok": True, "url": default_storage.url(saved)})


# Пресеты сжатия: макс. сторона (px) и CRF (меньше = лучше качество/больше вес).
_VIDEO_PRESETS = {"web": ("1280", "30"), "high": ("1920", "24")}

# Выше этого веса несжатый ролик на фон не пускаем: браузер тянет фоновое видео
# целиком, и стомегабайтный файл кладёт страницу на любом устройстве.
_HEAVY_VIDEO_BYTES = 20 * 1024 * 1024


def _webify_video(saved, quality="web"):
    """Транскод фонового видео в web-формат по пресету качества (web/high).

    Камерные ролики огромны (80–100 МБ, 4K): браузер тянет их целиком и захлёбывается
    на декодировании. Делаем H.264, ≤maxdim, без звука, faststart.

    Работает и с локальным диском, и с облачным хранилищем. Раньше — только с диском:
    на S3 `default_storage.path()` бросает NotImplementedError, и сжатие тихо
    пропускалось, а на сайт уходил стомегабайтный исходник. Молчаливое «ничего не
    делаем» на проде — худший из вариантов, поэтому теперь качаем во временный файл.

    Возвращает имя web-версии либо None (тогда остаётся оригинал).
    """
    import os
    import shutil
    import subprocess
    import tempfile

    from django.core.files.base import File
    from django.core.files.storage import default_storage

    maxdim, crf = _VIDEO_PRESETS.get(quality, _VIDEO_PRESETS["web"])
    try:
        import imageio_ffmpeg
        ff = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None

    tmpdir = tempfile.mkdtemp(prefix="mata-video-")
    src = os.path.join(tmpdir, "src" + (os.path.splitext(saved)[1] or ".mp4"))
    out = os.path.join(tmpdir, "web.mp4")
    scale = ("scale=w=%s:h=%s:force_original_aspect_ratio=decrease:force_divisible_by=2"
             % (maxdim, maxdim))
    try:
        # Исходник — из хранилища, каким бы оно ни было (диск, S3).
        with default_storage.open(saved, "rb") as fh, open(src, "wb") as dst:
            shutil.copyfileobj(fh, dst)
        subprocess.run(
            [ff, "-y", "-i", src, "-vf", scale,
             "-c:v", "libx264", "-crf", crf, "-preset", "veryfast", "-pix_fmt", "yuv420p",
             "-an", "-movflags", "+faststart", out],
            check=True, timeout=900, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        if not os.path.exists(out) or os.path.getsize(out) == 0:
            return None
        with open(out, "rb") as fh:
            web_name = default_storage.save(
                os.path.splitext(saved)[0] + "_web.mp4", File(fh))
    except Exception:
        return None
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    try:
        default_storage.delete(saved)  # оригинал-тяжеловес больше не нужен
    except Exception:
        pass
    _video_poster(web_name)
    return web_name


def _video_poster(video_name):
    """Первый кадр видео — картинкой рядом, по соглашению `<имя>_poster.jpg`.

    Решение владельца: пока ролик грузится, на его месте стоит первый кадр, а не
    мерцание. Постер снимаем сами при загрузке — иначе его надо задавать руками, и
    его не задают: в окне входа так и осталось мерцание.

    Возвращает имя файла или None (тогда сайт покажет прежнюю загрузку).
    """
    import os
    import shutil
    import subprocess
    import tempfile

    from django.core.files.base import File
    from django.core.files.storage import default_storage

    try:
        import imageio_ffmpeg
        ff = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None

    tmpdir = tempfile.mkdtemp(prefix="mata-poster-")
    src = os.path.join(tmpdir, "src.mp4")
    out = os.path.join(tmpdir, "poster.jpg")
    try:
        with default_storage.open(video_name, "rb") as fh, open(src, "wb") as dst:
            shutil.copyfileobj(fh, dst)
        subprocess.run(
            [ff, "-y", "-i", src, "-frames:v", "1", "-q:v", "4", out],
            check=True, timeout=120, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        if not os.path.exists(out) or os.path.getsize(out) == 0:
            return None
        name = os.path.splitext(video_name)[0] + "_poster.jpg"
        with open(out, "rb") as fh:
            return default_storage.save(name, File(fh))
    except Exception:
        return None
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ── Баннеры (промо) в конструкторе: полный CRUD перенесён из Django-админки ───
# Раньше баннеры правились только в Catalog → Banner. Теперь — визуально в
# «Конструкторе» (владелец: всё визуальное в одном месте). Данные общие, порядок
# раздельный по площадкам (sort_site/sort_app), как у товаров.

def _banner_json(b):
    return {
        "id": b.id,
        "title": b.title,
        "subtitle": b.subtitle,
        "action": b.action,
        "imageUrl": b.network_image_url(),
        "isPublished": b.is_published,
        "imageFit": b.image_fit or "cover",
        "imageFocal": b.image_focal or "50% 50%",
        "sortSite": b.sort_site,
        "sortApp": b.sort_app,
    }


_TRUE = ("1", "true", "True", "on", "yes", True)


def _apply_banner_fields(b, post, files):
    """Обновить поля баннера из multipart-формы (image опционально). Кидает ValueError."""
    if "title" in post:
        b.title = str(post.get("title") or "").strip()[:200]
    if "subtitle" in post:
        b.subtitle = str(post.get("subtitle") or "").strip()[:200]
    if "action" in post:
        b.action = str(post.get("action") or "").strip()[:80]
    if "isPublished" in post:
        b.is_published = post.get("isPublished") in _TRUE
    if "imageFit" in post:
        b.image_fit = "contain" if post.get("imageFit") == "contain" else "cover"
    if "imageFocal" in post:
        v = str(post.get("imageFocal") or "").strip()[:16]
        b.image_focal = v if v else "50% 50%"
    f = files.get("image")
    if f:
        if f.size > 40 * 1024 * 1024:
            raise ValueError("Файл слишком большой (макс 40 МБ)")
        if not (f.content_type or "").startswith("image/"):
            raise ValueError("Нужен файл-изображение")
        if b.image:
            try:
                b.image.delete(save=False)   # убрать старый файл баннера при замене
            except Exception:
                pass
        b.image = _webify_image(f)   # даунскейл + пережатие → лёгкий баннер


@staff_member_required
@tab_required("merch")
@require_http_methods(["GET"])
def merch_banners(request):
    """Список баннеров для конструктора в порядке выбранной площадки."""
    from catalog.models import Banner

    platform = (request.GET.get("platform") or "site").strip().lower()
    field = _PLATFORM_FIELD.get(platform, "sort")
    qs = Banner.objects.all().order_by(field, "sort", "id")
    return JsonResponse({"banners": [_banner_json(b) for b in qs]})


@staff_member_required
@tab_required("merch", LEVEL_EDIT)
@require_http_methods(["POST"])
def merch_banner_create(request):
    """Создать баннер (multipart: title/subtitle/action/isPublished + image)."""
    from django.db.models import Max

    from catalog.models import Banner

    b = Banner()
    try:
        _apply_banner_fields(b, request.POST, request.FILES)
    except ValueError as e:
        return JsonResponse({"detail": str(e)}, status=400)
    if not b.title:
        return JsonResponse({"detail": "Нужен заголовок"}, status=400)
    agg = Banner.objects.aggregate(s=Max("sort_site"), a=Max("sort_app"), g=Max("sort"))
    b.sort_site = (agg["s"] if agg["s"] is not None else -1) + 1
    b.sort_app = (agg["a"] if agg["a"] is not None else -1) + 1
    b.sort = (agg["g"] if agg["g"] is not None else -1) + 1
    b.save()
    return JsonResponse({"ok": True, "banner": _banner_json(b)})


@staff_member_required
@tab_required("merch", LEVEL_EDIT)
@require_http_methods(["POST"])
def merch_banner(request, bid):
    """Правка баннера (multipart, image опционально)."""
    from catalog.models import Banner

    b = Banner.objects.filter(id=bid).first()
    if not b:
        return JsonResponse({"detail": "Баннер не найден"}, status=404)
    try:
        _apply_banner_fields(b, request.POST, request.FILES)
    except ValueError as e:
        return JsonResponse({"detail": str(e)}, status=400)
    b.save()
    return JsonResponse({"ok": True, "banner": _banner_json(b)})


@staff_member_required
@tab_required("merch", LEVEL_EDIT)
@require_http_methods(["POST"])
def merch_banner_delete(request, bid):
    """Удалить баннер."""
    from catalog.models import Banner

    n, _ = Banner.objects.filter(id=bid).delete()
    if not n:
        return JsonResponse({"detail": "Баннер не найден"}, status=404)
    return JsonResponse({"ok": True})


@staff_member_required
@tab_required("merch", LEVEL_EDIT)
@require_http_methods(["POST"])
def merch_banner_reorder(request):
    """Порядок баннеров для площадки: {platform, order:[id,...]} → sort_site/app."""
    from catalog.models import Banner

    try:
        data = json.loads(request.body or b"{}")
    except ValueError:
        return JsonResponse({"detail": "Некорректный JSON"}, status=400)
    field = _PLATFORM_FIELD.get((data.get("platform") or "").strip().lower())
    if not field:
        return JsonResponse({"detail": "Неизвестная площадка"}, status=400)
    order = data.get("order") or []
    for i, bid in enumerate(order):
        Banner.objects.filter(id=bid).update(**{field: i})
    return JsonResponse({"ok": True, "count": len(order)})


@staff_member_required
@tab_required("storage")
@require_http_methods(["GET"])
def admin_storage(request):
    """Свободное место: диски (ФС) + размер БД + вес загрузок — наглядно, чтобы владелец
    легко зашёл и посмотрел. Несколько дисков/томов показываются отдельными карточками."""
    import os
    import shutil

    def human(n):
        n = float(n or 0)
        for unit in ("Б", "КБ", "МБ", "ГБ"):
            if n < 1024:
                return ("%.0f %s" % (n, unit)) if unit in ("Б", "КБ") else ("%.1f %s" % (n, unit))
            n /= 1024
        return "%.1f ТБ" % n

    media_root = getattr(settings, "MEDIA_ROOT", "/srv/media")
    disks = []
    for name, path in (("Медиа-хранилище (загрузки)", media_root), ("Диск приложения", "/")):
        try:
            du = shutil.disk_usage(path)
        except Exception:
            continue
        pct = round(du.used / du.total * 100) if du.total else 0
        disks.append({
            "name": name, "path": path,
            "total": human(du.total), "used": human(du.used), "free": human(du.free),
            "pct": pct, "level": ("danger" if pct >= 90 else "warn" if pct >= 75 else "ok"),
        })

    # Размер БД (PostgreSQL) — отдельным блоком (БД в своём контейнере/томе).
    db = None
    try:
        from django.db import connection
        with connection.cursor() as cur:
            cur.execute("SELECT pg_database_size(current_database())")
            db_bytes = cur.fetchone()[0]
        db = {"name": connection.settings_dict.get("NAME", "—"), "size": human(db_bytes)}
    except Exception:
        pass

    # Вес именно загрузок конструктора (uploads/*), для контекста.
    up = 0
    try:
        for dp, _dn, fns in os.walk(os.path.join(media_root, "uploads")):
            for fn in fns:
                try:
                    up += os.path.getsize(os.path.join(dp, fn))
                except Exception:
                    pass
    except Exception:
        pass

    return render(request, "admin/storage.html", {
        # each_context → сайдбар/шапка/навигация Unfold: вкладка внутри админки,
        # а не «голый» экран без кнопки назад (как «Ошибки»).
        **admin.site.each_context(request),
        "disks": disks, "db": db, "uploads_size": human(up),
    })
