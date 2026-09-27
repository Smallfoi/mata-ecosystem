"""Защита от запуска в проде с небезопасной конфигурацией (P0 безопасность).

Самая частая катастрофа запуска — выкатить прод с дефолтными секретами из репо:
тогда `JWT_SECRET`/`DJANGO_SECRET_KEY` известны всем → любой подделывает токен
кого угодно. Эта проверка вызывается из settings и НЕ ДАЁТ приложению стартовать,
если `DEBUG=0`, а критичные секреты всё ещё дефолтные (или `ALLOWED_HOSTS=*`).
В dev (`DEBUG=1`) ничего не мешает — список пустой."""

_DEV_SECRET = "dev-secret-change-in-prod"
_DEV_DB_PASSWORD = "kvartal"


def insecure_prod_settings(
    *, debug, secret_key, jwt_secret, db_password, allowed_hosts
):
    """Список небезопасных для прода настроек (пусто = можно стартовать)."""
    if debug:
        return []
    bad = []
    if secret_key == _DEV_SECRET:
        bad.append("DJANGO_SECRET_KEY")
    if jwt_secret == _DEV_SECRET:
        bad.append("JWT_SECRET")
    if db_password == _DEV_DB_PASSWORD:
        bad.append("POSTGRES_PASSWORD")
    if not allowed_hosts or "*" in allowed_hosts:
        bad.append("DJANGO_ALLOWED_HOSTS")
    return bad


# ── Полный отчёт о прод-конфигурации (аудит D09) ─────────────────────────────
# Без REDIS_URL настройки молча уходили в dev-поведение: кэш LocMem (у каждого воркера
# gunicorn свой — лимиты входа, коды OTP и мгновенный бан перестают быть общими) и
# Celery EAGER (фоновые задачи выполняются прямо в запросе, beat не работает — чистка
# данных по 152-ФЗ не идёт). Без DJANGO_CORS_ORIGINS API открыт для любых сайтов.
#
# Отказ старта — ТОЛЬКО для переменных, которые прод-скрипты кладут в .env всегда
# (статический блок `deploy/prod-deploy.sh` и `deploy/refresh-env.sh`, тот же в
# `cloud-init-prod.yaml`): REDIS_URL, DJANGO_CORS_ORIGINS, плюс проверенные в самих
# скриптах POSTGRES_PASSWORD/DJANGO_SECRET_KEY/JWT_SECRET. Их отсутствие на проде —
# поломка деплоя, а не «ещё не подключили».
#
# Остальное приходит из Lockbox и может законно отсутствовать (интеграция ещё не
# заведена) — это ПРЕДУПРЕЖДЕНИЯ: громкая строка в логе при старте и поле в
# /v1/health, но не простой прода.

# Интеграции, без которых прод работает, но в опасном/слепом режиме.
_WARN_CHECKS = (
    # Без провайдера вход по коду в dev-режиме (код 1234) — вход в чужой аккаунт.
    ("SMS_PROVIDER", lambda env: bool(_get(env, "SMS_PROVIDER"))),
    # Без Sentry/GlitchTip ошибки прода никто не видит (D-25/D-32).
    ("SENTRY_DSN", lambda env: bool(_get(env, "SENTRY_DSN"))),
    # Без S3 загрузки лежат на диске ВМ и пропадут при её пересоздании (D-31).
    ("MEDIA_S3_BUCKET", lambda env: all(
        _get(env, k) for k in ("MEDIA_S3_BUCKET", "MEDIA_S3_ACCESS_KEY", "MEDIA_S3_SECRET_KEY")
    )),
)


def _get(env, name):
    return str(env.get(name) or "").strip()


def prod_config_report(env, *, debug):
    """{"fatal": [...], "warnings": [...]} — имена переменных (без значений).

    `fatal` — прод не стартует (см. комментарий выше); `warnings` — стартует, но
    громко сообщает. В dev (debug=True) оба списка пусты.
    """
    if debug:
        return {"fatal": [], "warnings": []}
    fatal = insecure_prod_settings(
        debug=False,
        secret_key=_get(env, "DJANGO_SECRET_KEY") or _DEV_SECRET,
        jwt_secret=_get(env, "JWT_SECRET") or _DEV_SECRET,
        db_password=_get(env, "POSTGRES_PASSWORD") or _DEV_DB_PASSWORD,
        allowed_hosts=[h.strip() for h in _get(env, "DJANGO_ALLOWED_HOSTS").split(",") if h.strip()]
        or ["*"],
    )
    # Брокер берётся из REDIS_URL, если CELERY_BROKER_URL не задан (settings.py):
    # без обоих — LocMem-кэш и EAGER-задачи.
    if not _get(env, "REDIS_URL"):
        fatal.append("REDIS_URL")
    if not _get(env, "DJANGO_CORS_ORIGINS"):
        fatal.append("DJANGO_CORS_ORIGINS")
    warnings = [name for name, ok in _WARN_CHECKS if not ok(env)]
    return {"fatal": fatal, "warnings": warnings}


def config_warnings():
    """Предупреждения текущего процесса (для /v1/health). Пусто в dev."""
    import os

    debug = os.environ.get("DJANGO_DEBUG", "1") == "1"
    return prod_config_report(os.environ, debug=debug)["warnings"]
