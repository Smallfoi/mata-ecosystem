"""Уменьшенные копии фото сайта под экраны (этап 6 оптимизации, 21.11.2026).

Фото блоков из Конструктора хранится до 2560 px по большей стороне — на телефон
уходило 300–600 КБ на картинку (Lighthouse: 1 МБ лишнего на главной). Делаем копии
640 и 1280 px; сайт отдаёт их через `srcset`, и браузер телефона берёт подходящую.

Копии привязаны к имени исходного файла (`image_variants["src"]`): заменили фото
в Конструкторе — старые копии перестают отдаваться сами, новые сделает следующий
проход фоновой задачи. Пока копий нет, сайт показывает исходное фото, как раньше.
"""
import io
import logging
import os

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

log = logging.getLogger(__name__)

WIDTHS = (640, 1280)
QUALITY = 80


def variants_ready(obj) -> bool:
    v = obj.image_variants or {}
    return bool(obj.image) and v.get("src") == obj.image.name


def srcset(obj) -> str:
    """`url640 640w, url1280 1280w, оригинал Nw` — или пусто, если копий нет."""
    if not variants_ready(obj):
        return ""
    v = obj.image_variants
    parts = [f"{default_storage.url(v[str(w)])} {w}w" for w in WIDTHS if v.get(str(w))]
    if not parts:
        return ""
    full_w = v.get("width")
    if full_w:
        parts.append(f"{obj.image.url} {full_w}w")
    return ", ".join(parts)


def make_variants(obj) -> bool:
    """Сделать копии для `obj.image` (SiteContent). True — что-то записали."""
    from PIL import Image

    if not obj.image or variants_ready(obj):
        return False
    name = obj.image.name
    if name.lower().endswith((".svg", ".gif")):
        return False
    with obj.image.open("rb") as fh:
        img = Image.open(io.BytesIO(fh.read()))
        img.load()
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA" if "A" in img.getbands() else "RGB")
    w, h = img.size
    base = os.path.basename(name).rsplit(".", 1)[0]
    variants = {"src": name, "width": w}
    for target in WIDTHS:
        if w <= target:
            continue  # исходник и так не шире — копия не нужна
        small = img.resize((target, max(1, round(h * target / w))), Image.LANCZOS)
        buf = io.BytesIO()
        small.save(buf, format="WEBP", quality=QUALITY, method=6)
        saved = default_storage.save(
            f"uploads/site/variants/{base}_w{target}.webp", ContentFile(buf.getvalue()))
        variants[str(target)] = saved
    obj.image_variants = variants
    obj.save(update_fields=["image_variants"])
    return True


def make_all(stdout=None) -> int:
    """Копии для всех фото сайта, у которых их нет или они устарели."""
    from catalog.models import SiteContent

    done = 0
    for obj in SiteContent.objects.exclude(image="").exclude(image__isnull=True):
        try:
            if make_variants(obj):
                done += 1
                if stdout:
                    stdout.write(f"  копии: {obj.key} ({obj.image.name})")
        except Exception:
            log.warning("копии фото %s не сделаны", obj.key, exc_info=True)
    return done
