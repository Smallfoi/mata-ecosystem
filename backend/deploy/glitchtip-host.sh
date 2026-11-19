#!/usr/bin/env bash
# GlitchTip МАТА на своей ВМ (D-132) — установка, приём базы с прод-ВМ, состояние.
#
# Запускать на ВМ GlitchTip под sudo (каталог — /opt/mata/backend):
#   sudo bash deploy/glitchtip-host.sh setup            — секреты, база, миграции, запуск
#                                                        (делает cloud-init при создании ВМ)
#   sudo bash deploy/glitchtip-host.sh restore <файл>   — принять базу и секреты с прод-ВМ
#                                                        (архив от `glitchtip.sh move`, уже
#                                                        расшифрованный: glitchtip.dump +
#                                                        mata-glitchtip.env)
#   sudo bash deploy/glitchtip-host.sh status           — контейнеры, память, сертификат
#   sudo bash deploy/glitchtip-host.sh admin            — создать пользователя (почта + пароль)
#   sudo bash deploy/glitchtip-host.sh keys             — проекты, ключи, токен для админки
#                                                        магазина (если их надо выпустить заново)
#
# После restore ключи (DSN) и пользователи — прежние: приложения у тестеров продолжают
# слать ошибки без новой сборки.
set -euo pipefail

cd "$(dirname "$0")/.."   # → backend/

DOMAIN="${GLITCHTIP_HOST:-errors.mata-club.ru}"
# Секреты — вне рабочей копии: обновление кода (git) их не трогает.
SECRETS="${GLITCHTIP_SECRETS_FILE:-/root/mata-glitchtip.env}"
ENVF="glitchtip.env"   # копия для docker compose (в .gitignore — репозиторий публичный)
GT=(docker compose -f docker-compose.glitchtip-host.yml --env-file "$ENVF")

make_secrets() {
  local secret dbpass
  secret="$(openssl rand -hex 32)"
  dbpass="$(openssl rand -hex 24)"
  umask 077
  # Почты пока нет (письма — в журнал): настоящие настройки приезжают с базой (restore).
  cat > "$SECRETS" <<ENV
# GlitchTip МАТА — секреты (создано deploy/glitchtip-host.sh $(date -u +%Y-%m-%dT%H:%MZ)).
GLITCHTIP_DB_PASSWORD=$dbpass
DATABASE_URL=postgres://glitchtip:$dbpass@glitchtip-db:5432/glitchtip
SECRET_KEY=$secret
GLITCHTIP_DOMAIN=https://$DOMAIN
ALLOWED_HOSTS=$DOMAIN,glitchtip,localhost
CSRF_TRUSTED_ORIGINS=https://$DOMAIN
DEFAULT_FROM_EMAIL=noreply@mata-club.ru
EMAIL_URL=consolemail://
ENABLE_USER_REGISTRATION=False
ENABLE_ORGANIZATION_CREATION=False
ENABLE_ADMIN=False
GLITCHTIP_MAX_EVENT_LIFE_DAYS=30
ENV
  echo "Секреты GlitchTip созданы: $SECRETS"
}

sync_env() {
  [ -s "$SECRETS" ] || { echo "Нет $SECRETS — сначала: glitchtip-host.sh setup"; exit 1; }
  install -m 600 "$SECRETS" "$ENVF"
  # Адрес внутри этой ВМ — имя сервиса `glitchtip` (на прод-ВМ был `glitchtip-web`):
  # без него в ALLOWED_HOSTS проверки изнутри получали бы 400.
  if ! grep -q '^ALLOWED_HOSTS=.*\bglitchtip\b' "$ENVF" || grep -q '^ALLOWED_HOSTS=.*glitchtip-web' "$ENVF"; then
    sed -i "s/^ALLOWED_HOSTS=.*/ALLOWED_HOSTS=$DOMAIN,glitchtip,localhost/" "$ENVF"
  fi
}

wait_healthy() {
  local i
  for i in $(seq 1 60); do
    # Любой HTTP-ответ (даже 404) — сервер поднялся; отказ соединения — ещё нет.
    if "${GT[@]}" exec -T glitchtip python -c "
import urllib.request, urllib.error
try:
    urllib.request.urlopen('http://localhost:8000/_health/', timeout=5)
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

wait_db() {
  local i
  for i in $(seq 1 30); do
    "${GT[@]}" exec -T glitchtip-db pg_isready -U glitchtip -d glitchtip >/dev/null 2>&1 && return 0
    sleep 2
  done
  echo "База GlitchTip не поднялась за минуту."; return 1
}

case "${1:-}" in
  setup)
    [ -s "$SECRETS" ] && echo "Секреты уже есть: $SECRETS — не пересоздаю." || make_secrets
    sync_env
    "${GT[@]}" pull
    "${GT[@]}" up -d glitchtip-db
    wait_db
    "${GT[@]}" run --rm glitchtip ./manage.py migrate --noinput
    "${GT[@]}" up -d
    wait_healthy
    echo "ГОТОВО. Сертификат Caddy выпустит сам, когда A-запись $DOMAIN укажет на эту ВМ."
    ;;

  restore)
    src="${2:-}"
    [ -n "$src" ] && [ -s "$src" ] || { echo "Использование: glitchtip-host.sh restore <архив.tar>"; exit 1; }
    work="$(mktemp -d)"; trap 'rm -rf "$work"' EXIT
    tar -C "$work" -xf "$src" glitchtip.dump mata-glitchtip.env
    [ -s "$work/glitchtip.dump" ] && [ -s "$work/mata-glitchtip.env" ] || {
      echo "СТОП: в архиве нет glitchtip.dump или mata-glitchtip.env"; exit 1; }
    grep -q '^GLITCHTIP_DB_PASSWORD=' "$work/mata-glitchtip.env" || {
      echo "СТОП: в принесённых секретах нет GLITCHTIP_DB_PASSWORD"; exit 1; }
    # Прежние секреты — рядом, на случай отката.
    [ -s "$SECRETS" ] && cp -p "$SECRETS" "$SECRETS.bak-$(date +%Y%m%d%H%M%S)"
    # Сеть магазина здесь не нужна — строку прод-ВМ выкидываем.
    umask 077
    grep -v '^MATA_PROD_NETWORK=' "$work/mata-glitchtip.env" > "$SECRETS"
    sync_env
    # Базу создаём заново под принесённый пароль. Сносим ТОЛЬКО том базы: том Caddy
    # с сертификатом остаётся (иначе перевыпуск и лимит Let's Encrypt).
    "${GT[@]}" stop glitchtip glitchtip-db
    "${GT[@]}" rm -f glitchtip-db
    docker volume rm mata-glitchtip_glitchtip-pg
    "${GT[@]}" up -d glitchtip-db
    wait_db
    "${GT[@]}" exec -T glitchtip-db pg_restore -U glitchtip -d glitchtip --no-owner --exit-on-error \
      < "$work/glitchtip.dump"
    # Дамп той же версии GlitchTip — migrate ничего не меняет, но доводит схему, если
    # образ на этой ВМ окажется новее.
    "${GT[@]}" run --rm glitchtip ./manage.py migrate --noinput
    "${GT[@]}" up -d --force-recreate glitchtip
    wait_healthy
    "${GT[@]}" exec -T glitchtip ./manage.py shell -c "
from django.apps import apps
P = apps.get_model('projects', 'Project'); K = apps.get_model('projects', 'ProjectKey')
print('Проекты:', ', '.join(P.objects.order_by('id').values_list('slug', flat=True)) or 'нет',
      '| ключей:', K.objects.filter(is_active=True).count())"
    echo "База и секреты приняты. Ключи (DSN) — прежние."
    ;;

  status)
    sync_env
    "${GT[@]}" ps
    docker stats --no-stream --format '{{.Name}}\t{{.MemUsage}}\t{{.CPUPerc}}' | grep -E 'glitchtip|caddy' || true
    echo "Сертификат:"
    echo | openssl s_client -connect 127.0.0.1:443 -servername "$DOMAIN" 2>/dev/null \
      | openssl x509 -noout -issuer -enddate 2>/dev/null || echo "  пока нет (DNS ещё не указывает сюда?)"
    ;;

  admin)
    sync_env
    "${GT[@]}" exec glitchtip ./manage.py createsuperuser
    ;;

  keys)
    # Повторный запуск ничего не дублирует. Строки ENV:… положить в /root/mata-server-keys.env
    # на проде и выполнить там `bash deploy/refresh-env.sh`; APPS_DSN — в секрет GitHub SENTRY_DSN.
    sync_env
    "${GT[@]}" exec -T glitchtip ./manage.py shell -c "$(cat deploy/glitchtip_connect.py)"
    ;;

  *)
    sed -n '2,18p' "$0"
    exit 1
    ;;
esac
