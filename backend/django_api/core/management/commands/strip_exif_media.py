"""Очистить УЖЕ загруженные изображения от EXIF/GPS/XMP (аудит D07, решение владельца).

Новые загрузки чистятся на лету (common.uploads.prepare_image). Эта команда проходит по
тому, что загрузили раньше, и пересохраняет файлы тем же путём:
  - имя/ключ файла НЕ меняется — ссылки в БД и в приложениях остаются рабочими;
  - ориентация из EXIF применяется к пикселям, формат прежний;
  - качество: PNG без потерь, JPEG q95 4:4:4; фотопайплайн (приватный) — без потерь;
  - ACL как было: публичные файлы пишутся публичным хранилищем (public-read),
    файлы фотопайплайна — приватным (private), см. common.media;
  - файлы без метаданных не трогаются, поэтому повторный запуск ничего не меняет.

Где ищем (все места загрузки изображений):
  публичное хранилище: uploads/ (аватары, отзывы, клубы, витрина ProductPhoto, баннеры,
                       блоки Конструктора, товары, категории), races/ (обложки), partners/;
  приватное хранилище: photopipeline/ (исходники, крупные планы, мастера, webp).

Запуск (владелец, на сервере):
    docker compose -f docker-compose.prod.yml exec web python manage.py strip_exif_media
        — сухой прогон: сколько изображений, у скольких есть метаданные и GPS;
    ... strip_exif_media --apply
        — перезаписать файлы с метаданными.
Ошибка на одном файле не останавливает остальные (попадает в отчёт).
"""
import io
import os
import tempfile

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand
from PIL import ExifTags, Image

from common.media import private_storage
from common.uploads import prepare_image

PUBLIC_ROOTS = ("uploads", "races", "partners")
PRIVATE_ROOTS = ("photopipeline",)
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif")
# Ключи Pillow, в которых живут метаданные (а не сама картинка).
_META_INFO = ("exif", "xmp", "XML:com.adobe.xmp", "comment", "photoshop",
              "Raw profile type exif", "extension")


def inspect_metadata(data: bytes):
    """(есть ли метаданные, есть ли GPS). MPO — всегда «есть»: доп. кадр со своим EXIF."""
    with Image.open(io.BytesIO(data)) as im:
        exif = im.getexif()
        xmp = im.info.get("xmp") or im.info.get("XML:com.adobe.xmp") or b""
        if isinstance(xmp, str):
            xmp = xmp.encode("utf-8", "ignore")
        gps = bool(exif.get_ifd(ExifTags.IFD.GPSInfo)) or b"GPS" in xmp
        text = getattr(im, "text", None) if im.format == "PNG" else None
        meta = (bool(exif) or im.format == "MPO" or bool(text)
                or any(k in im.info for k in _META_INFO))
    return meta or gps, gps


def _walk(storage, root):
    """Все файлы под root (рекурсивно, через API хранилища: диск или S3)."""
    try:
        dirs, files = storage.listdir(root)
    except (FileNotFoundError, NotADirectoryError, OSError):
        return
    for fn in files:
        yield "%s/%s" % (root, fn)
    for d in dirs:
        yield from _walk(storage, "%s/%s" % (root, d))


def overwrite(storage, name, data: bytes):
    """Записать data ровно под тем же именем.

    Обычный storage.save() при занятом имени придумал бы новое (file_overwrite=False),
    и ссылка в БД осталась бы на старый файл. Диск — атомарная замена через временный
    файл; S3 — запись в тот же ключ через _save с параметрами хранилища (ACL, тип).
    """
    try:
        path = storage.path(name)
    except NotImplementedError:
        path = None
    if path:
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".strip-")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            os.replace(tmp, path)
        except Exception:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise
        return name
    saved = storage._save(name, ContentFile(data))
    if saved != name:
        raise RuntimeError("хранилище записало под другим именем: %s" % saved)
    return saved


class Command(BaseCommand):
    help = "Снять EXIF/GPS/XMP с уже загруженных изображений. Без --apply — сухой прогон."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true",
                            help="перезаписать файлы (без флага — только подсчёт)")

    def handle(self, *args, **opts):
        apply = opts["apply"]
        stats = {"images": 0, "meta": 0, "gps": 0, "cleaned": 0, "failed": 0}
        plan = [(default_storage, r, False) for r in PUBLIC_ROOTS]
        plan += [(private_storage(), r, True) for r in PRIVATE_ROOTS]
        for storage, root, private in plan:
            for name in _walk(storage, root):
                if not name.lower().endswith(IMAGE_EXTS):
                    continue
                self._one(storage, name, private, apply, stats)
        if apply:
            self.stdout.write(
                "Изображений %(images)d: с метаданными %(meta)d (с GPS %(gps)d), "
                "очищено %(cleaned)d, ошибок %(failed)d." % stats)
        else:
            self.stdout.write(
                "Сухой прогон. Изображений %(images)d: с метаданными %(meta)d "
                "(с GPS %(gps)d), не прочитано %(failed)d. Очистить: --apply." % stats)

    def _one(self, storage, name, private, apply, stats):
        try:
            with storage.open(name, "rb") as fh:
                data = fh.read()
            meta, gps = inspect_metadata(data)
            stats["images"] += 1
            if not meta:
                return
            stats["meta"] += 1
            stats["gps"] += int(gps)
            if not apply:
                return
            ext, clean, err = prepare_image(ContentFile(data, name=name),
                                            archival=private or not name.lower().endswith(".webp"))
            if err:
                raise ValueError(err)
            overwrite(storage, name, clean.read())
            stats["cleaned"] += 1
        except Exception as e:                   # noqa: BLE001 — отчёт и дальше по списку
            stats["failed"] += 1
            self.stderr.write("не удалось: %s (%s)" % (name, e))
