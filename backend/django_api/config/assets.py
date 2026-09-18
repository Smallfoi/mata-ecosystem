# -*- coding: utf-8 -*-
"""Метка версии у своих файлов стиля админки.

nginx на проде отдаёт `/static/` с `Cache-Control: max-age=604800` — неделю.
Адрес `/static/admin/mata.css` при правке не меняется, поэтому браузер ещё
неделю берёт СТАРЫЙ файл из своей памяти и не спрашивает сервер: владелец
выкатанных изменений не видит и думает, что их не сделали (реальный случай —
подсветка строк 18.09.2026; та же беда уже была на сайте, см. страж
`tools/check_site_cache_bust.py`).

Поэтому к адресу дописываем короткий отпечаток содержимого: поменяли файл —
поменялся адрес — браузер скачивает заново. Не поменяли — тянет из памяти,
как и должен.
"""
from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path

from django.templatetags.static import static


@lru_cache(maxsize=32)
def _fingerprint(root: str, rel: str) -> str:
    """Отпечаток содержимого файла. Считается один раз на процесс: после выката
    поднимается новый процесс — отпечаток пересчитывается сам."""
    try:
        data = Path(root, *rel.split("/")).read_bytes()
    except OSError:
        return ""  # файла нет (редкий случай) — просто отдаём адрес без метки
    return hashlib.sha256(data).hexdigest()[:10]


def versioned(rel: str) -> str:
    """Адрес файла статики с меткой версии: `/static/admin/mata.css?v=ab12cd34ef`."""
    from django.conf import settings

    for root in [*settings.STATICFILES_DIRS, settings.STATIC_ROOT]:
        if not root:
            continue
        mark = _fingerprint(str(root), rel)
        if mark:
            return f"{static(rel)}?v={mark}"
    return static(rel)
