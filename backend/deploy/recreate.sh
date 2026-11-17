# shellcheck shell=bash
# Пересоздание web/worker/beat, которое не роняет сайт. Подключается через `source`.
#
# 15.11.2026: `up -d --force-recreate` упал на `Conflict. The container name
# "/3674aa0ab4ca_backend-worker-1" is already in use`. Такое имя compose даёт старому
# контейнеру на время пересоздания; прерванное пересоздание оставляет его висеть, и
# следующее спотыкается. Скрипт вышел с ошибкой до `nginx -s reload`, а web уже
# получил новый адрес — сайт ~5 минут отдавал 502.
#
#   compose_up_app "<команда compose>" <аргументы up -d...>
#       при конфликте имён убирает застрявшие контейнеры и пробует ещё раз;
#   nginx_reload "<команда compose>"
#       перечитать nginx (web пересоздан → новый IP; без этого 502). Не падает.

stale_app_containers() {  # ID контейнеров вида <12 hex>_backend-web|worker|beat-N
  docker ps -a --format '{{.ID}} {{.Names}}' 2>/dev/null \
    | awk '$2 ~ /^[0-9a-f]{12}_[A-Za-z0-9-]+-(web|worker|beat)-[0-9]+$/ {print $1}'
}

compose_up_app() {
  local compose="$1"; shift
  local out stale
  if out="$($compose up -d "$@" 2>&1)"; then
    printf '%s\n' "$out"; return 0
  fi
  printf '%s\n' "$out"
  printf '%s' "$out" | grep -q 'is already in use by container' || return 1
  stale="$(stale_app_containers)"
  if [ -n "$stale" ]; then
    echo "Застрявшие контейнеры от прерванного пересоздания — убираю: $(echo "$stale" | tr '\n' ' ')"
    # shellcheck disable=SC2086
    docker rm -f $stale >/dev/null 2>&1 || true
  fi
  echo "Повторный запуск…"
  $compose up -d "$@"
}

nginx_reload() {
  local compose="$1"
  $compose exec -T nginx nginx -s reload < /dev/null 2>/dev/null \
    || $compose up -d nginx < /dev/null || echo "WARN: nginx не перечитан — проверьте сайт"
}
