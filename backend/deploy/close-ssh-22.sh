#!/usr/bin/env bash
# Закрыть SSH-порт 22 на прод-ВМ (директива владельца 28.09.2026).
#
#   sudo bash /opt/mata/backend/deploy/close-ssh-22.sh
#
# Зачем. Мы работаем по 2222, а 22 просто стоял открытым и собирал брутфорс:
# ~500 неудачных попыток в сутки с чужих адресов. Вход по паролю выключен, так
# что это был шум, а не пролом, — но лишнюю дверь держать незачем.
#
# Безопасность операции. Порт задан в одном drop-in файле; скрипт снимает бэкап,
# проверяет конфиг `sshd -t` ДО перезапуска и после перезапуска убеждается, что
# 2222 слушается. Если хоть что-то не сошлось — возвращает прежний конфиг и
# поднимает sshd обратно. Открытые сессии перезапуск sshd не рвёт, так что даже
# в худшем случае текущее подключение остаётся живым.
#
# Аварийный выход, если всё же потеряли доступ: серийная консоль ВМ в консоли
# Yandex Cloud (см. PITFALLS «Диагностика без SSH»).
set -euo pipefail

CONF=/etc/ssh/sshd_config.d/mata-port.conf
BACKUP="/root/mata-port.conf.$(date +%Y%m%d-%H%M%S).bak"

[ -f "$CONF" ] || { echo "Нет $CONF — порт задан где-то ещё, разберись руками."; exit 1; }

cp -a "$CONF" "$BACKUP"
echo "Бэкап: $BACKUP"

restore() {
  echo "ОТКАТ: возвращаю прежний конфиг."
  cp -a "$BACKUP" "$CONF"
  systemctl restart ssh || systemctl restart sshd || true
}

cat > "$CONF" <<'EOF'
# Только 2222. Порт 22 закрыт 28.09.2026: им не пользуемся, а брутфорс он собирал.
# Вернуть при необходимости — добавить строку «Port 22» и перезапустить ssh.
Port 2222
EOF

if ! sshd -t; then
  restore
  echo "Конфиг не прошёл проверку — ничего не меняли." >&2
  exit 1
fi

systemctl restart ssh 2>/dev/null || systemctl restart sshd
sleep 2

if ! ss -ltn | grep -qE ':2222 '; then
  restore
  echo "После перезапуска 2222 не слушается — откатился." >&2
  exit 1
fi

if ss -ltn | grep -qE ':22 '; then
  echo "Порт 22 всё ещё слушается — проверь другие drop-in файлы:" >&2
  grep -rn '^ *Port' /etc/ssh/sshd_config /etc/ssh/sshd_config.d/ >&2
  exit 1
fi

echo "Готово: слушается только 2222."
ss -ltn | grep -E ':(22|2222) ' || true
echo
echo "В облаке правило для 22 в security-group можно тоже убрать — теперь оно ни на что не указывает."
