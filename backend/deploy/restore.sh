#!/usr/bin/env bash
# Восстановление прод-БД STAW из бэкапа backup.sh — через ОТДЕЛЬНУЮ БД (аудит E02).
# Запуск НА СЕРВЕРЕ из backend/:  ./deploy/restore.sh backups/mata_YYYYMMDD_HHMMSS.sql.gz[.enc]
#
# Порядок (живая БД не трогается, пока новая не проверена):
#   1) проверка файла целиком (архив цел, дамп дописан до конца, хватает места на диске);
#   2) контрольный бэкап текущей БД — ОБЯЗАТЕЛЕН: его ошибка = стоп. Осознанно пропустить
#      (живая БД мертва и бэкапить нечего): RESTORE_SKIP_CONTROL_BACKUP=1;
#   3) дамп грузится в НОВУЮ БД <db>_restore_<ts>: psql -v ON_ERROR_STOP=1 --single-transaction —
#      первая же ошибка откатывает загрузку целиком, новая БД удаляется;
#   4) проверки новой БД (миграции Django, число таблиц) + сверка с живой — ДО переключения;
#   5) второе подтверждение → стоп web/worker/beat → ОДНОЙ транзакцией: живая БД →
#      <db>_pre_restore_<ts>, новая → <db> → старт web/worker/beat → smoke-тест.
#   Прежняя БД остаётся под именем <db>_pre_restore_<ts>: откат — команды в конце вывода.
set -euo pipefail

cd "$(dirname "$0")/.."  # → backend/
FILE="${1:-}"
[ -n "$FILE" ] && [ -f "$FILE" ] || { echo "Использование: ./deploy/restore.sh <файл.sql.gz[.enc]>"; exit 1; }
[ -f .env ] || { echo "Нет .env"; exit 1; }
set -a; . ./.env; set +a

COMPOSE="docker compose -f docker-compose.prod.yml --env-file .env"
TS=$(date +%Y%m%d_%H%M%S)
DB="${POSTGRES_DB}"
NEW="${DB}_restore_${TS}"        # сюда грузим дамп
OLD="${DB}_pre_restore_${TS}"    # под этим именем останется прежняя БД
PGU="${POSTGRES_USER}"
STAGE=""                         # этап для уборки при сбое (см. cleanup)

# psql внутри контейнера db. -X: без ~/.psqlrc; ON_ERROR_STOP: ошибка = ненулевой код.
psql_db() {  # psql_db <база> [аргументы psql...]
  local d="$1"; shift
  $COMPOSE exec -T db psql -X -v ON_ERROR_STOP=1 -U "$PGU" -d "$d" "$@"
}
# q <база> <SQL> → одно значение. stdin закрыт: `docker compose exec` иначе съедает
# ввод терминала (ответы 'yes' на подтверждения).
q() { psql_db "$1" -tAc "$2" < /dev/null; }

# Поток дампа: .enc расшифровываем на лету — открытым на диск не кладём.
dump_stream() {
  case "$FILE" in
    *.enc) openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 \
             -in "$FILE" -pass env:BACKUP_ENCRYPT_PASSPHRASE | gzip -dc ;;
    *)     gzip -dc "$FILE" ;;
  esac
}

case "$FILE" in
  *.enc) [ -n "${BACKUP_ENCRYPT_PASSPHRASE:-}" ] || {
           echo "Файл зашифрован, а BACKUP_ENCRYPT_PASSPHRASE не задан в .env"; exit 1; } ;;
esac

# ── 1. Проверка файла и места ДО любых действий ──────────────────────────────
echo "Проверяю файл дампа целиком..."
# Читаем поток до конца (без head/grep -q — под pipefail они дают SIGPIPE, см. E03).
DUMP_BYTES=$(dump_stream | wc -c) || { echo "ОШИБКА: файл не читается/не расшифровывается"; exit 1; }
LAST=$(dump_stream | tail -c 4096)
case "$LAST" in
  *"PostgreSQL database dump complete"*) ;;
  *) echo "ОШИБКА: дамп оборван (нет финальной метки pg_dump) — восстанавливать нельзя"; exit 1 ;;
esac
echo "  дамп цел: $DUMP_BYTES байт SQL"

LIVE_SIZE=$(q postgres "SELECT COALESCE((SELECT pg_database_size(datname) FROM pg_database WHERE datname = '$DB'), 0)")
FREE_KB=$($COMPOSE exec -T db df -Pk /var/lib/postgresql/data < /dev/null | awk 'NR==2 {print $4}')
# Новой БД нужно примерно столько же, сколько живой (+ контрольный бэкап и запас).
NEED_KB=$(( (LIVE_SIZE > DUMP_BYTES ? LIVE_SIZE : DUMP_BYTES) * 3 / 2 / 1024 ))
echo "  место: свободно ${FREE_KB} КБ, нужно ~${NEED_KB} КБ"
if [ "${FREE_KB:-0}" -lt "$NEED_KB" ] && [ "${RESTORE_SKIP_SPACE_CHECK:-0}" != 1 ]; then
  echo "ОШИБКА: мало места под вторую копию БД (обойти осознанно: RESTORE_SKIP_SPACE_CHECK=1)"; exit 1
fi

echo "ВОССТАНОВЛЕНИЕ БД '${DB}' из $FILE"
echo "  дамп грузится в НОВУЮ БД '${NEW}'; живая БД не трогается до проверки и второго подтверждения."
read -r -p "Продолжить? (введите 'yes'): " ans
[ "$ans" = "yes" ] || { echo "Отменено."; exit 1; }

# ── 2. Контрольный бэкап — обязателен ────────────────────────────────────────
if [ "${RESTORE_SKIP_CONTROL_BACKUP:-0}" = 1 ]; then
  echo "ВНИМАНИЕ: контрольный бэкап пропущен (RESTORE_SKIP_CONTROL_BACKUP=1)."
else
  echo "Контрольный бэкап текущей БД..."
  ./deploy/backup.sh < /dev/null || {
    echo "ОШИБКА: контрольный бэкап не удался — восстановление остановлено, ничего не изменено."
    echo "  (если живая БД мертва и бэкапить нечего: RESTORE_SKIP_CONTROL_BACKUP=1)"; exit 1; }
fi

# ── 3. Загрузка в новую изолированную БД ─────────────────────────────────────
STAGE=load
cleanup() {
  local rc=$?
  case "$STAGE" in
    load|verify)
      echo "Восстановление НЕ выполнено — удаляю недогруженную БД '${NEW}'; живая БД не тронута."
      q postgres "DROP DATABASE IF EXISTS \"$NEW\"" >/dev/null 2>&1 || \
        echo "  (не удалось удалить '${NEW}' — удалить вручную)" ;;
    switch)
      echo "Переключение НЕ выполнено — поднимаю web/worker/beat на прежней БД '${DB}'."
      $COMPOSE up -d web worker beat || true
      echo "  новая БД осталась как '${NEW}' (проверить/удалить вручную)." ;;
  esac
  exit "$rc"
}
trap cleanup EXIT

echo "Создаю БД '${NEW}'..."
q postgres "CREATE DATABASE \"$NEW\" TEMPLATE template0" >/dev/null
echo "Гружу дамп в '${NEW}' (ON_ERROR_STOP, одна транзакция)..."
dump_stream | psql_db "$NEW" -q --single-transaction >/dev/null

# ── 4. Проверки ДО переключения ──────────────────────────────────────────────
STAGE=verify
NEW_MIG=$(q "$NEW" "SELECT count(*) FROM django_migrations")
NEW_TABLES=$(q "$NEW" "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'")
LIVE_MIG=$(q "$DB" "SELECT count(*) FROM django_migrations" 2>/dev/null || echo "?")
LIVE_TABLES=$(q "$DB" "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'" 2>/dev/null || echo "?")
echo "Проверка:            новая БД | живая БД"
echo "  миграций Django:   ${NEW_MIG} | ${LIVE_MIG}"
echo "  таблиц в public:   ${NEW_TABLES} | ${LIVE_TABLES}"
[ "${NEW_MIG:-0}" -gt 0 ] && [ "${NEW_TABLES:-0}" -gt 10 ] || {
  echo "ОШИБКА: в восстановленной БД нет схемы Django — не переключаю"; exit 1; }

read -r -p "Переключить приложение на восстановленную БД? (введите 'yes'): " ans2
[ "$ans2" = "yes" ] || { echo "Отменено до переключения."; exit 1; }

# ── 5. Переключение ─────────────────────────────────────────────────────────
STAGE=switch
echo "Останавливаю web/worker/beat..."
$COMPOSE stop web worker beat
echo "Меняю БД местами одной транзакцией: '${DB}' → '${OLD}', '${NEW}' → '${DB}'..."
switched=0
for attempt in 1 2 3; do
  if psql_db postgres <<SQL
SELECT pg_terminate_backend(pid) FROM pg_stat_activity
 WHERE datname IN ('$DB', '$NEW') AND pid <> pg_backend_pid();
BEGIN;
ALTER DATABASE "$DB" RENAME TO "$OLD";
ALTER DATABASE "$NEW" RENAME TO "$DB";
COMMIT;
SQL
  then switched=1; break; fi
  echo "  попытка $attempt не удалась (к БД кто-то подключён?) — повтор через 3 с"; sleep 3
done
[ "$switched" = 1 ] || { echo "ОШИБКА: переключить БД не удалось"; exit 1; }
STAGE=switched

echo "Поднимаю web/worker/beat (web сам догонит миграции)..."
$COMPOSE up -d web worker beat || echo "ВНИМАНИЕ: up -d вернул ошибку — решит smoke-тест ниже"

ROLLBACK="  $COMPOSE stop web worker beat
  $COMPOSE exec -T db psql -X -v ON_ERROR_STOP=1 -U $PGU -d postgres \\
    -c 'ALTER DATABASE \"$DB\" RENAME TO \"${DB}_failed_${TS}\"' -c 'ALTER DATABASE \"$OLD\" RENAME TO \"$DB\"'
  $COMPOSE up -d web worker beat"

smoke_ok=0
for i in $(seq 1 12); do
  sleep 10
  if ./deploy/smoke.sh; then smoke_ok=1; break; fi
  echo "  smoke ещё не прошёл ($i/12)..."
done
if [ "$smoke_ok" != 1 ]; then
  echo "ОШИБКА: после переключения smoke-тест не проходит. Откат на прежнюю БД:"
  echo "$ROLLBACK"
  exit 1
fi
echo "Готово: БД '${DB}' восстановлена из $FILE. Прежняя БД сохранена как '${OLD}'."
echo "Откат (если что-то не так):"
echo "$ROLLBACK"
echo "Когда убедишься, что всё в порядке, освободить место:"
echo "  $COMPOSE exec -T db psql -U $PGU -d postgres -c 'DROP DATABASE \"$OLD\"'"
