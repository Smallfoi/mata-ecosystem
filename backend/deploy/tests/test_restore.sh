#!/usr/bin/env bash
# Модельный прогон deploy/restore.sh (аудит E02).
#  - Заглушка docker моделирует каталог БД (файл на базу) и psql: с ON_ERROR_STOP первая
#    ошибка в дампе = код 3; без него psql идёт дальше (как настоящий).
#  - DEPLOY_TEST_REAL_PG=1 — дополнительно прогон на НАСТОЯЩЕМ postgis в одноразовом
#    контейнере (нужен docker; в CI включено).
# Проверяем: живая БД не трогается до проверки новой; ошибки контрольного бэкапа/загрузки/
# проверок останавливают восстановление; переключение атомарно; прежняя БД сохраняется.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="$HERE/../restore.sh"
BASE="${DEPLOY_TEST_TMP:-$(mktemp -d)}"
mkdir -p "$BASE"
fails=0
ok()  { echo "  ok   $*"; }
bad() { echo "  FAIL $*"; fails=$((fails + 1)); }
REAL_DOCKER="$(command -v docker || true)"

# Общая часть песочницы: backend/{deploy/restore.sh,.env}, заглушки backup.sh и smoke.sh.
make_base() {
  local sb; sb="$(mktemp -d "$BASE/restore.XXXXXX")"
  mkdir -p "$sb/backend/deploy" "$sb/bin" "$sb/state/dbs"
  cp "$SRC" "$sb/backend/deploy/restore.sh"
  printf 'POSTGRES_DB=mata\nPOSTGRES_USER=mata\n' > "$sb/backend/.env"
  cat > "$sb/backend/deploy/backup.sh" <<'STUB'
#!/usr/bin/env bash
cat > /dev/null   # pg_dump через `docker compose exec` съедает stdin
echo "BACKUP" >> "$STUB_STATE/calls.log"; exit "${STUB_BACKUP_RC:-0}"
STUB
  cat > "$sb/backend/deploy/smoke.sh" <<'STUB'
#!/usr/bin/env bash
echo "SMOKE" >> "$STUB_STATE/calls.log"; exit "${STUB_SMOKE_RC:-0}"
STUB
  chmod +x "$sb/backend/deploy/"*.sh
  : > "$sb/state/calls.log"
  echo "$sb"
}

# ── Модельная заглушка docker ────────────────────────────────────────────────
make_stub_sandbox() {
  local sb; sb="$(make_base)"
  printf -- '-- MIG=120\n-- TABLES=80\nLIVEDATA\n' > "$sb/state/dbs/mata"
  cat > "$sb/bin/docker" <<'STUB'
#!/usr/bin/env bash
# docker compose -f X --env-file Y <stop|up|exec -T db ...>
ST="$STUB_STATE"; DBS="$ST/dbs"
args=("$@"); i=0
while [ $i -lt ${#args[@]} ]; do
  case "${args[$i]}" in stop|up|exec) break ;; esac; i=$((i + 1))
done
verb="${args[$i]:-}"
case "$verb" in
  stop|up) echo "COMPOSE ${args[*]:$i}" >> "$ST/calls.log"; exit 0 ;;
  exec) ;;
  *) echo "stub docker: unexpected: $*" >&2; exit 2 ;;
esac
cmd=("${args[@]:$((i + 3))}")      # после «exec -T db»
case "${cmd[0]}" in
  df) cat > /dev/null; printf 'Filesystem 1024-blocks Used Available Capacity Mounted\n/dev/vdb 100000000 1000 %s 1%% /var/lib/postgresql/data\n' "${STUB_FREE_KB:-99999999}"; exit 0 ;;
  psql) ;;
  *) echo "stub docker: unexpected exec: ${cmd[*]}" >&2; exit 2 ;;
esac
db=""; sql=""; onerr=0; single=0; j=1
while [ $j -lt ${#cmd[@]} ]; do
  case "${cmd[$j]}" in
    -d) j=$((j + 1)); db="${cmd[$j]}" ;;
    -c|-tAc) j=$((j + 1)); sql="${cmd[$j]}" ;;
    ON_ERROR_STOP=1) onerr=1 ;;
    --single-transaction|-1) single=1 ;;
  esac
  j=$((j + 1))
done
[ "$db" = postgres ] || [ -f "$DBS/$db" ] || { echo "psql: database \"$db\" does not exist" >&2; exit 2; }
field() { sed -n "s/^-- $1=//p" "$DBS/$2" | head -n 1; }
if [ -n "$sql" ]; then
  cat > /dev/null      # как настоящий `docker compose exec`: без < /dev/null съест ввод терминала
  echo "SQL db=$db $sql" >> "$ST/calls.log"
  case "$sql" in
    *"CREATE DATABASE"*) n=$(printf '%s' "$sql" | sed -n 's/.*CREATE DATABASE "\([^"]*\)".*/\1/p'); : > "$DBS/$n" ;;
    *"DROP DATABASE"*)   n=$(printf '%s' "$sql" | sed -n 's/.*DROP DATABASE IF EXISTS "\([^"]*\)".*/\1/p'); rm -f "$DBS/$n" ;;
    *pg_database_size*)  echo 1000000 ;;
    *django_migrations*) v=$(field MIG "$db"); [ -n "$v" ] || { echo 'relation "django_migrations" does not exist' >&2; exit 1; }; echo "$v" ;;
    *information_schema.tables*) v=$(field TABLES "$db"); echo "${v:-0}" ;;
    *) echo "stub psql: unknown SQL: $sql" >&2; exit 2 ;;
  esac
  exit 0
fi
body="$(cat)"
case "$body" in
  *"ALTER DATABASE"*)
    echo "RENAME $(printf '%s' "$body" | grep -c 'ALTER DATABASE') stmts" >> "$ST/calls.log"
    [ "${STUB_RENAME_FAIL:-0}" = 1 ] && { echo 'ERROR: database "mata" is being accessed by other users' >&2; exit 3; }
    tmpd="$(mktemp -d "$ST/tx.XXXX")"; cp "$DBS"/* "$tmpd"/
    while IFS= read -r line; do
      from=$(printf '%s' "$line" | sed -n 's/^ALTER DATABASE "\([^"]*\)" RENAME TO "\([^"]*\)";$/\1/p')
      to=$(printf '%s' "$line"   | sed -n 's/^ALTER DATABASE "\([^"]*\)" RENAME TO "\([^"]*\)";$/\2/p')
      [ -n "$from" ] && mv "$tmpd/$from" "$tmpd/$to"
    done <<< "$body"
    rm -f "$DBS"/*; mv "$tmpd"/* "$DBS"/; rmdir "$tmpd"
    exit 0 ;;
esac
echo "LOAD db=$db onerr=$onerr single=$single" >> "$ST/calls.log"
if printf '%s' "$body" | grep -q 'FAIL_HERE'; then
  echo 'ERROR:  syntax error at or near "FAIL_HERE"' >&2
  if [ "$onerr" = 1 ]; then exit 3; fi   # без ON_ERROR_STOP psql идёт дальше и отдаёт 0
fi
printf '%s\n' "$body" > "$DBS/$db"
exit 0
STUB
  chmod +x "$sb/bin/docker"
  echo "$sb"
}

make_dump() {  # make_dump <файл.gz> <mig> <marker 0|1> <fail 0|1>
  { printf -- '-- MIG=%s\n-- TABLES=80\nRESTOREDDATA\n' "$2"
    [ "$4" = 1 ] && printf 'FAIL_HERE;\n'
    [ "$3" = 1 ] && printf -- '--\n-- PostgreSQL database dump complete\n--\n'
  } | gzip > "$1"
}

run_restore() {  # run_restore <sandbox> <dump> <ответы stdin>
  local sb="$1"
  printf '%b' "$3" | STUB_STATE="$sb/state" PATH="$sb/bin:$PATH" \
    bash "$sb/backend/deploy/restore.sh" "$2" > "$sb/out.log" 2>&1
}

has()   { grep -q -- "$2" "$1/state/calls.log"; }
live()  { cat "$1/state/dbs/mata" 2>/dev/null; }
count_restore_dbs() { find "$1/state/dbs" -name 'mata_restore_*' | wc -l | tr -d ' '; }
show()  { sed 's/^/       | /' "$1/out.log"; sed 's/^/       > /' "$1/state/calls.log"; }

echo "E02-1: штатное восстановление через отдельную БД"
SB="$(make_stub_sandbox)"; make_dump "$SB/d.sql.gz" 118 1 0
run_restore "$SB" "$SB/d.sql.gz" 'yes\nyes\n'; rc=$?
[ "$rc" = 0 ] && ok "код 0" || { bad "код $rc"; show "$SB"; }
grep -q 'LOAD db=mata ' "$SB/state/calls.log" && bad "дамп грузился прямо в живую БД" || ok "живая БД под загрузку не попала"
grep -q 'LOAD db=mata_restore_.* onerr=1 single=1' "$SB/state/calls.log" \
  && ok "загрузка в mata_restore_* c ON_ERROR_STOP и одной транзакцией" || bad "нет загрузки в новую БД с ON_ERROR_STOP"
order=$(grep -o -E '^(BACKUP|SQL db=postgres CREATE DATABASE|LOAD|COMPOSE stop|RENAME|COMPOSE up|SMOKE)' "$SB/state/calls.log" | tr '\n' ',')
[ "$order" = "BACKUP,SQL db=postgres CREATE DATABASE,LOAD,COMPOSE stop,RENAME,COMPOSE up,SMOKE," ] \
  && ok "порядок: бэкап → новая БД → загрузка → стоп → переключение → старт → smoke" || bad "порядок: $order"
live "$SB" | grep -q RESTOREDDATA && ok "живое имя БД теперь указывает на восстановленные данные" || bad "данные не восстановлены"
old=$(find "$SB/state/dbs" -name 'mata_pre_restore_*' | head -n 1)
[ -n "$old" ] && grep -q LIVEDATA "$old" && ok "прежняя БД сохранена: $(basename "$old")" || bad "прежняя БД не сохранена"

echo "E02-2: контрольный бэкап упал → стоп, ничего не тронуто"
SB="$(make_stub_sandbox)"; make_dump "$SB/d.sql.gz" 118 1 0
STUB_BACKUP_RC=1 run_restore "$SB" "$SB/d.sql.gz" 'yes\nyes\n'; rc=$?
[ "$rc" != 0 ] && ok "код $rc" || bad "ошибка контрольного бэкапа проигнорирована"
has "$SB" 'LOAD' && bad "дамп всё равно грузился" || ok "дамп не грузился"
live "$SB" | grep -q LIVEDATA && ok "живая БД цела" || bad "живая БД изменена"

echo "E02-3: ошибка SQL в дампе → загрузка остановлена, живая БД цела, новая удалена"
SB="$(make_stub_sandbox)"; make_dump "$SB/d.sql.gz" 118 1 1
run_restore "$SB" "$SB/d.sql.gz" 'yes\nyes\n'; rc=$?
[ "$rc" != 0 ] && ok "код $rc" || bad "ошибка в дампе не остановила восстановление"
has "$SB" 'COMPOSE stop' && bad "приложение останавливали" || ok "приложение не останавливали"
live "$SB" | grep -q LIVEDATA && ok "живая БД цела" || bad "живая БД изменена"
[ "$(count_restore_dbs "$SB")" = 0 ] && ok "недогруженная БД удалена" || bad "недогруженная БД осталась"

echo "E02-4: в дампе нет схемы Django → проверка до переключения не пускает"
SB="$(make_stub_sandbox)"; make_dump "$SB/d.sql.gz" 0 1 0
run_restore "$SB" "$SB/d.sql.gz" 'yes\nyes\n'; rc=$?
[ "$rc" != 0 ] && ok "код $rc" || bad "пустая схема прошла проверку"
has "$SB" 'RENAME' && bad "переключение было" || ok "переключения не было"
live "$SB" | grep -q LIVEDATA && ok "живая БД цела" || bad "живая БД изменена"

echo "E02-5: оборванный дамп (нет метки конца) → отказ до любых действий"
SB="$(make_stub_sandbox)"; make_dump "$SB/d.sql.gz" 118 0 0
run_restore "$SB" "$SB/d.sql.gz" 'yes\nyes\n'; rc=$?
[ "$rc" != 0 ] && ok "код $rc" || bad "оборванный дамп принят"
has "$SB" 'BACKUP' || has "$SB" 'LOAD' && bad "начались действия" || ok "никаких действий"

echo "E02-6: переключение не удалось → приложение поднято на прежней БД"
SB="$(make_stub_sandbox)"; make_dump "$SB/d.sql.gz" 118 1 0
STUB_RENAME_FAIL=1 run_restore "$SB" "$SB/d.sql.gz" 'yes\nyes\n'; rc=$?
[ "$rc" != 0 ] && ok "код $rc" || bad "сбой переключения не замечен"
live "$SB" | grep -q LIVEDATA && ok "живая БД цела" || bad "живая БД изменена"
tail -n 1 "$SB/state/calls.log" | grep -q 'COMPOSE up' && ok "web/worker/beat подняты обратно" || bad "сервисы остались остановлены"

echo "E02-7: отказ на втором подтверждении → без переключения, новая БД удалена"
SB="$(make_stub_sandbox)"; make_dump "$SB/d.sql.gz" 118 1 0
run_restore "$SB" "$SB/d.sql.gz" 'yes\nno\n'; rc=$?
[ "$rc" != 0 ] && ok "код $rc" || bad "код 0 при отказе"
has "$SB" 'COMPOSE stop' && bad "приложение останавливали" || ok "приложение не останавливали"
[ "$(count_restore_dbs "$SB")" = 0 ] && ok "новая БД удалена" || bad "новая БД осталась"

echo "E02-8: мало места под вторую копию → отказ"
SB="$(make_stub_sandbox)"; make_dump "$SB/d.sql.gz" 118 1 0
STUB_FREE_KB=100 run_restore "$SB" "$SB/d.sql.gz" 'yes\nyes\n'; rc=$?
[ "$rc" != 0 ] && ok "код $rc" || bad "нехватка места не замечена"
has "$SB" 'BACKUP' && bad "начались действия" || ok "никаких действий"

# ── Прогон на настоящем PostgreSQL/PostGIS ───────────────────────────────────
if [ "${DEPLOY_TEST_REAL_PG:-0}" = 1 ] && [ -n "$REAL_DOCKER" ]; then
  echo "E02-real: настоящий postgis — восстановление, битый дамп, откат"
  export MSYS_NO_PATHCONV=1          # git-bash на Windows не должен переписывать /var/... в C:/...
  PGC="mata-restore-test-$$"
  trap '"$REAL_DOCKER" rm -f "$PGC" >/dev/null 2>&1' EXIT
  "$REAL_DOCKER" run -d --name "$PGC" -e POSTGRES_DB=mata -e POSTGRES_USER=mata \
    -e POSTGRES_PASSWORD=test postgis/postgis:16-3.4 >/dev/null
  # Ждём окончания init-скриптов postgis (сервер перезапускается один раз).
  for _ in $(seq 1 90); do
    [ "$("$REAL_DOCKER" logs "$PGC" 2>&1 | grep -c 'ready to accept connections')" -ge 2 ] && break; sleep 2
  done
  pg() { "$REAL_DOCKER" exec -i "$PGC" psql -X -v ON_ERROR_STOP=1 -U mata "$@"; }
  pg -d mata -q -c "CREATE TABLE django_migrations (id serial, name text);
                    INSERT INTO django_migrations(name) SELECT 'm'||g FROM generate_series(1,5) g;" \
    -c "DO \$\$ BEGIN FOR i IN 1..12 LOOP EXECUTE format('CREATE TABLE t%s (v text)', i); END LOOP; END \$\$;" \
    -c "INSERT INTO t1 VALUES ('BACKUP_STATE')"
  SB="$(make_base)"
  "$REAL_DOCKER" exec "$PGC" pg_dump -U mata mata | gzip > "$SB/good.sql.gz"
  # Битый дамп: ошибка в середине, метка конца на месте (как оборванный COPY/чужая схема).
  gzip -dc "$SB/good.sql.gz" | awk '/PostgreSQL database dump complete/ && !x {print "SELECT no_such_function();"; x=1} {print}' \
    | gzip > "$SB/broken.sql.gz"
  pg -d mata -q -c "UPDATE t1 SET v = 'LIVE_STATE'"
  cat > "$SB/bin/docker" <<STUB
#!/usr/bin/env bash
# compose exec -T db … → docker exec -i <тестовый контейнер> …; stop/up — только в журнал.
args=("\$@"); i=0
while [ \$i -lt \${#args[@]} ]; do case "\${args[\$i]}" in stop|up|exec) break ;; esac; i=\$((i + 1)); done
case "\${args[\$i]}" in
  stop|up) echo "COMPOSE \${args[*]:\$i}" >> "\$STUB_STATE/calls.log"; exit 0 ;;
  exec) exec "$REAL_DOCKER" exec -i "$PGC" "\${args[@]:\$((i + 3))}" ;;
esac
exit 2
STUB
  chmod +x "$SB/bin/docker"
  val() { pg -d "$1" -tAc "SELECT v FROM t1" 2>/dev/null; }
  dbs() { pg -d postgres -tAc "SELECT string_agg(datname, ',' ORDER BY datname) FROM pg_database WHERE datname LIKE 'mata%'"; }

  run_restore "$SB" "$SB/broken.sql.gz" 'yes\nyes\n'; rc=$?
  [ "$rc" != 0 ] && ok "битый дамп: код $rc" || { bad "битый дамп принят"; show "$SB"; }
  [ "$(val mata)" = LIVE_STATE ] && ok "битый дамп: живая БД цела" || bad "битый дамп: живая БД изменена"
  [ "$(dbs)" = mata ] && ok "битый дамп: временная БД удалена" || bad "битый дамп: остались $(dbs)"

  sleep 1  # другой TS у имён БД
  run_restore "$SB" "$SB/good.sql.gz" 'yes\nyes\n'; rc=$?
  [ "$rc" = 0 ] && ok "восстановление: код 0" || { bad "восстановление: код $rc"; show "$SB"; }
  [ "$(val mata)" = BACKUP_STATE ] && ok "восстановление: данные из бэкапа" || bad "восстановление: в mata '$(val mata)'"
  OLDDB=$(pg -d postgres -tAc "SELECT datname FROM pg_database WHERE datname LIKE 'mata_pre_restore_%'")
  [ -n "$OLDDB" ] && [ "$(val "$OLDDB")" = LIVE_STATE ] && ok "прежняя БД сохранена: $OLDDB" || bad "прежняя БД не сохранена"
  # Откат командами, которые печатает restore.sh.
  rb=$(grep -o "ALTER DATABASE[^']*" "$SB/out.log" | tail -n 2)
  while IFS= read -r s; do pg -d postgres -q -c "$s" < /dev/null; done <<< "$rb"
  [ "$(val mata)" = LIVE_STATE ] && ok "откат по напечатанным командам вернул прежнюю БД" || bad "откат не сработал"
  "$REAL_DOCKER" rm -f "$PGC" >/dev/null
fi

if command -v shellcheck >/dev/null 2>&1; then
  (cd "$HERE/.." && shellcheck -S warning restore.sh) && ok "shellcheck restore.sh" || bad "shellcheck restore.sh"
fi

[ -z "${DEPLOY_TEST_TMP:-}" ] && rm -rf "$BASE"
[ "$fails" = 0 ] || { echo "test_restore: $fails провал(ов)"; exit 1; }
echo "test_restore: OK"
