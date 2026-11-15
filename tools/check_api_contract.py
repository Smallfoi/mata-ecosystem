#!/usr/bin/env python3
"""СТРАЖ контракта API: ECOSYSTEM_API.md против маршрутов Django.

Зачем: `ECOSYSTEM_API.md` объявлен единым источником правды по эндпоинтам для трёх
продуктов (Квартал, МАТА Store, сайт). Источник правды, который врёт, хуже отсутствия
документа: по нему пишут клиентов. Сверка 15.11.2026 нашла в нём 58 неописанных адресов
и 4 обещанных, которых в коде нет (`PUT /auth/password`, `POST /auth/password/forgot`,
`POST /devices` вместо `/devices/register`, `GET /orders/:id`).

Страж ловит обе стороны расхождения:
  1) маршрут есть в коде, но его нет в документе — новый эндпоинт забыли описать;
  2) документ обещает адрес, которого в коде нет — клиент напишет в пустоту.

Запуск: python tools/check_api_contract.py   (0 — сошлось, 1 — расхождение)
"""
import ast
import os
import re
import sys

try:  # кириллица в выводе не должна падать на Windows-cp1251
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND = os.path.join(ROOT, "backend", "django_api")
DOC = os.path.join(ROOT, "ECOSYSTEM_API.md")

# path("v1/...", view) и path("v1/...", include("app.urls"))
PATH_RE = re.compile(r'path\(\s*"([^"]*)"\s*,\s*([^\n]*)')
INCLUDE_RE = re.compile(r'path\(\s*"([^"]*)"\s*,\s*include\("([^"]+)"\)')
# `GET /path`, `POST  /path`, `GET|PATCH /path` — в любом месте строки документа
DOC_RE = re.compile(r"\b(GET|POST|PATCH|PUT|DELETE)(\|\w+)*\s+(/[^\s|]*)")


def normalize(path: str) -> str:
    """Один вид для сравнения: без /v1, без query, параметры → {}.

    Django пишет `<str:club_id>`, документ — `:id`, `{id}` или `<ГГГГ-ММ-ДД>`.
    Для сверки адресов важна форма, а не имя параметра.
    """
    path = path.split("?")[0].split("[")[0]
    if path.startswith("/v1"):
        path = path[3:]
    path = re.sub(r"<[^>]*>", "{}", path)
    path = re.sub(r":[A-Za-z_]\w*", "{}", path)
    path = re.sub(r"\{[^}]*\}", "{}", path)
    return path.rstrip("/.`,") or "/"


def backend_routes() -> dict:
    """{нормализованный путь: как он записан в urls.py}."""
    main_path = os.path.join(BACKEND, "config", "urls.py")
    with open(main_path, encoding="utf-8") as f:
        main = f.read()

    includes = {m.group(2): m.group(1) for m in INCLUDE_RE.finditer(main)}
    raw = []
    for m in PATH_RE.finditer(main):
        url, rest = m.group(1), m.group(2)
        if url.startswith("v1") and "include(" not in rest:
            raw.append("/" + url)

    for module, prefix in includes.items():
        f_path = os.path.join(BACKEND, *module.split(".")) + ".py"
        if not os.path.exists(f_path):
            continue
        with open(f_path, encoding="utf-8") as f:
            src = f.read()
        for m in PATH_RE.finditer(src):
            raw.append("/" + prefix + m.group(1))

    out = {}
    for r in raw:
        out.setdefault(normalize(r), r)
    return out


def documented() -> set:
    with open(DOC, encoding="utf-8") as f:
        doc = f.read()
    return {normalize(m.group(3)) for m in DOC_RE.finditer(doc)}


def main() -> int:
    routes = backend_routes()
    doc = documented()

    undocumented = sorted(k for k in routes if k not in doc)
    # Обещанное, но несуществующее берём только со строк, которые ОБЪЯВЛЯЮТ эндпоинт
    # (начало строки), иначе ловим упоминания в прозе.
    with open(DOC, encoding="utf-8") as f:
        text = f.read()
    declared = {
        normalize(m.group(3))
        for m in re.finditer(r"^\s*(GET|POST|PATCH|PUT|DELETE)(\|\w+)*\s+(/\S*)", text, re.M)
    }
    phantom = sorted(declared - set(routes))

    if not undocumented and not phantom:
        print(
            "✓ Контракт API сошёлся: %d маршрутов /v1 — все описаны, лишнего не обещано."
            % len(routes)
        )
        return 0

    if undocumented:
        print("✗ Есть в коде, НЕ описано в ECOSYSTEM_API.md (%d):" % len(undocumented))
        for k in undocumented:
            print("    %s" % routes[k])
        print("  Опишите эндпоинт в ECOSYSTEM_API.md — по этому файлу пишут клиентов.")
    if phantom:
        print("✗ Обещано в ECOSYSTEM_API.md, НЕТ в коде (%d):" % len(phantom))
        for k in phantom:
            print("    %s" % k)
        print("  Либо реализуйте, либо уберите из документа.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
