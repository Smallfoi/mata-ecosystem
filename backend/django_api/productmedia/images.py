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


# ── Разметка снимка для витрины: где на нём товар (владелец 27.11.2026) ───────
#
# Снимки у брендов разные: у ANTA кадр вытянутый и кроссовок лежит в нижней
# трети, у STAW модель в полный рост, у очков Rockbros квадрат. Рамка карточки
# и страницы товара одна, и обрезка «по центру» резала подошвы, головы и края.
# Поэтому при загрузке ОДИН раз меряем снимок, а сайт и приложение по этой
# разметке ставят товар целиком в центр рамки, с полями цвета фона.

MEASURE_PX = 300        # хватает для рамки товара с точностью до процента
FLAT_SPREAD = 10        # средняя разница края с фоном; больше — фон не ровный (лайфстайл)


def measure(data: bytes) -> dict:
    """{"box": [лево, верх, право, низ] долями, "bg": "#rrggbb", "ar": ш/в}.

    Фон не ровный (снимок на улице, в интерьере) — рамкой считаем весь кадр:
    вырезать товар из сложного фона мы не умеем, такой снимок просто
    показывается целиком.
    """
    im = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
    if "A" in im.getbands() or im.mode == "P":
        # Прозрачный фон (гели SIS) — на белом, как его и видит покупатель;
        # простой convert("RGB") делал прозрачное чёрным.
        rgba = im.convert("RGBA")
        im = Image.new("RGB", rgba.size, WHITE)
        im.paste(rgba, mask=rgba.getchannel("A"))
    else:
        im = im.convert("RGB")
    ar = im.width / im.height
    im.thumbnail((MEASURE_PX, MEASURE_PX))
    w, h = im.size
    bg = _corner_background(im)
    diff = ImageChops.difference(im, Image.new("RGB", im.size, bg)).convert("L")
    edges = [diff.crop(b) for b in ((0, 0, w, 2), (0, h - 2, w, h), (0, 0, 2, h), (w - 2, 0, w, h))]
    spread = sum(sum(e.getdata()) / max(1, e.width * e.height) for e in edges) / 4
    box = None
    if spread <= FLAT_SPREAD:
        mask = diff.point(lambda v: 255 if v > BG_TOLERANCE else 0)
        # Убираем одиночные точки (шум сжатия, пылинки) — иначе рамка «до края».
        mask = mask.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3))
        box = mask.getbbox()
    if not box:
        box = (0, 0, w, h)
    l, t, r, b = box
    return {
        "box": [round(l / w, 3), round(t / h, 3), round(r / w, 3), round(b / h, 3)],
        "bg": "#%02x%02x%02x" % bg,
        "ar": round(ar, 4),
    }
