#!/usr/bin/env python3
"""Страж воспроизводимости бэкенда (F05 аудита 27.09.2026).

Сверяет то, что РЕАЛЬНО установилось (`pip freeze`), с зафиксированным
`backend/django_api/requirements.lock`. Прод-образ на ВМ собирается заново
(`pip install -r requirements.txt -c requirements.lock`), поэтому lock — это
ровно тот набор, что поедет в прод. Если кто-то добавил зависимость в
requirements.txt и не обновил lock, она поставится «последней версией» —
этот страж это ловит и валит CI.

Запуск (в окружении, куда поставлены зависимости):
    python tools/check_requirements_lock.py backend/django_api/requirements.lock
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def parse(lines: list[str]) -> dict[str, str]:
    pins: dict[str, str] = {}
    for raw in lines:
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if "==" not in line:
            raise SystemExit(f"lock: строка без точной версии: {raw!r}")
        name, ver = line.split("==", 1)
        pins[_norm(name)] = ver.strip()
    return pins


def main() -> int:
    lock_path = Path(sys.argv[1] if len(sys.argv) > 1 else "backend/django_api/requirements.lock")
    locked = parse(lock_path.read_text(encoding="utf-8").splitlines())
    frozen_out = subprocess.run(
        [sys.executable, "-m", "pip", "freeze"], check=True, capture_output=True, text=True
    ).stdout
    installed = parse(frozen_out.splitlines())

    problems = []
    for name, ver in sorted(installed.items()):
        if name not in locked:
            problems.append(f"  + {name}=={ver} установлен, но его нет в lock")
        elif locked[name] != ver:
            problems.append(f"  ~ {name}: установлен {ver}, в lock {locked[name]}")
    for name, ver in sorted(locked.items()):
        if name not in installed:
            problems.append(f"  - {name}=={ver} есть в lock, но не установлен")

    if problems:
        print(f"Установленный набор разошёлся с {lock_path}:")
        print("\n".join(problems))
        print(
            "Обновите lock: соберите образ из requirements.txt и замените файл выводом "
            "`pip freeze` (см. шапку requirements.lock)."
        )
        return 1
    print(f"OK: {len(installed)} пакетов совпадают с {lock_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
