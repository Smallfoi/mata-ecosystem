#!/usr/bin/env bash
# MTU сервера = 1500 + защита от «чёрной дыры» MTU. Идемпотентно, запускать от root.
#
# Зачем (15.11.2026): образ Cloud.ru пишет в netplan mtu 9000, а путь в интернет пропускает
# только 1500. ICMP «нужна фрагментация» от части узлов не доходит, поэтому крупные пакеты
# пропадали молча: TLS к S3 Timeweb рвался (ночной дамп с 12.11 не ложился во второе
# хранилище), SSH к серверу проходил через раз. Контейнеры (MTU 1500) этого не замечали.
set -euo pipefail

cat > /etc/sysctl.d/60-mata-mtu.conf <<'CONF'
# МАТА: TCP сам уменьшает пакеты, если крупные теряются без ICMP (см. deploy/net-mtu.sh).
net.ipv4.tcp_mtu_probing = 1
CONF
sysctl -q -p /etc/sysctl.d/60-mata-mtu.conf

# Каждому интерфейсу с MTU больше 1500 (кроме docker/veth/lo) — 1500 сейчас и после перезагрузки.
for path in /sys/class/net/*; do
  ifc="$(basename "$path")"
  case "$ifc" in lo|docker*|br-*|veth*) continue ;; esac
  mtu="$(cat "$path/mtu")"
  [ "$mtu" -gt 1500 ] || continue
  ip link set "$ifc" mtu 1500
  echo "MTU $ifc: $mtu → 1500"
done

# Netplan: перекрываем MTU из 50-cloud-init.yaml (у Cloud.ru там блок all-en с mtu 9000).
if [ -d /etc/netplan ] && grep -qs "mtu: *9000" /etc/netplan/*.yaml; then
  ids="$(grep -h -B6 "mtu: *9000" /etc/netplan/*.yaml | sed -n 's/^    \([A-Za-z0-9_-]*\):$/\1/p' | sort -u)"
  {
    echo "# МАТА: MTU 1500 вместо 9000 из образа (deploy/net-mtu.sh)."
    echo "network:"
    echo "  version: 2"
    echo "  ethernets:"
    for id in $ids; do echo "    $id:"; echo "      mtu: 1500"; done
  } > /etc/netplan/60-mata-mtu.yaml
  chmod 600 /etc/netplan/60-mata-mtu.yaml
  netplan generate
  echo "Netplan: /etc/netplan/60-mata-mtu.yaml ($ids)"
fi
