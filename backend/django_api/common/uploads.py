"""Проверка загружаемых изображений (D-37, аудит D07).

Раньше тип файла определялся по заголовку `Content-Type` и расширению из имени — и то,
и другое присылает клиент. Значит можно было положить в media файл `x.html` с любым
содержимым: nginx отдал бы его как страницу, то есть хранимый XSS на домене медиа.

Тип определяется ПО СОДЕРЖИМОМУ (сигнатуре файла), имя и заголовок игнорируются.
Сигнатуры мало: к правильным первым байтам можно дописать что угодно (мусор,
обрезанный поток) или прислать «бомбу» — крошечный файл, который при разборе
разворачивается в гигапиксели и съедает память воркера. Поэтому файл целиком
декодируется Pillow с лимитом пикселей: битый, обрезанный, неподдерживаемый или
слишком большой по размерам — отклоняется (аудит D07).

Годный файл дальше ПЕРЕСОХРАНЯЕТСЯ без метаданных (`prepare_image`, аудит D07): фото
с телефона несёт в EXIF координаты съёмки — это геопозиция человека (152-ФЗ), модель
телефона, серийники, время. Ориентацию из EXIF сначала применяем к пикселям, иначе
после снятия EXIF снимок «ляжет на бок».
"""
import io
import warnings

from django.core.files.base import ContentFile

MAX_IMAGE_BYTES = 40 * 1024 * 1024
# Лимит размеров: 64 Мп (8000×8000) — больше любой нормальной фотографии/баннера.
MAX_IMAGE_PIXELS = 64_000_000
# Для анимированного GIF считаем пиксели всех кадров вместе.
MAX_TOTAL_PIXELS = 256_000_000

# Сигнатуры (magic bytes) → расширение, которое мы сами и подставим в имя файла.
_SIGNATURES = (
    (b"\xff\xd8\xff", "jpg"),
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
)
# Что Pillow должен узнать в файле для каждого расширения по сигнатуре.
_PIL_FORMAT = {"jpg": "JPEG", "png": "PNG", "gif": "GIF", "webp": "WEBP"}
# MPO — это JPEG с приклеенными доп. кадрами (превью/глубина), так пишут камеры многих
# телефонов (Samsung и др.). Для нас это обычный JPEG: берём основной кадр.
_ALSO_OK = {"jpg": {"MPO"}}

# Качество пересохранения (аудит D07). Обычные загрузки — на глаз без потерь.
JPEG_QUALITY = 90
WEBP_QUALITY = 90
# Исходники фотопайплайна потом обрабатывает ИИ — сохраняем максимально близко к оригиналу.
ARCHIVE_JPEG_QUALITY = 95

_BAD_IMAGE = "Файл повреждён или это не изображение (JPEG, PNG, GIF или WebP)"
_TOO_BIG = "Изображение слишком большое (макс %d Мп)" % (MAX_IMAGE_PIXELS // 1_000_000)


def _sniff(head: bytes):
    for magic, ext in _SIGNATURES:
        if head.startswith(magic):
            return ext
    # WEBP: "RIFF" + 4 байта размера + "WEBP"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    return None


def _decode_error(f, ext):
    """Полностью разобрать изображение. Текст ошибки или None, если файл годен."""
    from PIL import Image

    try:
        f.seek(0)
        with warnings.catch_warnings():
            # DecompressionBombWarning → исключение: свои лимиты строже встроенных.
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(f) as im:
                if im.format != _PIL_FORMAT[ext] and im.format not in _ALSO_OK.get(ext, ()):
                    return _BAD_IMAGE
                w, h = im.size
                if w <= 0 or h <= 0:
                    return _BAD_IMAGE
                if w * h > MAX_IMAGE_PIXELS:
                    return _TOO_BIG
                frames = getattr(im, "n_frames", 1) or 1
                if w * h * frames > MAX_TOTAL_PIXELS:
                    return "Слишком много кадров в анимации"
                # Полное декодирование каждого кадра: обрезанный/битый поток падает здесь.
                for i in range(frames):
                    im.seek(i)
                    im.load()
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        return _TOO_BIG
    except Exception:                            # noqa: BLE001 — любой сбой разбора = битый файл
        return _BAD_IMAGE
    finally:
        f.seek(0)  # вернуть курсор — файл ещё предстоит сохранить
    return None


def image_extension(f, allowed=None):
    """(расширение, текст ошибки). Ошибка не None → загрузку отклонить.

    allowed — набор допустимых расширений ("jpg", "png", "gif", "webp"); None — все.
    """
    if not f:
        return None, "Нет файла"
    if f.size > MAX_IMAGE_BYTES:
        return None, "Файл слишком большой (макс 40 МБ)"
    head = f.read(16)
    f.seek(0)
    ext = _sniff(head or b"")
    if not ext or (allowed is not None and ext not in allowed):
        return None, "Нужен файл-изображение (JPEG, PNG, GIF или WebP)"
    err = _decode_error(f, ext)
    if err:
        return None, err
    return ext, None


def _animated(im) -> bool:
    return im.format in ("GIF", "PNG", "WEBP") and (getattr(im, "n_frames", 1) or 1) > 1


def clean_image_bytes(f, ext, *, archival=False) -> bytes:
    """Пересохранить уже проверенное изображение в тот же формат без метаданных.

    Уходят EXIF (GPS, модель телефона, время), XMP, текстовые блоки PNG, комментарии
    JPEG/GIF. Остаются пиксели, прозрачность и ICC-профиль (цвет, а не сведения о человеке).
    Анимация (GIF, WebP, APNG) сохраняется со всеми кадрами, задержками и повтором.
    archival=True — исходник для ИИ: PNG/WebP без потерь, JPEG 95 без прореживания цвета.
    """
    from PIL import Image, ImageOps

    fmt = _PIL_FORMAT[ext]
    out = io.BytesIO()
    f.seek(0)
    try:
        with Image.open(f) as src:
            icc = src.info.get("icc_profile")
            if _animated(src):
                _save_animated(src, fmt, out, archival, icc)
            else:
                src.seek(0)
                # Ориентацию — в пиксели ДО снятия EXIF, иначе фото с телефона ляжет на бок.
                im = ImageOps.exif_transpose(src)
                # Из info Pillow берёт при записи комментарии/EXIF — оставляем только
                # прозрачность (это часть картинки, а не метаданные).
                im.info = {k: v for k, v in im.info.items() if k == "transparency"}
                kw = {"icc_profile": icc} if icc else {}
                if fmt == "JPEG":
                    if im.mode not in ("RGB", "L"):
                        im = im.convert("RGB")   # CMYK и пр.: браузеры понимают RGB надёжнее
                        kw = {}                  # профиль был от другой цветовой модели
                    kw.update(quality=ARCHIVE_JPEG_QUALITY if archival else JPEG_QUALITY,
                              optimize=True)
                    if archival:
                        kw["subsampling"] = 0    # 4:4:4 — цвет без прореживания
                elif fmt == "WEBP":
                    kw.update({"lossless": True} if archival else {"quality": WEBP_QUALITY})
                elif fmt == "GIF":
                    kw = {}                      # у GIF нет ICC
                im.save(out, fmt, **kw)
    finally:
        f.seek(0)
    return out.getvalue()


def _save_animated(src, fmt, out, archival, icc):
    """Анимацию пересобираем кадр за кадром: кадры, задержки и повтор — как были.

    Кадры Pillow берёт из самого src (без копии всей анимации в память). Ориентацию
    не трогаем: у анимаций её в EXIF на практике не бывает, а EXIF всё равно не пишем.
    """
    durations = []
    for i in range(src.n_frames):
        src.seek(i)
        durations.append(int(src.info.get("duration") or 0))
    src.seek(0)
    loop = src.info.get("loop", 0)
    kw = {"save_all": True, "duration": durations, "loop": loop}
    if fmt == "GIF":
        # Пустой комментарий перекрывает тот, что Pillow иначе перенёс бы из исходника.
        kw["comment"] = b""
    elif fmt == "WEBP":
        kw.update({"lossless": True} if archival else {"quality": WEBP_QUALITY})
        kw.update(exif=b"", xmp=b"")
        if icc:
            kw["icc_profile"] = icc
    elif icc:
        kw["icc_profile"] = icc
    src.save(out, fmt, **kw)


def prepare_image(f, allowed=None, *, archival=False):
    """Проверить и очистить загрузку: (расширение, ContentFile, текст ошибки).

    Ошибка не None → загрузку отклонить. Иначе сохранять ContentFile, а НЕ исходный
    файл: в нём уже нет EXIF/GPS/XMP (аудит D07).
    """
    ext, err = image_extension(f, allowed)
    if err:
        return None, None, err
    try:
        data = clean_image_bytes(f, ext, archival=archival)
    except Exception:                            # noqa: BLE001 — не смогли очистить = не храним
        return None, None, _BAD_IMAGE
    return ext, ContentFile(data, name="image.%s" % ext), None
