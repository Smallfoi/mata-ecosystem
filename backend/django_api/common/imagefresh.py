"""Сторож свежести образа: установленные пакеты против requirements.txt.

Зачем. Код в dev монтируется томом (`./django_api:/app`), а пакеты ставятся при
`build`. Поэтому новая строка в `requirements.txt` доезжает до контейнера только
после `docker compose up -d --build`. Правило «добавил зависимость — пересобери
образ» записано в PITFALLS, но за год не сработало трижды: `celery` (D-07),
`django-otp` (после мержа 2FA, D-49) и `cryptography` (после Play Integrity,
D-129). Каждый раз это выглядело не как устаревший образ, а как сломанный код:
шесть красных тестов в `attestation`, и настоящая причина — одна строка
`ModuleNotFoundError` в глубине трейсбека одного из них.

Правило, которое трижды не сработало, — задача для кода, а не ещё один абзац в
PITFALLS. Проверка зарегистрирована как системная (`django.core.checks`), поэтому
она срабатывает ДО тестов и до поднятия сервера — `manage.py test`, `runserver`,
`check` — и называет, чего именно не хватает.

Что НЕ проверяем: версии. Боль была ровно одна — пакета нет совсем. Сверка версий
кричала бы на каждом расхождении патча и быстро научила бы не читать эти строки.
"""
import re
from importlib.metadata import PackageNotFoundError
from importlib.metadata import distribution
from pathlib import Path

REQUIREMENTS = Path(__file__).resolve().parent.parent / "requirements.txt"

# Имя пакета в начале строки: до спецификатора версии, экстр и комментария.
# `psycopg[binary]>=3.1` → `psycopg`; `sentry-sdk[django]>=2.0` → `sentry-sdk`.
_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def required_names(text: str) -> list:
    """Имена пакетов из текста requirements.txt — без версий, экстр и комментариев.

    Пропускаем всё, что не является обычной строкой-зависимостью: комментарии,
    пустые строки, флаги pip (`-r`, `--hash`), ссылки на git/файлы и строки с
    маркерами окружения (`; python_version < "3.12"`) — последние могут быть
    законно не установлены на этой машине.
    """
    out = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-") or ";" in line:
            continue
        if "://" in line or line.startswith("."):
            continue
        found = _NAME.match(line)
        if found:
            out.append(found.group(1))
    return out


def missing(names, installed=None) -> list:
    """Какие из этих пакетов не установлены в текущем окружении."""
    def present(name):
        try:
            distribution(name)
            return True
        except PackageNotFoundError:
            return False

    check = present if installed is None else (lambda n: n in installed)
    return [n for n in names if not check(n)]


def stale_report() -> list:
    """Пустой список — образ свежий. Иначе имена недостающих пакетов."""
    try:
        text = REQUIREMENTS.read_text(encoding="utf-8")
    except OSError:
        return []  # requirements рядом нет (чужая сборка) — молчим, не мешаем
    return missing(required_names(text))
