#!/usr/bin/env bash
# РУЧНАЯ сквозная проверка непрерывной копии БД (D-117) — в CI не входит (минуты, docker, два S3).
# Сценарий: pgbr.sh setup → данные → diff-копия → хранилище 1 падает, пишем дальше → сервер
# потерян целиком → restore 1 (не выходит) → restore 2 → данные совпадают до последней строки.
# Запуск (Windows/Docker Desktop, из корня репо; /tmp/pgbrtest — путь внутри ВМ Docker):
#   MSYS_NO_PATHCONV=1 docker run --rm -v /var/run/docker.sock:/var/run/docker.sock \
#     -v "$PWD/backend:/src:ro" -v "$PWD/backend/deploy/tests/e2e_pgbr.sh:/e2e.sh:ro" \
#     -v /tmp/pgbrtest:/tmp/pgbrtest docker:27-cli sh -c "apk add -q bash python3 openssl coreutils && bash /e2e.sh"
# S3 — versity/versitygw (MinIO закрыл образы на Docker Hub и quay.io в 2025–2026).
set -uo pipefail
T=/tmp/pgbrtest
NET=pgbr-e2e
step() { echo; echo "######## $*"; }
fail() { echo "!!!!!!!! ПРОВАЛ: $*"; exit 1; }

docker rm -f pgbr-m1 pgbr-m2 >/dev/null 2>&1
rm -rf "$T"/* 2>/dev/null; mkdir -p "$T/certs" "$T/data"
docker network create "$NET" >/dev/null 2>&1

step "Сертификаты и два S3 (versitygw) (хранилище 1 = «Яндекс», 2 = «Beget»)"
openssl req -x509 -newkey rsa:2048 -nodes -days 2 -subj "/CN=minio" \
  -addext "subjectAltName=DNS:pgbr-m1,DNS:pgbr-m2" \
  -keyout "$T/certs/private.key" -out "$T/certs/public.crt" 2>/dev/null || fail "openssl"
chmod 644 "$T/certs/"*
for i in 1 2; do
  mkdir -p "$T/s3data$i/backups$i"   # у versitygw (posix) корзина — это папка
  docker run -d --name pgbr-m$i --network "$NET" -v "$T/certs:/certs:ro" -v "$T/s3data$i:/data" \
    versity/versitygw:latest --access minioadmin --secret minioadmin123 --port :9000 \
    --cert /certs/public.crt --key /certs/private.key posix /data >/dev/null || fail "s3 $i"
done
sleep 4
docker logs pgbr-m1 2>&1 | tail -3

step "Копия backend → /work, тестовый .env"
rm -rf /work && cp -r /src /work && cd /work
cat > .env <<EOF
POSTGRES_DB=mata
POSTGRES_USER=mata
POSTGRES_PASSWORD=test
BACKUP_S3_BUCKET=backups1
BACKUP_S3_ACCESS_KEY=minioadmin
BACKUP_S3_SECRET_KEY=minioadmin123
BACKUP_S3_ENDPOINT=https://pgbr-m1:9000
BACKUP_S3_REGION=us-east-1
BACKUP2_S3_BUCKET=backups2
BACKUP2_S3_ACCESS_KEY=minioadmin
BACKUP2_S3_SECRET_KEY=minioadmin123
BACKUP2_S3_ENDPOINT=https://pgbr-m2:9000
BACKUP2_S3_REGION=us-east-1
BACKUP_ENCRYPT_PASSPHRASE=test-pass-123
EOF
# Сеть MinIO подключаем к контейнеру БД через override (в проде его нет).
cat > docker-compose.override.test.yml <<EOF
services:
  db:
    networks: [default, e2e]
networks:
  e2e:
    external: true
    name: $NET
EOF
export MATA_DATA_DIR="$T/data"
export PGBR_EXTRA_GLOBAL=$'repo1-storage-verify-tls=n\nrepo2-storage-verify-tls=n'
export COMPOSE_PROJECT_NAME=pgbre2e
# pgbr.sh зовёт compose только с prod-файлом — подменяем через COMPOSE_FILE (переменная compose).
sed -i 's#^COMPOSE=(docker compose -f docker-compose.prod.yml --env-file .env)#COMPOSE=(docker compose -f docker-compose.prod.yml -f docker-compose.override.test.yml --env-file .env)#' deploy/pgbr.sh
grep -q override.test deploy/pgbr.sh || fail "подмена compose"
psql_() { docker compose -f docker-compose.prod.yml -f docker-compose.override.test.yml --env-file .env exec -T db psql -X -U mata -d mata -tAc "$1"; }

step "pgbr.sh setup"
./deploy/pgbr.sh setup || fail "setup"

step "Данные после полной копии + ждём отправку WAL (archive_timeout 60 с)"
psql_ "create table t(id serial primary key, note text, at timestamptz default now())" || fail "create"
psql_ "insert into t(note) select 'row '||g from generate_series(1,1000) g" >/dev/null
psql_ "insert into t(note) values ('ПОСЛЕДНЯЯ ДО АВАРИИ')" >/dev/null
BEFORE=$(psql_ "select count(*)||'|'||max(note) filter (where note like 'ПОСЛ%') from t")
echo "до аварии: $BEFORE"
psql_ "select pg_switch_wal()" >/dev/null
sleep 20
./deploy/pgbr.sh check || fail "check"
step "Разностная копия, как в кроне"
./deploy/pgbr.sh backup diff 2>&1 | grep -E "==|new backup label|ОШИБКА|ERROR" || fail "backup diff"

step "Хранилище 1 недоступно — уходит ли WAL во второе?"
docker stop pgbr-m1 >/dev/null
psql_ "insert into t(note) values ('ПРИ ЛЕЖАЩЕМ ЯНДЕКСЕ')" >/dev/null
psql_ "select pg_switch_wal()" >/dev/null
sleep 45
BEFORE=$(psql_ "select count(*)||'|'||string_agg(note, ',') filter (where note like 'П%') from t")
echo "до аварии (с лежащим хранилищем 1): $BEFORE"

step "Авария: сервер потерян целиком"
docker compose -f docker-compose.prod.yml -f docker-compose.override.test.yml --env-file .env rm -sf db >/dev/null
rm -rf "$T/data/pgdata" "$T/data/pgbackrest" "$T/data/pgbackrest-spool"
echo "каталог данных удалён"

step "Новый сервер: pgbr.sh restore 2 (из второго хранилища)"
./deploy/pgbr.sh restore 1 || { echo "-- хранилище 1 не отдало копию, пробую 2"; ls -A "$T/data/pgdata" | head -3; ./deploy/pgbr.sh restore 2; } || fail "restore"
AFTER=$(psql_ "select count(*)||'|'||string_agg(note, ',') filter (where note like 'П%') from t")
echo "после восстановления: $AFTER"
[ "$AFTER" = "$BEFORE" ] && echo "======== УСПЕХ: данные совпадают, включая запись при лежащем хранилище 1" \
  || echo "======== РАСХОЖДЕНИЕ: было «$BEFORE», стало «$AFTER»"

step "Уборка"
docker compose -f docker-compose.prod.yml -f docker-compose.override.test.yml --env-file .env down -v >/dev/null 2>&1
docker rm -f pgbr-m1 pgbr-m2 >/dev/null 2>&1
docker network rm "$NET" >/dev/null 2>&1
rm -rf "$T"
