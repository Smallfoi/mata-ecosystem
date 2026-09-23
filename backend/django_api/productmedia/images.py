"""Изображения фотопайплайна: из «мастера» (высокое разрешение от ИИ) делаем лёгкий
webp под витрину. Мастер храним как есть (печать, маркетплейсы, другой кроп без повторной
генерации), webp отдаём на сайт/в приложение.
"""
import io

from PIL import Image

WEBP_MAX_PX = 1600   # длинная сторона витринного webp
WEBP_QUALITY = 82


def make_webp(master_bytes: bytes, max_px: int = WEBP_MAX_PX, quality: int = WEBP_QUALITY) -> bytes:
    """Мастер (любой формат) → сжатый webp, вписанный в max_px по длинной стороне.
    Прозрачность сохраняем (RGBA), иначе RGB."""
    im = Image.open(io.BytesIO(master_bytes))
    if im.mode not in ("RGB", "RGBA"):
        im = im.convert("RGBA" if "A" in im.getbands() else "RGB")
    im.thumbnail((max_px, max_px))  # уменьшает, не увеличивает; сохраняет пропорции
    out = io.BytesIO()
    im.save(out, format="WEBP", quality=quality, method=6)
    return out.getvalue()
