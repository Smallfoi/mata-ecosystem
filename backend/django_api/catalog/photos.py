"""Работа с фотографиями витрины: приём файла, размеры, выдача по модели и цвету.

Почему отдельный модуль: снимок с фотоаппарата весит 8–12 МБ, а витрине нужен
лёгкий webp и совсем маленькая миниатюра. Приводим файл к обоим размерам ОДИН раз
при загрузке — не на каждый запрос покупателя (D-99).
"""
from django.core.files.base import ContentFile

from productmedia.images import make_webp

from .models import ProductPhoto

# Длинная сторона: витринный снимок и миниатюра для ленты каталога и кружков цвета.
FULL_PX = 1600
THUMB_PX = 400


def norm_color(color: str) -> str:
    """Цвет для сравнения: 1С пишет то «ЧЕРНЫЙ», то «Черный»."""
    return (color or "").strip().upper()


def store_photo(model_key: str, color: str, data: bytes, base: str) -> ProductPhoto:
    """Сохранить снимок как следующий по порядку у этой модели и цвета.

    Кидает ValueError, если место кончилось: шесть — решение владельца, и молча
    седьмой снимок терять нельзя.
    """
    used = ProductPhoto.objects.filter(model_key=model_key, color=color).count()
    if used >= ProductPhoto.MAX_PER_COLOR:
        raise ValueError(
            f"у этого цвета уже {ProductPhoto.MAX_PER_COLOR} фото — удалите лишнее"
        )

    photo = ProductPhoto(model_key=model_key, color=color, order=used)
    photo.image.save(f"{base}.webp", ContentFile(make_webp(data, FULL_PX)), save=False)
    photo.thumb.save(f"{base}-t.webp", ContentFile(make_webp(data, THUMB_PX)), save=False)
    photo.save()
    return photo


def renumber(model_key: str, color: str) -> None:
    """Пересчитать порядок подряд — после удаления или смены главного снимка."""
    rows = list(ProductPhoto.objects.filter(model_key=model_key, color=color))
    for i, row in enumerate(rows):
        if row.order != i:
            row.order = i
            row.save(update_fields=["order"])


def make_main(photo: ProductPhoto) -> None:
    """Сделать снимок первым: он идёт обложкой карточки в ленте каталога."""
    others = ProductPhoto.objects.filter(
        model_key=photo.model_key, color=photo.color
    ).exclude(pk=photo.pk)
    photo.order = 0
    photo.save(update_fields=["order"])
    for i, row in enumerate(others, start=1):
        if row.order != i:
            row.order = i
            row.save(update_fields=["order"])


def by_model(keys) -> dict:
    """{ключ модели: {ЦВЕТ: [фото, ...]}} одним запросом.

    Витрина отдаёт две сотни карточек за раз — по запросу на карточку превратило бы
    список в две сотни запросов.
    """
    out = {}
    for row in ProductPhoto.objects.filter(model_key__in=list(keys)):
        out.setdefault(row.model_key, {}).setdefault(norm_color(row.color), []).append(row)
    return out


def pick(photos: dict, color: str):
    """Снимки нужного цвета; нет таких — общие снимки модели (цвет не заполнен)."""
    if not photos:
        return []
    return photos.get(norm_color(color)) or photos.get("") or []

def attach(model_key: str, color: str = "", data: bytes = b"", first: bool = False):
    """Положить готовый снимок в галерею модели — точка входа для фотопайплайна.

    Конвейер (`productmedia`) отдаёт байты картинки, а размеры, имена файлов и
    порядок делаются здесь: хранилище одно, и правила у него одни. `first=True` —
    снимок становится обложкой (у ИИ это «главное фото» задания).

    Кидает ValueError, если у цвета кончились места.
    """
    import secrets

    row = store_photo(model_key, color, data, secrets.token_hex(8))
    if first:
        make_main(row)
        row.refresh_from_db()
    return row
