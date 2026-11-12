"""Свежесть резервных копий — для /v1/health и внешнего мониторинга.

Почему это нужно: с конца августа по 28.09.2026 ночные дампы молча не доходили до
бакета — заметили только на аудите. А `pgbr.sh backup` без настроенного pgBackRest
пишет «пропуск» и выходит с кодом 0, крон доволен. Сбой бэкапа не должен быть тихим.

Два источника правды:
- отметки `BackupMark` — их ставят скрипты бэкапа ПОСЛЕ удачной выгрузки в хранилище
  (`dump:1`/`dump:2` — ночной pg_dump в Яндекс/Timeweb, `pgbr:1`/`pgbr:2` — копия
  pgBackRest). Копии суточные: отметка старше `MAX_AGE` = копия не легла;
- `pg_stat_archiver` самого PostgreSQL — непрерывная отправка журнала (WAL). Если
  последняя неудача свежее последнего успеха — архив сейчас не пишется, и восстановить
  «на минуту до аварии» уже нельзя. Скрипты для этого не нужны.

Каких копий ждать, решает конфигурация: хранилище задано в .env (`BACKUP_S3_BUCKET`,
`BACKUP2_S3_BUCKET`) → ждём его дамп; плюс включён `archive_mode` → ждём и pgBackRest.
Отметки, которой ещё нет, заводим «сейчас»: отсчёт пошёл, и если за `MAX_AGE` первая
копия так и не ляжет — это тоже тревога (а не вечное «ещё не было»).

Наружу уходят только имена (`dump:2`, `wal`) — без времени, путей и бакетов.
"""
import os
from datetime import timedelta

from django.db import connection
from django.utils import timezone

# Копии ночные (дамп 04:00 UTC, pgBackRest 03:30 UTC): сутки + запас на долгую выгрузку.
MAX_AGE = timedelta(hours=26)

STORES = (
    # (номер хранилища, переменная .env, по которой видно, что оно подключено)
    ("1", "BACKUP_S3_BUCKET"),
    ("2", "BACKUP2_S3_BUCKET"),
)

KINDS = ("dump", "pgbr")


def _archive_mode_on() -> bool:
    if connection.vendor != "postgresql":
        return False
    with connection.cursor() as cur:
        cur.execute("SHOW archive_mode")
        return (cur.fetchone() or [""])[0] in ("on", "always")


def expected_marks(env, *, archive_on: bool) -> list[str]:
    """Какие отметки должны обновляться при текущей конфигурации."""
    names = []
    for kind in KINDS:
        if kind == "pgbr" and not archive_on:
            continue
        for repo, var in STORES:
            if (env.get(var) or "").strip():
                names.append(f"{kind}:{repo}")
    return names


def wal_failing() -> bool:
    """Отправка WAL сейчас не работает: последняя неудача свежее последнего успеха."""
    if connection.vendor != "postgresql":
        return False
    with connection.cursor() as cur:
        cur.execute("SELECT last_archived_time, last_failed_time FROM pg_stat_archiver")
        row = cur.fetchone()
    if not row:
        return False
    archived, failed = row
    return failed is not None and (archived is None or failed > archived)


def backup_warnings(env=None, *, debug=None, now=None) -> list[str]:
    """Имена копий, которые устарели или не пишутся. Пусто в dev и при ошибке проверки."""
    from core.models import BackupMark

    env = os.environ if env is None else env
    if debug is None:
        debug = env.get("DJANGO_DEBUG", "1") == "1"
    if debug:
        return []
    now = now or timezone.now()
    try:
        archive_on = _archive_mode_on()
        expected = expected_marks(env, archive_on=archive_on)
        marks = {m.name: m.at for m in BackupMark.objects.filter(name__in=expected)}
        stale = []
        for name in expected:
            at = marks.get(name)
            if at is None:
                # Первая встреча: запускаем отсчёт, тревога — если за MAX_AGE копия не ляжет.
                BackupMark.objects.get_or_create(name=name, defaults={"at": now})
            elif now - at > MAX_AGE:
                stale.append(name)
        if archive_on and wal_failing():
            stale.append("wal")
        return stale
    except Exception:  # health не должен падать из-за проверки бэкапов
        return ["check-failed"]


def mark(name: str, now=None) -> None:
    """Отметить удачную копию (зовут скрипты через `manage.py backup_mark`)."""
    from core.models import BackupMark

    kind, _, repo = name.partition(":")
    if kind not in KINDS or repo not in {r for r, _ in STORES}:
        raise ValueError(f"неизвестная копия: {name!r} (ждём dump:1|dump:2|pgbr:1|pgbr:2)")
    BackupMark.objects.update_or_create(name=name, defaults={"at": now or timezone.now()})
