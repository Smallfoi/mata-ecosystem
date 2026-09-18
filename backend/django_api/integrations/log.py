"""Запись в журнал обмена с 1С.

Отдельный модуль, чтобы приём данных не зависел от журнала: если запись почему-то
не удалась, обмен всё равно должен завершиться успешно — потерять выгрузку из-за
не записанной строчки истории было бы худшим разменом.
"""
import time

from django.core.cache import cache

from .models import OneCExchange


def _status(result: dict, detail: str) -> str:
    if detail:
        return "error"
    if result.get("errors"):
        return "partial"
    return "ok"


def record(operation: str, result: dict | None = None, *,
           detail: str = "", started: float | None = None) -> None:
    """Оставить строку в журнале. Никогда не роняет обмен."""
    result = result or {}
    try:
        OneCExchange.objects.create(
            operation=operation,
            status=_status(result, detail),
            received=int(result.get("received") or 0),
            created_count=int(result.get("created") or 0),
            updated_count=int(result.get("updated") or 0),
            skipped=int(result.get("skipped") or 0),
            kept_by_owner=list(result.get("keptByOwner") or []),
            errors=list(result.get("errors") or []),
            duration_ms=int((time.monotonic() - started) * 1000) if started else 0,
            detail=detail[:200],
            sample=result.get("sample") or {},
            unknown_keys=list(result.get("unknownKeys") or [])[:30],
        )
        # Чистка старых записей — раз в сутки, на первом же обмене.
        if cache.add("onec_log_pruned", 1, 24 * 3600):
            OneCExchange.prune()
    except Exception:  # журнал не важнее самого обмена
        pass
