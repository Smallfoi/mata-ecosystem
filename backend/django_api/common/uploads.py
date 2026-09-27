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
"""
import warnings

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
                if im.format != _PIL_FORMAT[ext]:
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
