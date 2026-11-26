"""Разовые правки контента на проде — кодом через PR, а не руками (D-103).

Каждая правка идемпотентна: повторный прогон ничего не меняет, а то, что владелец
уже успел поправить сам, не трогается (заменяется только точный старый фрагмент).
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Демо-баннеры из первого наполнения: «Новая коллекция Весна 2025», «Скидки до 40%»,
# «Зимняя линейка». Фото — стоковые из assets приложения (на сайте 404), скидок
# в каталоге нет. Владелец 26.11.2026: «баннеры сними».
DEMO_BANNER_IDS = (55, 56, 57)
DEMO_IMAGE_PREFIX = "assets/images/products/"


def unpublish_demo_banners(Banner) -> int:
    """Снять с публикации демо-баннеры. Только те, что всё ещё на стоковых фото:
    если владелец заменил фото на своё — баннер уже его, не трогаем."""
    from django.db.models import Q

    return (
        Banner.objects.filter(
            id__in=DEMO_BANNER_IDS,
            is_published=True,
            image_url__startswith=DEMO_IMAGE_PREFIX,
        )
        .filter(Q(image="") | Q(image__isnull=True))
        .update(is_published=False)
    )


def load_pairs(name: str) -> list[dict]:
    with open(HERE / name, encoding="utf-8") as f:
        return json.load(f)


def apply_copy_fixes(Product, pairs: list[dict]) -> int:
    """Заменить в описаниях точные фрагменты old → new. Возвращает число товаров,
    у которых описание изменилось. Поле помечается как правка владельца, чтобы
    выгрузка 1С не вернула старый текст."""
    changed = 0
    for p in Product.objects.exclude(description=""):
        text = p.description
        for pair in pairs:
            if pair["old"] in text:
                text = text.replace(pair["old"], pair["new"])
        if text == p.description:
            continue
        p.description = text
        overrides = list(p.overrides or [])
        if "description" not in overrides:
            overrides.append("description")
        p.overrides = overrides
        p.save(update_fields=["description", "overrides"])
        changed += 1
    return changed
