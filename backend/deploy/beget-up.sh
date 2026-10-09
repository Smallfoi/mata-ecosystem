#!/usr/bin/env bash
# Поднять прод на обычном VPS (Beget и т.п.) — D-115, авария Yandex Cloud 8.10.2026.
#
# Запускать в Yandex Cloud Shell (там есть доступ к Lockbox), указав IP нового VPS:
#   curl -fsSL https://raw.githubusercontent.com/Smallfoi/mata-ecosystem/main/backend/deploy/beget-up.sh | HOST=<IP VPS> bash
# SSH на VPS — под root (SSH_USER/SSH_PORT меняют это). Пароль root спросят один раз.
#
# Что делает:
#   1. берёт секреты прода из Lockbox (mata-prod-secrets + mata-eco-image) и кладёт их на VPS
#      в /root/mata-secrets.env (права 600) — по SSH, мимо чата и репозитория;
#   2. запускает на VPS prod-deploy.sh в режиме vps с восстановлением последнего бэкапа БД.
# Хранилище фото и бэкапов остаётся в Yandex Object Storage — ключи доступа среди секретов.
set -euo pipefail

HOST="${HOST:?Укажите IP VPS: ... | HOST=1.2.3.4 bash}"
SSH_USER="${SSH_USER:-root}"
SSH_PORT="${SSH_PORT:-22}"
LB_SECRET_ID="e6q1ias432ne7vtogghv"        # mata-prod-secrets
ECO_IMAGE_SECRET_ID="e6qu8vruift7elbpm6o8" # mata-eco-image (необязательный)
DEPLOY_URL="https://raw.githubusercontent.com/Smallfoi/mata-ecosystem/main/backend/deploy/prod-deploy.sh"

# Один вход на все обращения: пароль спрашивается один раз. -n у команд без ввода: скрипт
# читается из того же stdin (curl | bash), и ssh иначе съел бы его остаток.
CTL="/tmp/mata-ssh-${HOST}"
SSH=(ssh -p "$SSH_PORT" -o StrictHostKeyChecking=accept-new
     -o ControlMaster=auto -o ControlPath="$CTL" -o ControlPersist=120 "${SSH_USER}@${HOST}")

TMP=$(mktemp)
chmod 600 "$TMP"
trap 'rm -f "$TMP"' EXIT

# Lockbox → строки KEY='value' (как в .env). CLI отдаёт text_value, REST — textValue.
to_env='import sys,json,shlex
for e in json.load(sys.stdin).get("entries", []):
    print(e["key"] + "=" + shlex.quote(e.get("text_value", e.get("textValue", ""))))'

echo "== 1/3 Секреты из Lockbox =="
yc lockbox payload get --id "$LB_SECRET_ID" --format json | python3 -c "$to_env" >> "$TMP"
yc lockbox payload get --id "$ECO_IMAGE_SECRET_ID" --format json 2>/dev/null \
  | python3 -c "$to_env" >> "$TMP" 2>/dev/null || echo "   (mata-eco-image не прочитан — фотопайплайн без GPT)"
for k in POSTGRES_PASSWORD DJANGO_SECRET_KEY JWT_SECRET BACKUP_S3_BUCKET BACKUP_ENCRYPT_PASSPHRASE; do
  grep -q "^$k=" "$TMP" || { echo "ОШИБКА: в Lockbox нет $k — без него прод не поднять"; exit 1; }
done
echo "   ключей: $(grep -c '=' "$TMP")"

echo "== 2/3 Секреты → ${SSH_USER}@${HOST}:/root/mata-secrets.env =="
"${SSH[@]}" 'umask 077; cat > /root/mata-secrets.env' < "$TMP"

echo "== 3/3 Запуск развёртывания на VPS (в фоне, 10–20 мин) =="
"${SSH[@]}" -n "set -e; command -v curl >/dev/null || (apt-get update -y && apt-get install -y curl);
  curl -fsSL '$DEPLOY_URL' -o /opt/prod-deploy.sh;
  MATA_HOST=vps MATA_RESTORE_LATEST=1 nohup bash /opt/prod-deploy.sh > /var/log/mata-deploy.log 2>&1 < /dev/null &
  echo запущено"
"${SSH[@]}" -O exit 2>/dev/null || true

cat <<EOF

==================================================================
  Развёртывание идёт на ${HOST}. Ход работы:
    ssh -p ${SSH_PORT} ${SSH_USER}@${HOST} 'grep -E "===|FATAL|restore|Восстан" /var/log/mata-deploy.log | tail -20'

  Ждите «=== ГОТОВО». Строка FATAL — пришлите её Claude, домен НЕ переводите.
  После «ГОТОВО» — в Beget A-записи mata-club.ru, www, api → ${HOST}.
  Сертификат HTTPS выпустится сам через ~5 минут после обновления DNS.
==================================================================
EOF
