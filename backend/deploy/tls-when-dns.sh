#!/usr/bin/env bash
# Выпустить TLS, как только DNS всех доменов укажет на ЭТОТ сервер (крон раз в 5 минут).
# Запуск НА СЕРВЕРЕ из backend/:  ./deploy/tls-when-dns.sh
#
# Зачем: новый сервер (другая зона, другой IP) поднимается раньше, чем владелец переведёт
# A-записи у регистратора. Выпуск до этого бесполезен и вреден: каждая неудачная проверка
# Let's Encrypt идёт в лимит «5 неудач в час на домен». Поэтому сначала сверяем DNS.
# Сертификат уже есть — ничего не делаем (продление — отдельным кроном `tls.sh renew`).
set -uo pipefail

cd "$(dirname "$0")/.." || exit 0  # → backend/
[ -f .env ] || exit 0
set -a; . ./.env; set +a

[ -f nginx/certs/fullchain.pem ] && exit 0
[ -n "${PUBLIC_IP:-}" ] || { echo "PUBLIC_IP не задан в .env — не с чем сверять DNS"; exit 0; }

for d in ${TLS_DOMAIN:-} $(printf '%s' "${TLS_EXTRA_SAN:-}" | tr ',' ' '); do
  got=$(python3 -c 'import socket,sys
try:
    print(" ".join(sorted({a[4][0] for a in socket.getaddrinfo(sys.argv[1], 443, socket.AF_INET)})))
except Exception:
    print("")' "$d")
  if [ "$got" != "$PUBLIC_IP" ]; then
    echo "$(date -u '+%F %T') DNS $d → '${got:-нет}', а сервер $PUBLIC_IP — жду перевода записей"
    exit 0
  fi
done

echo "$(date -u '+%F %T') DNS всех доменов указывает на $PUBLIC_IP — выпускаю сертификат"
./deploy/tls.sh issue
