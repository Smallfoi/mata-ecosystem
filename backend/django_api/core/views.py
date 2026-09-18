from datetime import datetime, timezone

from django.core.cache import cache
from django.db import connection
from rest_framework.decorators import api_view, throttle_classes
from rest_framework.response import Response


def _db_ok():
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        return True
    except Exception:
        return False


def _cache_ok():
    """Round-trip в кэш (в проде — Redis; в dev — LocMem, всегда ok)."""
    try:
        cache.set("_health_probe", "1", 5)
        return cache.get("_health_probe") == "1"
    except Exception:
        return False


@api_view(["GET"])
@throttle_classes([])  # health опрашивают часто (мониторинг/балансировщик) — не троттлим
def health(_request):
    """Liveness: процесс жив + доступность БД/кэша. Контракт сохранён (status/service/db/time),
    поле `cache` добавлено (не ломает клиентов). status привязан к БД для обратной совместимости."""
    db_ok = _db_ok()
    return Response(
        {
            "status": "ok" if db_ok else "degraded",
            "service": "mata-ecosystem-django",
            "db": db_ok,
            "cache": _cache_ok(),
            "time": datetime.now(timezone.utc).isoformat(),
        }
    )


@api_view(["GET"])
@throttle_classes([])  # конфиг тянут на старте/резюме — не троттлим
def app_config(_request):
    """Серверные флаги видимости (D-89): что показывать в приложении. Публично,
    без токена — это UI-конфиг, не персональные данные. Клиент кэширует ответ и
    имеет свои дефолты на случай недоступности сети."""
    from core.models import AppConfig

    return Response(AppConfig.load().to_json())


@api_view(["GET"])
@throttle_classes([])
def readiness(_request):
    """Readiness: готов ли инстанс принимать трафик (БД И кэш живы). Для балансировщика/
    k8s: 200 если готов, 503 если нет — тогда инстанс выводят из ротации."""
    db_ok, cache_ok = _db_ok(), _cache_ok()
    ready = db_ok and cache_ok
    return Response(
        {"ready": ready, "db": db_ok, "cache": cache_ok},
        status=200 if ready else 503,
    )
