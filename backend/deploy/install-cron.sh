#!/usr/bin/env bash
# Расписание прода: авто-деплой, выпуск/продление TLS, ночной бэкап БД.
# Запускать под root:  bash /opt/mata/backend/deploy/install-cron.sh   (повторно — безопасно)
#
# ГРАБЛИ (9.10.2026, VPS Beget): на сервере без расписания `crontab -l` завершается с ошибкой,
# grep -v без строк — тоже, и под `set -euo pipefail` весь конвейер падал: в crontab не
# попадало НИЧЕГО, а prod-deploy.sh обрывался на этом шаге. Без авто-деплоя, бэкапа и TLS.
set -euo pipefail

# Пути переопределяются только в модельном тесте (tests/test_install_cron.sh).
MATA_DIR="${MATA_DIR:-/opt/mata}"
AUTODEPLOY="${AUTODEPLOY:-/opt/prod-autodeploy.sh}"
install -m 755 "$MATA_DIR/backend/deploy/prod-autodeploy.sh" "$AUTODEPLOY"

CURRENT=$(crontab -l 2>/dev/null || true)
# Убираем наши прежние строки (и битые старые — mata-autodeploy/mata-tls), чужие оставляем.
KEEP=$(printf '%s\n' "$CURRENT" \
  | grep -v 'prod-autodeploy\|mata-autodeploy\|mata-tls\|tls.sh renew\|tls-when-dns\|backup.sh' || true)

{
  [ -n "$KEEP" ] && printf '%s\n' "$KEEP"
  echo "*/2 * * * * /opt/prod-autodeploy.sh >> /var/log/mata-autodeploy.log 2>&1"
  echo "*/5 * * * * cd /opt/mata/backend && ./deploy/tls-when-dns.sh >> /var/log/mata-tls.log 2>&1"
  echo "0 3 * * 1 cd /opt/mata/backend && ./deploy/tls.sh renew >> /var/log/mata-tls.log 2>&1"
  echo "0 4 * * * cd /opt/mata/backend && ./deploy/backup.sh >> /var/log/mata-backup.log 2>&1"
} | crontab -

echo "Расписание установлено:"
crontab -l | grep -E 'prod-autodeploy|tls|backup'
