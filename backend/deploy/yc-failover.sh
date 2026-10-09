#!/usr/bin/env bash
# Аварийный подъём прода в ДРУГОЙ зоне Yandex Cloud (8.10.2026: пожар в ЦОД ru-central1-b).
#
# Прежняя ВМ, её диск с БД и статический IP живут в одной зоне и вместе с ней недоступны.
# Этот скрипт ничего из прежнего не трогает и создаёт рядом новое:
#   статический IP + пустой диск под БД + ВМ «mata-prod-<зона>» с меткой mata-restore-latest=1.
# ВМ сама разворачивает стек (prod-deploy.sh), скачивает ПОСЛЕДНИЙ бэкап БД из бакета и
# восстанавливает базу. TLS выпускается, когда DNS переведён на новый IP (крон раз в 5 мин).
#
# Запуск в Yandex Cloud Shell (зона по умолчанию — ru-central1-a, Владимир):
#   curl -fsSL https://raw.githubusercontent.com/Smallfoi/mata-ecosystem/main/backend/deploy/yc-failover.sh | bash
#   ZONE=ru-central1-d ... | bash        # другая зона (Калуга)
# Повторный запуск безопасен: готовые IP/диск/ВМ переиспользуются, а не создаются заново.
set -euo pipefail

ZONE="${ZONE:-ru-central1-a}"
SUFFIX="${ZONE##*-}"                          # a | b | d
NAME="mata-prod-${SUFFIX}"
ADDR_NAME="mata-prod-ip-${SUFFIX}"
DISK_NAME="mata-db-data-${SUFFIX}"
DISK_GB="${DISK_GB:-30}"
OLD_SUBNET="e2lrgpcelk00ugbo1f0n"             # подсеть прежней ВМ (ru-central1-b) — берём из неё сеть
SG="enptivfkcai2uguhb837"                     # группа безопасности прода (принадлежит сети)
SA="ajeqekgcl5qjghk2rlju"                     # mata-vm: читает Lockbox и бакеты
CI_URL="https://raw.githubusercontent.com/Smallfoi/mata-ecosystem/main/backend/deploy/cloud-init-prod.yaml"

case "$ZONE" in
  ru-central1-a|ru-central1-d) ;;
  ru-central1-b) echo "Зона ru-central1-b — та, что недоступна. Выберите ru-central1-a или ru-central1-d."; exit 1 ;;
  *) echo "Неизвестная зона $ZONE"; exit 1 ;;
esac

js() { python3 -c "import sys,json; d=json.load(sys.stdin); $1"; }

echo "== 1/5 Сеть и подсеть в зоне $ZONE =="
NET=$(yc vpc subnet get "$OLD_SUBNET" --format json | js 'print(d["network_id"])')
SUBNET=$(yc vpc subnet list --format json | js "
for s in d:
    if s.get('network_id') == '$NET' and s.get('zone_id') == '$ZONE':
        print(s['id']); break")
if [ -z "$SUBNET" ]; then
  # Свободный диапазон: в сети по умолчанию a/b/d заняты 10.128/129/131.0.0/24.
  SUBNET=$(yc vpc subnet create --name "mata-subnet-${SUFFIX}" --zone "$ZONE" \
    --network-id "$NET" --range "10.140.0.0/24" --format json | js 'print(d["id"])')
  echo "   создана подсеть $SUBNET"
else
  echo "   подсеть $SUBNET"
fi

echo "== 2/5 Статический IP в зоне $ZONE =="
IP=$(yc vpc address get --name "$ADDR_NAME" --format json 2>/dev/null \
  | js 'print(d["external_ipv4_address"]["address"])' 2>/dev/null || true)
if [ -z "$IP" ]; then
  IP=$(yc vpc address create --name "$ADDR_NAME" --external-ipv4 zone="$ZONE" \
    --format json | js 'print(d["external_ipv4_address"]["address"])')
  echo "   зарезервирован $IP"
else
  echo "   уже есть $IP"
fi

echo "== 3/5 Диск под БД ($DISK_GB ГБ, пустой — база придёт из бэкапа) =="
DISK=$(yc compute disk get --name "$DISK_NAME" --format json 2>/dev/null | js 'print(d["id"])' 2>/dev/null || true)
if [ -z "$DISK" ]; then
  DISK=$(yc compute disk create --name "$DISK_NAME" --zone "$ZONE" --size "$DISK_GB" \
    --type network-ssd --format json | js 'print(d["id"])')
  echo "   создан $DISK"
else
  echo "   уже есть $DISK"
fi

echo "== 4/5 cloud-init =="
curl -fsSL "$CI_URL" -o /tmp/mata-ci.yaml
echo "   строк: $(wc -l < /tmp/mata-ci.yaml)"

echo "== 5/5 ВМ $NAME =="
if yc compute instance get --name "$NAME" >/dev/null 2>&1; then
  echo "   ВМ уже существует — не пересоздаю (удалить: yc compute instance delete --name $NAME)"
else
  yc compute instance create \
    --name "$NAME" \
    --zone "$ZONE" \
    --service-account-id "$SA" \
    --platform standard-v3 \
    --cores 2 \
    --memory 4G \
    --core-fraction 100 \
    --create-boot-disk image-folder-id=standard-images,image-family=ubuntu-2404-lts,size=30G,type=network-ssd \
    --attach-disk disk-id="$DISK",auto-delete=false,mode=rw \
    --network-interface subnet-id="$SUBNET",security-group-ids="$SG",nat-address="$IP" \
    --metadata-from-file user-data=/tmp/mata-ci.yaml \
    --metadata "enable-oslogin=false,mata-restore-latest=1" >/dev/null
  echo "   создана"
fi

cat <<EOF

==================================================================
  Новый сервер: $NAME, зона $ZONE, IP $IP

  1. Подождите 10–15 минут: сервер ставит стек и восстанавливает базу.
     Ход работы:
       yc compute instance get-serial-port-output --name $NAME | grep -E "===|FATAL|Готово|restore" | tail -20
     Ждите строку «=== ГОТОВО». Строка FATAL — пришлите её Claude, домен НЕ переводите.

  2. После «ГОТОВО» — у регистратора (Beget) поменяйте A-записи на $IP:
       mata-club.ru, www.mata-club.ru, api.mata-club.ru

  3. Сертификат HTTPS выпустится сам в течение ~5 минут после того, как DNS обновится.
==================================================================
EOF
