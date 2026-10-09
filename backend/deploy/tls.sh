#!/usr/bin/env bash
# TLS-сертификаты Let's Encrypt для прод-nginx STAW (бесплатно, автообновление).
# Запускать НА СЕРВЕРЕ из каталога backend/ (домен уже должен указывать A-записью на IP):
#   ./deploy/tls.sh issue   — первый выпуск (nginx останавливается на ~минуту, порт 80 нужен certbot)
#   ./deploy/tls.sh renew   — обновление БЕЗ простоя (ACME-проверка через nginx), в cron раз в неделю
set -euo pipefail

cd "$(dirname "$0")/.."  # → backend/
[ -f .env ] || { echo "Нет .env (см. .env.prod.example)"; exit 1; }
set -a; . ./.env; set +a

DOMAIN="${TLS_DOMAIN:-}"
EMAIL="${TLS_EMAIL:-}"
[ -n "$DOMAIN" ] || { echo "ОШИБКА: задай TLS_DOMAIN в .env (напр. api.mata-club.ru)"; exit 1; }
[ -n "$EMAIL" ]  || { echo "ОШИБКА: задай TLS_EMAIL в .env (куда слать письма об истечении)"; exit 1; }

COMPOSE="docker compose -f docker-compose.prod.yml --env-file .env"
# Состояние certbot — на ПОСТОЯННОМ диске (если смонтирован), чтобы сертификат пережил
# пересоздание ВМ и НЕ перевыпускался каждый раз (иначе упираемся в лимиты ACME/LE).
# Каталог данных (на VPS без отдельного диска — /mnt/data на системном, D-115): серт живёт
# рядом с БД и переживает повторный деплой, который пересоздаёт /opt/mata.
if mountpoint -q /mnt/data 2>/dev/null || [ -d /mnt/data/pgdata ]; then
  LE_DIR="/mnt/data/letsencrypt"
else
  LE_DIR="$PWD/nginx/letsencrypt"
fi
WEBROOT="$PWD/nginx/certbot-www"   # сюда certbot кладёт файл ACME-проверки, его отдаёт nginx
CERTS="$PWD/nginx/certs"           # отсюда nginx читает fullchain.pem/privkey.pem
mkdir -p "$LE_DIR" "$WEBROOT" "$CERTS"

# Разложить свежий сертификат туда, где его ждёт nginx (в live/ лежат симлинки → cp -L).
install_certs() {
  local live="$LE_DIR/live/$DOMAIN"
  [ -f "$live/fullchain.pem" ] || { echo "ОШИБКА: сертификат не найден в $live"; exit 1; }
  cp -L "$live/fullchain.pem" "$CERTS/fullchain.pem"
  cp -L "$live/privkey.pem"   "$CERTS/privkey.pem"
  chmod 600 "$CERTS/privkey.pem"
  echo "Сертификаты разложены в nginx/certs/."
}

case "${1:-}" in
  issue)
    # Домены серта: основной + список из TLS_EXTRA_SAN (через запятую).
    EXTRA=""; for d in $(echo "${TLS_EXTRA_SAN:-}" | tr ',' ' '); do EXTRA="$EXTRA -d $d"; done
    # Переиспускаем ТОЛЬКО если существующий серт покрывает ВСЕ нужные домены
    # (иначе — расширяем: добавился сайт-домен). Так бережём лимиты ACME и не дёргаем nginx зря.
    NEED_ISSUE=1
    if [ -f "$LE_DIR/live/$DOMAIN/fullchain.pem" ]; then
      MISSING=0
      for d in "$DOMAIN" $(echo "${TLS_EXTRA_SAN:-}" | tr ',' ' '); do
        openssl x509 -in "$LE_DIR/live/$DOMAIN/fullchain.pem" -noout -text 2>/dev/null | grep -q "DNS:$d" || MISSING=1
      done
      [ "$MISSING" = 0 ] && NEED_ISSUE=0
    fi
    if [ "$NEED_ISSUE" = 0 ]; then
      echo "Серт уже покрывает все домены — переиспользую без перевыпуска."
      install_certs; $COMPOSE up -d nginx; exit 0
    fi
    echo "Выпуск/расширение сертификата ($DOMAIN${EXTRA}) — nginx остановится на ~минуту…"
    $COMPOSE stop nginx 2>/dev/null || true
    ACME_LE="${ACME_SERVER:-https://acme-v02.api.letsencrypt.org/directory}"   # LE (по умолчанию)
    ACME_ZS="https://acme.zerossl.com/v2/DV90"                                  # запасной CA
    # --dns: форсируем публичные резолверы. --expand: добавить новые домены к серту.
    issue_le() {
      docker run --rm -p 80:80 --dns 8.8.8.8 --dns 1.1.1.1 -v "$LE_DIR:/etc/letsencrypt" certbot/certbot \
        certonly --standalone --non-interactive --agree-tos --expand -m "$EMAIL" --server "$ACME_LE" -d "$DOMAIN" $EXTRA
    }
    issue_zerossl() {
      docker run --rm -p 80:80 --dns 8.8.8.8 --dns 1.1.1.1 -v "$LE_DIR:/etc/letsencrypt" certbot/certbot \
        certonly --standalone --non-interactive --agree-tos --expand -m "$EMAIL" --server "$ACME_ZS" \
        --eab-kid "${ZEROSSL_EAB_KID:-}" --eab-hmac-key "${ZEROSSL_EAB_HMAC:-}" -d "$DOMAIN" $EXTRA
    }
    if issue_le || { echo "LE не выдал (лимит?) — пробую ZeroSSL…"; issue_zerossl; }; then
      install_certs
    else
      echo "Выпуск не удался — оставляю ПРЕЖНИЙ серт (API не должен падать)."
      [ -f "$LE_DIR/live/$DOMAIN/fullchain.pem" ] && install_certs || echo "Серта нет — nginx не поднимется до успешного выпуска."
    fi
    $COMPOSE up -d nginx
    echo "Готово. Проверь: curl -I https://$DOMAIN/v1/health"
    ;;
  renew)
    # Обновление — webroot: nginx продолжает работать, отдавая /.well-known/acme-challenge/.
    # Если до истечения больше 30 дней, certbot ничего не делает и выходит с кодом 0.
    docker run --rm -v "$LE_DIR:/etc/letsencrypt" -v "$WEBROOT:/var/www/certbot" \
      certbot/certbot renew --webroot -w /var/www/certbot --non-interactive
    install_certs
    $COMPOSE exec -T nginx nginx -s reload
    echo "Обновление завершено, nginx перечитал конфигурацию."
    ;;
  *)
    echo "Использование: $0 {issue|renew}"
    exit 1
    ;;
esac
