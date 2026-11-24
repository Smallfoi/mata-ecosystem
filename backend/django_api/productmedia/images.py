"""Изображения фотопайплайна: из «мастера» (высокое разрешение от ИИ) делаем лёгкий
webp под витрину. Мастер храним как есть (печать, маркетплейсы, другой кроп без повторной
генерации), webp отдаём на сайт/в приложение.
"""
import io

from PIL import Image, ImageChops, ImageFilter, ImageOps

WEBP_MAX_PX = 1600   # длинная сторона витринного webp
WEBP_QUALITY = 82


def make_webp(master_bytes: bytes, max_px: int = WEBP_MAX_PX, quality: int = WEBP_QUALITY) -> bytes:
    """Мастер (любой формат) → сжатый webp, вписанный в max_px по длинной стороне.
    Прозрачность сохраняем (RGBA), иначе RGB.

    Ориентацию из EXIF применяем к пикселям: сам EXIF в webp не пишем (Pillow берёт его
    только из явного аргумента), и без поворота снимок с телефона лёг бы на бок (аудит D07).
    """
    im = ImageOps.exif_transpose(Image.open(io.BytesIO(master_bytes)))
    if im.mode not in ("RGB", "RGBA"):
        im = im.convert("RGBA" if "A" in im.getbands() else "RGB")
    im.thumbnail((max_px, max_px))  # уменьшает, не увеличивает; сохраняет пропорции
    out = io.BytesIO()
    im.save(out, format="WEBP", quality=quality, method=6)
    return out.getvalue()


# ── Витринная обработка: один вид каталога без перерисовки товара ────────────
#
# ИИ-генерация (`gpt-image` edit) рисует КАРТИНКУ ЗАНОВО по образцу: сохранить
# исходный ракурс и позу она не умеет в принципе — у модели нет режима «оставь
# эти пиксели». Отсюда и «все кроссовки на одно лицо». Когда от снимка нужно не
# новое изображение, а ровный фон, единый кадр и размер, работает обычная
# обработка: пиксели товара не трогаются вовсе.
#
# Что делает: находит товар по отличию от фона, обрезает по нему, кладёт на
# квадратное поле ровно по центру с одинаковыми полями, подтягивает резкость.
# Фон берётся из углов самого снимка, поэтому белый остаётся белым, а светло-серый
# студийный — светло-серым; задать его явно можно параметром.
#
# Чего НЕ делает: не вырезает товар из сложного фона (стол, пол, витрина). Для
# таких снимков нужна маска (сегментация) — отдельный шаг, его добавим, если
# понадобится. Поэтому снимать по-прежнему лучше на ровном светлом фоне.

WHITE = (255, 255, 255)   # фон витрины — решение владельца 25.11.2026
SHOWCASE_PX = 2048        # сторона квадрата мастера
SHOWCASE_MARGIN = 0.06    # поля вокруг товара, доля стороны
BG_TOLERANCE = 18         # насколько пиксель может отличаться от фона и всё ещё быть фоном


def _corner_background(im: Image.Image) -> tuple:
    """Цвет фона — медиана по четырём углам.

    Медиана, а не среднее: пылинка, блик или уголок товара, залезший в угол,
    среднее сдвинут, а медиану — нет.
    """
    w, h = im.size
    patch = max(4, min(w, h) // 50)
    boxes = ((0, 0, patch, patch), (w - patch, 0, w, patch),
             (0, h - patch, patch, h), (w - patch, h - patch, w, h))
    pixels = []
    for box in boxes:
        region = im.crop(box).resize((1, 1), Image.Resampling.BOX)
        pixels.append(region.getpixel((0, 0)))
    return tuple(sorted(c[i] for c in pixels)[len(pixels) // 2] for i in range(3))


def _content_box(im: Image.Image, bg: tuple, tolerance: int):
    """Прямоугольник товара: всё, что отличается от фона сильнее допуска.

    Считаем разницей с одноцветным полотном — это один проход в C внутри Pillow,
    без numpy и без перебора пикселей на Python.
    """
    diff = ImageChops.difference(im, Image.new("RGB", im.size, bg)).convert("L")
    return diff.point(lambda v: 255 if v > tolerance else 0).getbbox()


def showcase(master_bytes: bytes, *, size: int = SHOWCASE_PX,
             margin: float = SHOWCASE_MARGIN, paper: tuple = WHITE,
             tolerance: int = BG_TOLERANCE, sharpen: bool = True) -> bytes:
    """Снимок → витринный мастер: белый фон, товар по центру, единый размер.

    Товар не перерисовывается: его пиксели переносятся как есть, меняется только
    фон и обрамление. Ракурс, поза, принт и цвет остаются такими, какими их сняли.

    Белым делается именно ФОН СНИМКА, а не только поле вокруг. Если просто
    положить вырезанный прямоугольник на белый лист, серая студийная подложка
    исходника останется внутри него и будет видна рамкой.
    """
    im = ImageOps.exif_transpose(Image.open(io.BytesIO(master_bytes))).convert("RGB")
    found = _corner_background(im)

    # Маска товара: всё, что отличается от фона снимка сильнее допуска. Белые
    # места товара на белом фоне в маску не попадут — и не беда: они и так белые.
    # На сером фоне они отличаются и сохраняются.
    diff = ImageChops.difference(im, Image.new("RGB", im.size, found)).convert("L")
    mask = diff.point(lambda v: 255 if v > tolerance else 0)
    # Чуть размываем край: без этого по контуру товара остаётся «лесенка».
    mask = mask.filter(ImageFilter.GaussianBlur(0.8))

    im = Image.composite(im, Image.new("RGB", im.size, paper), mask)

    box = mask.getbbox()
    if box:
        im = im.crop(box)

    # Товар вписываем в квадрат за вычетом полей; увеличиваем только при нужде.
    inner = max(1, int(round(size * (1 - 2 * margin))))
    scale = min(inner / im.width, inner / im.height)
    im = im.resize((max(1, round(im.width * scale)), max(1, round(im.height * scale))),
                   Image.Resampling.LANCZOS)

    if sharpen:
        # Мягко: после уменьшения кромка подошвы и шнурки «замыливаются», но
        # сильная резкость лезет ореолами по краю товара.
        im = im.filter(ImageFilter.UnsharpMask(radius=1.2, percent=60, threshold=3))

    canvas = Image.new("RGB", (size, size), paper)
    canvas.paste(im, ((size - im.width) // 2, (size - im.height) // 2))

    out = io.BytesIO()
    canvas.save(out, format="PNG", optimize=True)
    return out.getvalue()
