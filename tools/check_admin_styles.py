# -*- coding: utf-8 -*-
"""Страж единого стиля админки: страницы не заводят собственное оформление.

Раньше каждая своя страница админки несла свой блок <style> со своей приставкой
(rv-, st-, ex-, cs-, pt-). Выглядело похоже, но расходилось в мелочах, а правка
означала обход всех файлов. Решение владельца 18.09.2026 (D-87): один стиль на всю
админку — `static/admin/mata.css`, страницы только расставляют классы `m-*`.

Что проверяем:
  1) в шаблонах `templates/admin/**` нет блоков <style> (кроме экранов «консоли»);
  2) не появились классы со старыми приставками.

Не хватает блока — добавить его в `static/admin/mata.css`, а не в шаблон.

Запуск: python tools/check_admin_styles.py
"""
from __future__ import annotations

import io
import re
import sys
from pathlib import Path

ADMIN_TEMPLATES = Path("backend/django_api/templates/admin")
STYLESHEET = Path("backend/django_api/static/admin/mata.css")

# Экраны «консоли» — отдельный утверждённый дизайн (вход, код, привязка фактора,
# приглашение, «доступ не настроен»). Они живут вне оболочки админки и наш файл
# стилей не подключают, поэтому своё оформление им положено.
CONSOLE = {"login.html", "two_factor.html", "staff/invite.html", "staff/otp_setup.html",
           "staff/no_access.html"}

OLD_PREFIXES = ("rv-", "ex-", "pt-", "cs-", "dp-", "st-", "sm-", "sec-", "errs-", "ed-", "eco-")
STYLE = re.compile(r"<style[\s>]")
CLASSES = re.compile(r'class="([^"]*)"')


def main() -> int:
    if not ADMIN_TEMPLATES.exists():
        print("Страж стиля: папка шаблонов админки не найдена — запускать из корня репозитория.")
        return 1
    if not STYLESHEET.exists():
        print(f"Страж стиля: нет общего файла {STYLESHEET}.")
        return 1

    problems: list[str] = []
    for path in sorted(ADMIN_TEMPLATES.rglob("*.html")):
        rel = path.relative_to(ADMIN_TEMPLATES).as_posix()
        if rel in CONSOLE:
            continue
        text = io.open(path, encoding="utf-8").read()
        if STYLE.search(text):
            problems.append(f"{rel}: свой блок <style> — правила место в static/admin/mata.css")
        for attr in CLASSES.findall(text):
            for cls in attr.split():
                if cls.startswith(OLD_PREFIXES) and not cls.startswith("m-"):
                    problems.append(f"{rel}: класс «{cls}» — используйте общие классы m-*")
                    break

    if problems:
        print("Страж единого стиля админки нашёл расхождения:\n")
        for p in problems:
            print("  •", p)
        print("\nБлоки и примеры — в шапке static/admin/mata.css.")
        return 1

    pages = sum(1 for p in ADMIN_TEMPLATES.rglob("*.html")
                if p.relative_to(ADMIN_TEMPLATES).as_posix() not in CONSOLE)
    print(f"✓ Единый стиль админки: {pages} страниц, своего оформления нет.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
