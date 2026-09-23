"""Привязка папок с фото к товарам по артикулу — Вариант А фотопайплайна.

Работник раскладывает исходные фото по папкам, названным АРТИКУЛОМ товара (артикул —
единственная истина, приходит из 1С). Здесь сопоставляем имя папки с товаром по артикулу:
надёжно и без «угадывания по картинке». Возвращаем и несопоставленные папки — их работник
дотянет вручную, ни одно фото не потеряется и не уедет к чужому товару.
"""
from catalog.models import Product


def _norm(article: str) -> str:
    """Нормализация артикула для сравнения: без пробелов по краям, регистронезависимо."""
    return (article or "").strip().upper()


def match_folders_to_products(folder_names):
    """folder_names: список имён папок (= артикулов).

    Возвращает {"matched": [...], "unmatched": [...]}:
      matched:   {"folder", "article", "productId", "name"}
      unmatched: {"folder"}
    """
    # Индекс товаров по нормализованному артикулу (пустые артикулы не участвуют).
    by_article = {}
    for p in (Product.objects.exclude(article="")
              .only("id", "article", "name", "display_name")):
        by_article.setdefault(_norm(p.article), p)

    matched, unmatched = [], []
    seen = set()
    for folder in folder_names:
        name = (folder or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        product = by_article.get(_norm(name))
        if product:
            matched.append({
                "folder": folder,
                "article": product.article,
                "productId": product.id,
                "name": product.display_name or product.name,
            })
        else:
            unmatched.append({"folder": folder})
    return {"matched": matched, "unmatched": unmatched}
