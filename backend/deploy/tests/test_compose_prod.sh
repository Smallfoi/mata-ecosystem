#!/usr/bin/env bash
# Проверка docker-compose.prod.yml (аудит E04, E05) через `docker compose config`
# с фиктивным .env — ничего не запускает, только разбирает итоговую конфигурацию.
#  E04: брокер Celery — отдельный Redis с noeviction; web/worker/beat смотрят в него,
#       кэш (redis, allkeys-lru) брокером не является.
#  E05: у web/worker/beat есть healthcheck (готовность — условие успешного деплоя).
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$(cd "$HERE/../.." && pwd)"
command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1 || {
  echo "SKIP: нет docker compose"; exit 0; }
PY="$(command -v python3 || command -v python)"
BASE="${DEPLOY_TEST_TMP:-$(mktemp -d)}"
mkdir -p "$BASE"
ENVF="$(mktemp "$BASE/compose-env.XXXXXX")"
cat > "$ENVF" <<'EOF'
POSTGRES_DB=mata
POSTGRES_USER=mata
POSTGRES_PASSWORD=dummy
REDIS_URL=redis://redis:6379/0
DJANGO_ALLOWED_HOSTS=api.example.test
EOF
JSON="$BASE/compose.json"
# env_file: .env у сервисов — подсовываем фиктивный через --env-file и копию-ссылку не делаем:
# config проверяет наличие .env рядом с compose, поэтому кладём временный, если его нет.
created_env=0
if [ ! -f "$BACKEND/.env" ]; then cp "$ENVF" "$BACKEND/.env"; created_env=1; fi
docker compose -p mata-config-check -f "$BACKEND/docker-compose.prod.yml" --env-file "$ENVF" \
  config --format json > "$JSON"; rc=$?
[ "$created_env" = 1 ] && rm -f "$BACKEND/.env"
[ "$rc" = 0 ] || { echo "FAIL: docker compose config (код $rc)"; exit 1; }

PYTHONIOENCODING=utf-8 "$PY" - "$JSON" <<'PY'
import json, sys
cfg = json.load(open(sys.argv[1], encoding="utf-8"))
svc = cfg["services"]
fails = []
def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)

def cmd(name):
    c = svc.get(name, {}).get("command") or []
    return " ".join(c) if isinstance(c, list) else str(c)

print("E04: отдельный брокер Celery с noeviction")
check("redis-broker" in svc, "есть сервис redis-broker")
check("noeviction" in cmd("redis-broker"), "redis-broker: --maxmemory-policy noeviction")
check("allkeys-lru" in cmd("redis"), "кэш redis остаётся allkeys-lru")
for name in ("web", "worker", "beat"):
    env = svc[name].get("environment") or {}
    url = env.get("CELERY_BROKER_URL", "")
    check(url.startswith("redis://redis-broker:"), f"{name}: CELERY_BROKER_URL → redis-broker ({url or 'не задан'})")
    dep = (svc[name].get("depends_on") or {}).get("redis-broker", {})
    check(dep.get("condition") == "service_healthy", f"{name}: ждёт healthy redis-broker")

print("E05: healthcheck у web/worker/beat")
for name in ("web", "worker", "beat"):
    hc = svc[name].get("healthcheck") or {}
    test = hc.get("test") or []
    check(bool(test) and not hc.get("disable"), f"{name}: healthcheck задан")
check("/v1/health/ready" in " ".join(svc["web"].get("healthcheck", {}).get("test") or []),
      "web: проверка по /v1/health/ready")
check("inspect ping" in " ".join(svc["worker"].get("healthcheck", {}).get("test") or []),
      "worker: celery inspect ping")
sys.exit(1 if fails else 0)
PY
rc=$?
[ -z "${DEPLOY_TEST_TMP:-}" ] && rm -rf "$BASE"
[ "$rc" = 0 ] && echo "test_compose_prod: OK" || { echo "test_compose_prod: провал"; exit 1; }
