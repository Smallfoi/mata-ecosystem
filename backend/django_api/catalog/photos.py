"""Работа с фотографиями витрины: приём файла, размеры, выдача по модели и цвету.

Почему отдельный модуль: снимок с фотоаппарата весит 8–12 МБ, а витрине нужен
лёгкий webp и совсем маленькая миниатюра. Приводим файл к обоим размерам ОДИН раз
при загрузке — не на каждый запрос покупателя (D-99).
"""
from django.core.files.base import ContentFile

from productmedia.images import make_webp

from .models import ProductPhoto

# Длинная сторона каждого размера.
FULL_PX = 1600
# Лента каталога: карточка занимает треть ширины (≈450 px), на экране с удвоенной
# плотностью — 900. Миниатюрой 400 её затягивало в мыло (владелец, 02.10.2026).
CARD_PX = 900
# Кружки выбора цвета и мелкие превью.
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
    photo.card.save(f"{base}-c.webp", ContentFile(make_webp(data, CARD_PX)), save=False)
    photo.thumb.save(f"{base}-t.webp", ContentFile(make_webp(data, THUMB_PX)), save=False)
    photo.save()
    return photo


def ensure_card(photo: ProductPhoto) -> bool:
    """Дорисовать средний размер снимку, залитому до его появления.

    Берём исходником витринный файл (1600): оригинал камеры мы не храним, а 1600 → 900
    без потерь качества для ленты.
    """
    if photo.card or not photo.image:
        return False
    photo.image.open("rb")
    try:
        data = photo.image.read()
    finally:
        photo.image.close()
    base = photo.image.name.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    photo.card.save(f"{base}-c.webp", ContentFile(make_webp(data, CARD_PX)), save=True)
    return True


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


def move(photo: ProductPhoto, delta: int) -> bool:
    """Сдвинуть снимок на одну позицию: delta -1 влево, +1 вправо.

    Порядок снимков — это порядок показа в карточке слева направо, и владельцу
    нужно расставлять его самому: «сделать главным» двигает только обложку, а
    остальные пять остаются в том порядке, в каком их залили (02.10.2026).

    Возвращает False, если двигать некуда (снимок с краю) — вызывающий покажет
    это как «ничего не произошло», а не как ошибку.
    """
    rows = list(ProductPhoto.objects.filter(model_key=photo.model_key, color=photo.color))
    at = next((i for i, row in enumerate(rows) if row.pk == photo.pk), -1)
    to = at + delta
    if at < 0 or to < 0 or to >= len(rows):
        return False
    rows[at], rows[to] = rows[to], rows[at]
    for i, row in enumerate(rows):
        if row.order != i:
            row.order = i
            row.save(update_fields=["order"])
    return True


def reorder(model_key: str, color: str, ids) -> int:
    """Записать порядок снимков списком: ids идут слева направо.

    Перетаскивание задаёт сразу весь ряд, поэтому принимаем ряд целиком, а не
    пару перестановок: иначе при быстром перетаскивании нескольких снимков
    клиент и сервер разошлись бы в порядке.

    Чужие id молча игнорируем, пропущенные дописываем в конец в прежнем порядке —
    пересчёт обязан оставить галерею целой при любом входе. Возвращает число
    снимков, которым порядок поменяли.
    """
    rows = {r.pk: r for r in ProductPhoto.objects.filter(model_key=model_key, color=color)}
    wanted, seen = [], set()
    for raw in ids or []:
        try:
            pk = int(raw)
        except (TypeError, ValueError):
            continue
        if pk in rows and pk not in seen:
            seen.add(pk)
            wanted.append(rows[pk])
    for pk, row in rows.items():                    # не названные — в конец, как были
        if pk not in seen:
            wanted.append(row)
    changed = 0
    for i, row in enumerate(wanted):
        if row.order != i:
            row.order = i
            row.save(update_fields=["order"])
            changed += 1
    return changed


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
