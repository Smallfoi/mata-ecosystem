#!/usr/bin/env bash
# Установка ограниченного канала управления продом (D-103). Запускается ОДИН РАЗ
# на прод-ВМ под sudo; повторный запуск безопасен (обновляет обёртку на месте).
#
#   sudo bash /opt/mata/backend/deploy/install-ops-key.sh
#
# Что делает:
#   1. кладёт обёртку в /opt/mata-ops/ops-shell.sh — ВНЕ рабочей копии git,
#      владелец root, чтобы её нельзя было подменить тем же каналом;
#   2. заводит журнал /var/log/mata-ops.log (кто и что выполнял);
#   3. добавляет в authorized_keys ключ claude-ops, ПРИБИТЫЙ к этой обёртке:
#      что бы ни прислал клиент, выполнится только разрешённый глагол.
#
# Ключ владельца (mata_prod2) не трогаем — он остаётся полным доступом и
# аварийным выходом.
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)/ops-shell.sh"
DST_DIR=/opt/mata-ops
DST="$DST_DIR/ops-shell.sh"
LOG=/var/log/mata-ops.log
USER_HOME=/home/ubuntu
AUTH="$USER_HOME/.ssh/authorized_keys"

# Открытая часть ключа claude-ops. Открытый ключ не секрет: закрытая половина
# лежит только на машине владельца (~/.ssh/mata_prod_ops) и в репозиторий не
# попадает никогда.
OPS_KEY="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAICgF2h9oITiT/Nwb1Np6uVvE+aUi177jRg2Zn+kjNqZa claude-ops@mata"

[ -f "$SRC" ] || { echo "Нет файла $SRC — запускать из /opt/mata/backend/deploy/"; exit 1; }

install -d -o root -g root -m 0755 "$DST_DIR"
install -o root -g root -m 0755 "$SRC" "$DST"
echo "Обёртка: $DST"

touch "$LOG"
chown root:root "$LOG"
chmod 0644 "$LOG"
echo "Журнал:  $LOG"

install -d -o ubuntu -g ubuntu -m 0700 "$USER_HOME/.ssh"
touch "$AUTH"
chown ubuntu:ubuntu "$AUTH"
chmod 0600 "$AUTH"

# restrict = запрет проброса портов/агента/X11/pty и user-rc; command= прибивает
# обёртку намертво: интерактивной оболочки у этого ключа нет в принципе.
LINE="restrict,command=\"$DST\" $OPS_KEY"
KEY_BODY="$(awk '{print $2}' <<< "$OPS_KEY")"

if grep -qF "$KEY_BODY" "$AUTH"; then
  # Ключ уже стоит — переписываем его строку целиком (вдруг менялись ограничения).
  grep -vF "$KEY_BODY" "$AUTH" > "$AUTH.tmp" || true
  mv "$AUTH.tmp" "$AUTH"
  echo "Ключ claude-ops был — строка обновлена."
else
  echo "Ключ claude-ops добавлен."
fi
printf '%s\n' "$LINE" >> "$AUTH"
chown ubuntu:ubuntu "$AUTH"
chmod 0600 "$AUTH"

# sudo для обёртки — ровно то, что она вызывает (docker compose, запись в журнал,
# refresh-env.sh). На ВМ Yandex Cloud у ubuntu и так sudo без пароля; на обычном VPS
# (D-115) пользователь заведён без прав, и каждая команда канала падала на пароле sudo.
SUDOERS=/etc/sudoers.d/mata-ops
cat > "$SUDOERS.tmp" <<'EOF'
# Канал claude-ops (D-103): только команды обёртки /opt/mata-ops/ops-shell.sh.
ubuntu ALL=(root) NOPASSWD: /usr/bin/docker, /usr/bin/tee -a /var/log/mata-ops.log, /usr/bin/bash /opt/mata/backend/deploy/refresh-env.sh
EOF
chmod 0440 "$SUDOERS.tmp"
if visudo -cf "$SUDOERS.tmp" >/dev/null; then
  mv -f "$SUDOERS.tmp" "$SUDOERS"
  echo "sudo для канала: $SUDOERS"
else
  rm -f "$SUDOERS.tmp"
  echo "ВНИМАНИЕ: правило sudo не прошло проверку visudo — не установлено"
fi

echo
echo "Готово. Проверка с машины владельца:"
echo "  ssh -i ~/.ssh/mata_prod_ops -p 2222 ubuntu@158.160.12.117 status"
echo "  ssh -i ~/.ssh/mata_prod_ops -p 2222 ubuntu@158.160.12.117 'rm -rf /'   # должно быть «Отказано»"
