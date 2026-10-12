#!/usr/bin/env bash
# Непрерывная копия БД через pgBackRest — в ДВА хранилища у разных провайдеров (D-117).
# Запуск НА СЕРВЕРЕ под root из backend/:  ./deploy/pgbr.sh <команда>
#
#   setup          конфиг из .env → пересоздать контейнер БД → stanza → проверка → первая полная копия
#   backup full|diff   полная / разностная копия (крон: full по воскресеньям, diff в остальные дни)
#   check          архив WAL доходит до хранилищ? (код ≠0 — нет)
#   info           что лежит в хранилищах
#   restore [1|2]  НОВЫЙ сервер, ПУСТОЙ каталог БД: восстановить последнее состояние из
#                  хранилища 1 (Яндекс) или 2 (Beget); БД догонит архив WAL до последней секунды
#
# Как это работает: PostgreSQL отдаёт каждый сегмент журнала (WAL) в pgBackRest не реже раза в
# минуту (archive_timeout=60 в docker-compose.prod.yml), тот шифрует и кладёт его в оба
# хранилища. Восстановление = последняя полная/разностная копия + все сегменты WAL после неё.
# Итог — при потере сервера теряется не больше ~минуты изменений.
set -euo pipefail

cd "$(dirname "$0")/.."  # → backend/
[ -f .env ] || { echo "Нет .env"; exit 1; }
set -a; . ./.env; set +a

COMPOSE=(docker compose -f docker-compose.prod.yml --env-file .env)
DATA="${MATA_DATA_DIR:-/mnt/data}"
CONF_DIR="$DATA/pgbackrest"
SPOOL="$DATA/pgbackrest-spool"
PG_UID=999   # пользователь postgres в образе postgis/postgis

pgbr() { "${COMPOSE[@]}" exec -T -u postgres db pgbackrest --stanza=mata "$@"; }

host_of() { local u="${1#*://}"; u="${u%%/*}"; echo "${u%%:*}"; }   # https://host:port/... → host
port_of() { local u="${1#*://}"; u="${u%%/*}"; case "$u" in *:*) echo "${u##*:}" ;; *) echo 443 ;; esac; }

write_conf() {
  local pass="${BACKUP_ENCRYPT_PASSPHRASE:-}"
  [ -n "$pass" ] || { echo "ОШИБКА: BACKUP_ENCRYPT_PASSPHRASE пуст — копии с ПДн без шифрования не делаем"; exit 1; }
  local repos=0 tmp
  install -d -m 0750 "$CONF_DIR"
  install -d -m 0750 "$SPOOL"
  tmp="$(mktemp "$CONF_DIR/.conf.XXXXXX")"
  {
    echo "[global]"
    if [ -n "${BACKUP_S3_BUCKET:-}" ]; then
      repos=$((repos + 1))
      echo "# Хранилище 1 — Yandex Object Storage"
      echo "repo1-type=s3"
      echo "repo1-s3-endpoint=$(host_of "${BACKUP_S3_ENDPOINT:-${MEDIA_S3_ENDPOINT:-https://storage.yandexcloud.net}}")"
      echo "repo1-storage-port=$(port_of "${BACKUP_S3_ENDPOINT:-${MEDIA_S3_ENDPOINT:-https://storage.yandexcloud.net}}")"
      echo "repo1-s3-region=${BACKUP_S3_REGION:-${MEDIA_S3_REGION:-ru-central1}}"
      echo "repo1-s3-bucket=${BACKUP_S3_BUCKET}"
      echo "repo1-s3-key=${BACKUP_S3_ACCESS_KEY:-${MEDIA_S3_ACCESS_KEY:-}}"
      echo "repo1-s3-key-secret=${BACKUP_S3_SECRET_KEY:-${MEDIA_S3_SECRET_KEY:-}}"
      echo "repo1-s3-uri-style=path"
      echo "repo1-path=/pgbackrest"
      echo "repo1-retention-full=4"
      echo "repo1-cipher-type=aes-256-cbc"
      echo "repo1-cipher-pass=${pass}"
    fi
    if [ -n "${BACKUP2_S3_BUCKET:-}" ]; then
      repos=$((repos + 1))
      echo "# Хранилище 2 — у другого провайдера (по умолчанию S3 Beget)"
      echo "repo2-type=s3"
      echo "repo2-s3-endpoint=$(host_of "${BACKUP2_S3_ENDPOINT:-https://s3.ru1.storage.beget.cloud}")"
      echo "repo2-storage-port=$(port_of "${BACKUP2_S3_ENDPOINT:-https://s3.ru1.storage.beget.cloud}")"
      echo "repo2-s3-region=${BACKUP2_S3_REGION:-ru1}"
      echo "repo2-s3-bucket=${BACKUP2_S3_BUCKET}"
      echo "repo2-s3-key=${BACKUP2_S3_ACCESS_KEY:-}"
      echo "repo2-s3-key-secret=${BACKUP2_S3_SECRET_KEY:-}"
      echo "repo2-s3-uri-style=path"
      echo "repo2-path=/pgbackrest"
      echo "repo2-retention-full=4"
      echo "repo2-cipher-type=aes-256-cbc"
      echo "repo2-cipher-pass=${pass}"
    fi
    if [ -n "${PGBR_EXTRA_GLOBAL:-}" ]; then printf '%s\n' "$PGBR_EXTRA_GLOBAL"; fi  # только для теста
    echo "# Отправка WAL — асинхронно: БД не ждёт сеть на каждом сегменте."
    echo "archive-async=y"
    echo "spool-path=/var/spool/pgbackrest"
    echo "# Хранилище недоступно долго — очередь WAL не растёт бесконечно и не кладёт диск:"
    echo "# сверх 4 ГиБ сегменты отбрасываются (в копии появится разрыв — check покажет)."
    echo "archive-push-queue-max=4GiB"
    echo "compress-type=zst"
    echo "process-max=2"
    echo "start-fast=y"
    echo "log-level-console=info"
    echo "log-level-file=off"
    echo
    echo "[mata]"
    echo "pg1-path=/var/lib/postgresql/data"
    echo "pg1-user=${POSTGRES_USER:-mata}"
    echo "pg1-database=${POSTGRES_DB:-mata}"
  } > "$tmp"
  [ "$repos" -gt 0 ] || { rm -f "$tmp"; echo "ОШИБКА: ни BACKUP_S3_BUCKET, ни BACKUP2_S3_BUCKET не заданы"; exit 1; }
  chmod 0600 "$tmp"
  chown "$PG_UID:$PG_UID" "$tmp" "$CONF_DIR" "$SPOOL"
  mv -f "$tmp" "$CONF_DIR/pgbackrest.conf"
  echo "Конфиг pgBackRest: хранилищ $repos ($CONF_DIR/pgbackrest.conf)"
}

wait_db() {
  for _ in $(seq 1 60); do
    "${COMPOSE[@]}" exec -T db pg_isready -U "${POSTGRES_USER:-mata}" -q 2>/dev/null && return 0
    sleep 2
  done
  echo "ОШИБКА: БД не поднялась за 2 минуты"; exit 1
}

case "${1:-}" in
  setup)
    write_conf
    echo "== Контейнер БД с архивом WAL (перезапуск ~10–30 с) =="
    "${COMPOSE[@]}" up -d --build db
    wait_db
    echo "== Stanza и проверка доставки WAL =="
    pgbr stanza-create
    pgbr check
    # Первая полная копия — в каждое хранилище, где её ещё нет (при двух хранилищах
    # pgBackRest без --repo пишет копию только в первое).
    have=$(pgbr info --output=json | python3 -c 'import sys,json
d = json.load(sys.stdin)
print(" ".join(sorted({str(b["database"]["repo-key"]) for b in (d[0].get("backup") or [])})) if d else "")')
    for repo in 1 2; do
      grep -q "^repo${repo}-type=" "$CONF_DIR/pgbackrest.conf" || continue
      case " $have " in
        *" $repo "*) echo "Хранилище $repo: полная копия уже есть." ;;
        *) echo "== Первая полная копия → хранилище $repo =="; pgbr --repo="$repo" --type=full backup ;;
      esac
    done
    pgbr info
    ;;
  backup)
    # Крон зовёт и там, где копия ещё не настроена (нет ключей хранилищ) — тихо выходим.
    [ -s "$CONF_DIR/pgbackrest.conf" ] || { echo "pgBackRest не настроен (./deploy/pgbr.sh setup) — пропуск"; exit 0; }
    type="${2:-diff}"
    case "$type" in full|diff|incr) ;; *) echo "Тип копии: full | diff | incr"; exit 1 ;; esac
    # Копия идёт во ВСЕ хранилища по очереди: недоступность одного не отменяет второе.
    rc=0
    for repo in 1 2; do
      grep -q "^repo${repo}-type=" "$CONF_DIR/pgbackrest.conf" 2>/dev/null || continue
      echo "== Копия $type → хранилище $repo =="
      pgbr --repo="$repo" --type="$type" backup || { echo "ОШИБКА: хранилище $repo"; rc=1; }
    done
    exit "$rc"
    ;;
  check)
    pgbr check
    ;;
  info)
    pgbr info
    ;;
  restore)
    repo="${2:-1}"
    case "$repo" in 1|2) ;; *) echo "Хранилище: 1 (Яндекс) или 2 (Beget)"; exit 1 ;; esac
    PGDATA_HOST="$DATA/pgdata"
    if [ -n "$(ls -A "$PGDATA_HOST" 2>/dev/null)" ]; then
      echo "ОШИБКА: $PGDATA_HOST не пуст — восстанавливаю только в пустой каталог (новый сервер)"; exit 1
    fi
    write_conf
    install -d -m 0700 "$PGDATA_HOST"
    chown "$PG_UID:$PG_UID" "$PGDATA_HOST"
    "${COMPOSE[@]}" stop db >/dev/null 2>&1 || true
    echo "== Восстановление из хранилища $repo =="
    if ! "${COMPOSE[@]}" run --rm --no-deps -u postgres --entrypoint pgbackrest db \
         --stanza=mata --repo="$repo" restore; then
      # Недовосстановленный каталог нельзя оставлять: следующая попытка (другое хранилище
      # или ночной дамп) требует пустого места, а PostgreSQL на обрывке не стартует.
      find "$PGDATA_HOST" -mindepth 1 -delete 2>/dev/null || true
      echo "ОШИБКА: восстановление из хранилища $repo не удалось — каталог БД очищен"; exit 1
    fi
    echo "== Старт БД: догоняет архив WAL до последнего сегмента и становится основной =="
    "${COMPOSE[@]}" up -d db
    wait_db
    # Догнала архив — вышла из режима восстановления (pg_is_in_recovery = f).
    for _ in $(seq 1 90); do
      st=$("${COMPOSE[@]}" exec -T db psql -X -U "${POSTGRES_USER:-mata}" -d "${POSTGRES_DB:-mata}" -tAc 'select pg_is_in_recovery()' 2>/dev/null || true)
      [ "$st" = "f" ] && { echo "Готово: БД восстановлена и принимает запись."; exit 0; }
      sleep 2
    done
    echo "ОШИБКА: БД не вышла из восстановления за 3 минуты — смотреть логи db"; exit 1
    ;;
  *)
    sed -n '2,13p' "$0"; exit 1 ;;
esac
