#!/usr/bin/env bash
# Остатки GlitchTip на прод-ВМ (D-122) — после переезда на свою ВМ (D-132, 17.11.2026).
#
# GlitchTip живёт на отдельной ВМ в Яндексе (deploy/glitchtip-host.sh, 153.51.171.179).
# На проде от него остались остановленные контейнеры, тома (база событий — в ней могут быть
# персональные данные), секреты /root/mata-glitchtip.env и копии файла ключей. Стереть —
# одна команда на сервере (магазин не затрагивает):
#
#   sudo bash /opt/mata/backend/deploy/glitchtip.sh purge
#
# Ключи, по которым магазин шлёт ошибки (SENTRY_DSN, GLITCHTIP_*), остаются в
# /root/mata-server-keys.env — их эта команда не трогает.
set -euo pipefail

cd "$(dirname "$0")/.."   # → backend/
[ -f .env ] || { echo "Нет .env — это не каталог прод-бэкенда"; exit 1; }

case "${1:-}" in
  purge)
    project="mata-glitchtip"
    ids="$(docker ps -aq --filter "label=com.docker.compose.project=$project")"
    [ -z "$ids" ] || docker rm -f $ids
    vols="$(docker volume ls -q --filter "label=com.docker.compose.project=$project")"
    [ -z "$vols" ] || docker volume rm $vols
    docker network rm "${project}_default" >/dev/null 2>&1 || true
    docker image rm glitchtip/glitchtip:6.2.6 postgres:16.14-alpine3.23 >/dev/null 2>&1 || true
    rm -f /root/mata-glitchtip.env glitchtip.env nginx/extra/glitchtip.conf
    rm -rf nginx/certs/errors
    # Копии файла ключей от connect/move: в них прежний внутренний адрес — больше не нужны.
    rm -f /root/mata-server-keys.env.bak-*
    echo "Готово: остатков GlitchTip на проде нет. Магазин шлёт ошибки на https://errors.mata-club.ru."
    ;;
  *)
    sed -n '2,13p' "$0"
    exit 1
    ;;
esac
