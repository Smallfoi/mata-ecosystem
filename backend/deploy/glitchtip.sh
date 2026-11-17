#!/usr/bin/env bash
# GlitchTip (мониторинг ошибок, D-32/D-122) на прод-ВМ — установка и обслуживание.
#
# ВРЕМЕННО на том же сервере, что и магазин (решение владельца 10.11.2026). Цель —
# отдельная площадка; набор docker-compose.glitchtip.yml переносится как есть.
#
# Запускать на сервере из любого места, под sudo:
#   sudo bash /opt/mata/backend/deploy/glitchtip.sh setup   — секреты, база, миграции, запуск
#   sudo bash /opt/mata/backend/deploy/glitchtip.sh tls     — сертификат и адрес errors.mata-club.ru
#                                                            (после A-записи DNS на этот сервер)
#   sudo bash /opt/mata/backend/deploy/glitchtip.sh admin   — создать первого пользователя (спросит
#                                                            почту и пароль)
#   sudo bash /opt/mata/backend/deploy/glitchtip.sh connect — проекты, ключи и токен; подключить магазин
#   sudo bash /opt/mata/backend/deploy/glitchtip.sh status  — живы ли контейнеры, сколько едят памяти
#   sudo bash /opt/mata/backend/deploy/glitchtip.sh stop    — остановить (магазин не затрагивает)
#   sudo bash /opt/mata/backend/deploy/glitchtip.sh move    — переезд на свою ВМ (D-132): база →
#                                                            бакет, магазин → внешний адрес
#
# Магазин не трогаем: своя база и свои контейнеры, общий только nginx. Блок nginx для
# errors.mata-club.ru появляется лишь после успешного выпуска сертификата и проверки
# `nginx -t`; не прошла проверка — блок убираем, nginx остаётся на прежнем конфиге.
set -euo pipefail

cd "$(dirname "$0")/.."   # → backend/
[ -f .env ] || { echo "Нет .env — это не каталог прод-бэкенда"; exit 1; }

DOMAIN="errors.mata-club.ru"
# Секреты GlitchTip живут ВНЕ рабочей копии: повторный деплой магазина пересоздаёт
# /opt/mata, а этот файл должен пережить его (как /root/mata-secrets.env, D-115).
SECRETS="${GLITCHTIP_SECRETS_FILE:-/root/mata-glitchtip.env}"
ENVF="glitchtip.env"   # копия для docker compose (в .gitignore — репозиторий публичный)
GT=(docker compose -f docker-compose.glitchtip.yml --env-file "$ENVF")
PROD=(docker compose -f docker-compose.prod.yml --env-file .env)

dotenv() {   # значение ключа из .env магазина (без кавычек)
  sed -n "s/^$1=//p" .env | head -n 1 | sed -e "s/^'//" -e "s/'$//" -e 's/^"//' -e 's/"$//'
}

prod_network() {   # сеть, в которой живёт nginx магазина
  local id
  id="$("${PROD[@]}" ps -q nginx 2>/dev/null | head -n 1)"
  [ -n "$id" ] || { echo "nginx магазина не запущен — сначала подними прод" >&2; return 1; }
  docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{$k}}{{"\n"}}{{end}}' "$id" | head -n 1
}

make_secrets() {
  local net secret dbpass email_url from
  net="$(prod_network)"
  secret="$(openssl rand -hex 32)"
  dbpass="$(openssl rand -hex 24)"
  # Почта для писем об ошибках — тот же SMTP, что у писем покупателям (D-111). Логин и
  # пароль кодируем для URL: иначе символы вроде @ / $ сломали бы адрес или compose.
  email_url="$(EH="$(dotenv EMAIL_HOST)" EP="$(dotenv EMAIL_PORT)" EU="$(dotenv EMAIL_HOST_USER)" \
    EW="$(dotenv EMAIL_HOST_PASSWORD)" ES="$(dotenv EMAIL_USE_SSL)" python3 - <<'PY'
import os
from urllib.parse import quote
host = os.environ.get("EH", "")
if not host or host == "localhost":
    print("consolemail://")      # почты нет — письма в лог, остальное работает
else:
    port = os.environ.get("EP") or "465"
    scheme = "smtp+ssl" if (os.environ.get("ES") or "1") == "1" else "smtp+tls"
    user = quote(os.environ.get("EU", ""), safe="")
    pw = quote(os.environ.get("EW", ""), safe="")
    print(f"{scheme}://{user}:{pw}@{host}:{port}")
PY
)"
  from="$(dotenv EMAIL_HOST_USER)"; [ -n "$from" ] || from="noreply@mata-club.ru"
  umask 077
  cat > "$SECRETS" <<EOF
# GlitchTip МАТА — секреты (создано deploy/glitchtip.sh $(date -u +%Y-%m-%dT%H:%MZ)).
GLITCHTIP_DB_PASSWORD=$dbpass
DATABASE_URL=postgres://glitchtip:$dbpass@glitchtip-db:5432/glitchtip
SECRET_KEY=$secret
GLITCHTIP_DOMAIN=https://$DOMAIN
ALLOWED_HOSTS=$DOMAIN,glitchtip-web,localhost
CSRF_TRUSTED_ORIGINS=https://$DOMAIN
DEFAULT_FROM_EMAIL=$from
EMAIL_URL=$email_url
ENABLE_USER_REGISTRATION=False
ENABLE_ORGANIZATION_CREATION=False
ENABLE_ADMIN=False
GLITCHTIP_MAX_EVENT_LIFE_DAYS=30
MATA_PROD_NETWORK=$net
EOF
  echo "Секреты GlitchTip созданы: $SECRETS"
}

sync_env() {
  [ -s "$SECRETS" ] || { echo "Нет $SECRETS — сначала: glitchtip.sh setup"; exit 1; }
  install -m 600 "$SECRETS" "$ENVF"
}

wait_healthy() {
  local i
  for i in $(seq 1 60); do
    # Любой HTTP-ответ (даже 404) — сервер поднялся; отказ соединения — ещё нет.
    if "${GT[@]}" exec -T glitchtip python -c "
import urllib.request, urllib.error
try:
    urllib.request.urlopen('http://localhost:8000/', timeout=5)
except urllib.error.HTTPError:
    pass" >/dev/null 2>&1; then
      echo "GlitchTip отвечает (через $((i * 5)) с)."; return 0
    fi
    sleep 5
  done
  echo "GlitchTip не ответил за 5 минут. Последние строки журнала:"
  "${GT[@]}" logs --tail 40 glitchtip || true
  return 1
}

case "${1:-}" in
  setup)
    avail=$(awk '/MemAvailable/ {print int($2 / 1024)}' /proc/meminfo)
    free_disk=$(df -Pm / | awk 'NR == 2 {print $4}')
    echo "Свободно: память ${avail} МБ, диск ${free_disk} МБ."
    # Потолки контейнеров — 700 + 256 МБ. Меньше 1 ГБ свободной памяти — не ставим:
    # GlitchTip не должен вытеснить магазин.
    if [ "$avail" -lt 1000 ] && [ "${GLITCHTIP_FORCE:-0}" != 1 ]; then
      echo "СТОП: свободно меньше 1000 МБ памяти — GlitchTip здесь потеснит магазин."
      echo "Нужна отдельная площадка (или GLITCHTIP_FORCE=1, если уверены)."
      exit 1
    fi
    [ "$free_disk" -ge 5000 ] || { echo "СТОП: на диске меньше 5 ГБ"; exit 1; }
    [ -s "$SECRETS" ] && echo "Секреты уже есть: $SECRETS — не пересоздаю." || make_secrets
    sync_env
    "${GT[@]}" pull
    "${GT[@]}" up -d glitchtip-db
    "${GT[@]}" run --rm glitchtip ./manage.py migrate --noinput
    "${GT[@]}" up -d
    wait_healthy
    # Каталог для блока errors.mata-club.ru. nginx видит его после пересоздания контейнера
    # (новый том в docker-compose.prod.yml) — это пара секунд, не простой магазина.
    mkdir -p nginx/extra nginx/certs/errors
    nginx_id="$("${PROD[@]}" ps -q nginx | head -n 1)"
    if ! docker inspect -f '{{range .Mounts}}{{.Destination}} {{end}}' "$nginx_id" | grep -q /etc/nginx/extra; then
      echo "Пересоздаю nginx магазина, чтобы он увидел каталог nginx/extra…"
      "${PROD[@]}" up -d nginx
    fi
    echo
    echo "ГОТОВО. Дальше:"
    echo "  1) DNS: A-запись $DOMAIN → IP этого сервера ($(dotenv PUBLIC_IP))"
    echo "  2) sudo bash $0 tls"
    echo "  3) sudo bash $0 admin"
    echo "  4) sudo bash $0 connect"
    ;;

  tls)
    sync_env
    ip="$(dotenv PUBLIC_IP)"
    got="$(python3 -c "import socket,sys; print(socket.gethostbyname(sys.argv[1]))" "$DOMAIN" 2>/dev/null || true)"
    if [ -z "$got" ] || { [ -n "$ip" ] && [ "$got" != "$ip" ]; }; then
      echo "СТОП: $DOMAIN указывает на «${got:-ничего}», а сервер — ${ip:-?}. Сначала A-запись в DNS."
      exit 1
    fi
    if mountpoint -q /mnt/data 2>/dev/null || [ -d /mnt/data/pgdata ]; then
      LE_DIR="/mnt/data/letsencrypt"   # тот же каталог, что у deploy/tls.sh
    else
      LE_DIR="$PWD/nginx/letsencrypt"
    fi
    WEBROOT="$PWD/nginx/certbot-www"
    mkdir -p "$LE_DIR" "$WEBROOT" nginx/certs/errors nginx/extra
    # Проверка через работающий nginx (webroot): магазин не останавливаем.
    docker run --rm -v "$LE_DIR:/etc/letsencrypt" -v "$WEBROOT:/var/www/certbot" certbot/certbot \
      certonly --webroot -w /var/www/certbot --non-interactive --agree-tos \
      -m "$(dotenv TLS_EMAIL)" -d "$DOMAIN"
    cp -L "$LE_DIR/live/$DOMAIN/fullchain.pem" nginx/certs/errors/fullchain.pem
    cp -L "$LE_DIR/live/$DOMAIN/privkey.pem" nginx/certs/errors/privkey.pem
    chmod 600 nginx/certs/errors/privkey.pem
    cp nginx/glitchtip.conf.example nginx/extra/glitchtip.conf
    if "${PROD[@]}" exec -T nginx nginx -t; then
      "${PROD[@]}" exec -T nginx nginx -s reload
      echo "Адрес включён: https://$DOMAIN"
    else
      rm -f nginx/extra/glitchtip.conf
      echo "СТОП: nginx -t не прошёл — блок убран, магазин на прежнем конфиге."
      exit 1
    fi
    ;;

  admin)
    sync_env
    echo "Создаём первого пользователя GlitchTip (почта + пароль). Регистрация чужих закрыта."
    "${GT[@]}" exec glitchtip ./manage.py createsuperuser
    ;;

  connect)
    # Проекты backend/apps, ключи и токен для страницы «Ошибки» в админке — одной командой,
    # без ручной работы в интерфейсе GlitchTip. Повторный запуск ничего не дублирует.
    sync_env
    shop_secrets="${MATA_SECRETS_FILE:-/root/mata-secrets.env}"
    [ -s "$shop_secrets" ] || { echo "СТОП: нет $shop_secrets — секреты магазина лежат не там"; exit 1; }
    out="$("${GT[@]}" exec -T glitchtip ./manage.py shell -c "$(cat deploy/glitchtip_connect.py)")"
    if ! printf '%s\n' "$out" | grep -q '^ENV:SENTRY_DSN='; then
      printf '%s\n' "$out" | tail -n 5
      echo "СТОП: GlitchTip не отдал ключи (первый пользователь создан? glitchtip.sh admin)"
      exit 1
    fi
    # Свой файл, а не файл секретов магазина: тот переписывается из Lockbox при каждом
    # обновлении секретов (beget-up.sh SECRETS_ONLY=1) и стирал эти ключи (12.11.2026).
    # refresh-env.sh и prod-deploy.sh добавляют этот файл в .env последним.
    keys_file="${MATA_SERVER_KEYS_FILE:-/root/mata-server-keys.env}"
    [ -s "$keys_file" ] && cp -p "$keys_file" "$keys_file.bak-$(date +%Y%m%d%H%M%S)"
    tmp="$(mktemp)"
    keys="$(printf '%s\n' "$out" | sed -n 's/^ENV:\([A-Z_]*\)=.*/\1/p' | paste -sd'|')"
    if [ -s "$keys_file" ]; then grep -Ev "^(${keys})=" "$keys_file" > "$tmp" || true; fi
    printf '%s\n' "$out" | sed -n 's/^ENV://p' >> "$tmp"
    install -m 600 "$tmp" "$keys_file"; rm -f "$tmp"
    echo "Ключи GlitchTip записаны в $keys_file — их не сотрёт обновление секретов из Lockbox."
    bash deploy/refresh-env.sh
    echo
    echo "Магазин подключён: ошибки бэкенда идут в GlitchTip, страница «Ошибки» в админке живая."
    echo "Для приложений положите в секрет GitHub SENTRY_DSN (Settings → Secrets → Actions):"
    printf '%s\n' "$out" | sed -n 's/^APPS_DSN=/  /p'
    ;;

  move)
    # Переезд на свою ВМ (D-132). Запускать ПОСЛЕ того, как A-запись errors.mata-club.ru
    # указывает на новую ВМ и та отвечает по HTTPS. Делает за один раз:
    #   1) дамп базы GlitchTip + его секреты → шифрует ключом переезда (открытая часть —
    #      deploy/glitchtip-move.crt, закрытая только у Claude) → бакет бэкапов Яндекса;
    #   2) магазин шлёт ошибки и читает список на внешний адрес (ключи DSN прежние);
    #   3) убирает блок errors.mata-club.ru из nginx магазина и останавливает GlitchTip здесь.
    # Тома старого GlitchTip остаются — откат: вернуть A-запись, `glitchtip.sh setup`
    # (секреты на месте) и файл ключей из копии .bak-*.
    sync_env
    cert="deploy/glitchtip-move.crt"
    [ -s "$cert" ] || { echo "СТОП: нет $cert — переезд уже закрыт или код устарел (git pull)"; exit 1; }
    code="$(curl -s -o /dev/null -m 20 -w '%{http_code}' "https://$DOMAIN/_health/" || true)"
    if [ "$code" != 200 ]; then
      echo "СТОП: https://$DOMAIN/_health/ ответил «${code:-нет связи}», нужно 200."
      echo "Сначала A-запись на новую ВМ, и подождите, пока она выпустит сертификат."
      exit 1
    fi
    # Если DNS всё ещё указывает сюда, «200» ответил этот же GlitchTip — переезжать некуда.
    ip="$(dotenv PUBLIC_IP)"
    got="$(python3 -c "import socket,sys; print(socket.gethostbyname(sys.argv[1]))" "$DOMAIN" 2>/dev/null || true)"
    if [ -n "$ip" ] && [ "$got" = "$ip" ]; then
      echo "СТОП: $DOMAIN всё ещё указывает на этот сервер ($ip). Сначала A-запись на новую ВМ."
      exit 1
    fi
    bucket="$(dotenv BACKUP_S3_BUCKET)"
    s3key="$(dotenv BACKUP_S3_ACCESS_KEY)"; [ -n "$s3key" ] || s3key="$(dotenv MEDIA_S3_ACCESS_KEY)"
    s3sec="$(dotenv BACKUP_S3_SECRET_KEY)"; [ -n "$s3sec" ] || s3sec="$(dotenv MEDIA_S3_SECRET_KEY)"
    endpoint="$(dotenv BACKUP_S3_ENDPOINT)"; [ -n "$endpoint" ] || endpoint="https://storage.yandexcloud.net"
    region="$(dotenv BACKUP_S3_REGION)"; [ -n "$region" ] || region="ru-central1"
    [ -n "$bucket" ] && [ -n "$s3key" ] && [ -n "$s3sec" ] || {
      echo "СТОП: в .env нет BACKUP_S3_BUCKET или ключей доступа — некуда выгрузить базу"; exit 1; }

    work="$(mktemp -d)"; trap 'rm -rf "$work"' EXIT
    echo "1/3 Дамп базы GlitchTip…"
    "${GT[@]}" exec -T glitchtip-db pg_dump -U glitchtip -Fc glitchtip > "$work/glitchtip.dump"
    [ -s "$work/glitchtip.dump" ] || { echo "СТОП: дамп пустой"; exit 1; }
    install -m 600 "$SECRETS" "$work/mata-glitchtip.env"
    tar -C "$work" -cf "$work/bundle.tar" glitchtip.dump mata-glitchtip.env
    openssl cms -encrypt -binary -aes256 -outform DER -in "$work/bundle.tar" \
      -out "$work/bundle.cms" "$cert"
    obj="glitchtip-move/$(date -u +%Y%m%dT%H%M%SZ).tar.cms"
    code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 600 \
      --aws-sigv4 "aws:amz:${region}:s3" --user "${s3key}:${s3sec}" \
      --upload-file "$work/bundle.cms" "${endpoint%/}/${bucket}/${obj}" || echo 000)"
    [ "$code" = 200 ] || { echo "СТОП: выгрузка в бакет не удалась (HTTP $code). Магазин не трогали."; exit 1; }
    echo "    выгружено: ${bucket}/${obj} ($(du -h "$work/bundle.cms" | cut -f1), зашифровано)"

    echo "2/3 Магазин → https://$DOMAIN …"
    keys_file="${MATA_SERVER_KEYS_FILE:-/root/mata-server-keys.env}"
    [ -s "$keys_file" ] || { echo "СТОП: нет $keys_file — ключей GlitchTip у магазина нет"; exit 1; }
    cp -p "$keys_file" "$keys_file.bak-$(date +%Y%m%d%H%M%S)"
    sed -i -E \
      -e "s#^(SENTRY_DSN=)http://([^@]+)@glitchtip-web:8000/#\1https://\2@${DOMAIN}/#" \
      -e "s#^GLITCHTIP_API_URL=.*#GLITCHTIP_API_URL=https://${DOMAIN}#" \
      "$keys_file"
    grep -q "^SENTRY_DSN=https://[^@]*@${DOMAIN}/" "$keys_file" || {
      echo "СТОП: SENTRY_DSN не переписался — проверьте $keys_file (копия рядом, .bak-*)"; exit 1; }
    bash deploy/refresh-env.sh

    echo "3/3 Убираю GlitchTip с этого сервера…"
    if [ -f nginx/extra/glitchtip.conf ]; then
      mv nginx/extra/glitchtip.conf "$work/glitchtip.conf.off"
      if "${PROD[@]}" exec -T nginx nginx -t; then
        "${PROD[@]}" exec -T nginx nginx -s reload
      else
        mv "$work/glitchtip.conf.off" nginx/extra/glitchtip.conf
        echo "ВНИМАНИЕ: nginx -t без блока не прошёл — блок оставлен, разберёмся отдельно."
      fi
    fi
    # Сертификат errors.mata-club.ru здесь больше не продлится (адрес смотрит на новую ВМ),
    # а неудачное продление в `tls.sh renew` сорвало бы и продление сертификата API.
    if [ -d /mnt/data/pgdata ]; then le_dir="/mnt/data/letsencrypt"; else le_dir="$PWD/nginx/letsencrypt"; fi
    if [ -f "$le_dir/renewal/$DOMAIN.conf" ]; then
      docker run --rm -v "$le_dir:/etc/letsencrypt" certbot/certbot delete         --cert-name "$DOMAIN" --non-interactive         || echo "ВНИМАНИЕ: сертификат $DOMAIN не удалён из certbot — удалить вручную до января"
    fi
    rm -rf nginx/certs/errors
    "${GT[@]}" down
    echo
    echo "ГОТОВО. Скажите Claude: «move сделан, объект ${obj}» — он поднимет базу на новой ВМ."
    echo "До этого новая ВМ отвечает, но старых ключей не знает: события этих минут теряются."
    ;;

  status)
    sync_env
    "${GT[@]}" ps
    docker stats --no-stream --format '{{.Name}}\t{{.MemUsage}}\t{{.CPUPerc}}' \
      | grep -E 'glitchtip' || true
    ;;

  stop)
    sync_env
    "${GT[@]}" stop
    echo "GlitchTip остановлен. Магазин работает как прежде; errors.mata-club.ru отвечает 502."
    ;;

  *)
    sed -n '2,19p' "$0"
    exit 1
    ;;
esac
