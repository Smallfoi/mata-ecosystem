#!/usr/bin/env bash
# Модельный прогон deploy/backup.sh (аудит E03) с заглушкой docker.
# Воспроизводит: дамп больше ~200 КБ → `gzip -dc | head -c` под pipefail ловил SIGPIPE
# (код 141) и валил бэкап; обрыв/недописанный дамп не должен считаться бэкапом.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="$HERE/../backup.sh"
BASE="${DEPLOY_TEST_TMP:-$(mktemp -d)}"
mkdir -p "$BASE"
fails=0
ok()  { echo "  ok   $*"; }
bad() { echo "  FAIL $*"; fails=$((fails + 1)); }

# Песочница: backend/{deploy/backup.sh,.env} + bin/docker (заглушка pg_dump).
make_sandbox() {
  local sb; sb="$(mktemp -d "$BASE/backup.XXXXXX")"
  mkdir -p "$sb/backend/deploy" "$sb/bin"
  cp "$SRC" "$sb/backend/deploy/backup.sh"
  printf 'POSTGRES_DB=mata\nPOSTGRES_USER=mata\n' > "$sb/backend/.env"
  cat > "$sb/bin/docker" <<'STUB'
#!/usr/bin/env bash
# Заглушка `docker compose ... exec -T db pg_dump ...`: синтетический дамп.
# STUB_DUMP_BYTES — объём тела; STUB_DUMP_MODE: ok | truncated | fail.
case " $* " in *" pg_dump "*) ;; *) echo "stub docker: unexpected: $*" >&2; exit 2 ;; esac
printf -- '--\n-- PostgreSQL database dump\n--\nSET statement_timeout = 0;\n'
yes "INSERT INTO public.loyalty_txn VALUES (1, 'synthetic row for backup test', 100);" \
  | head -c "${STUB_DUMP_BYTES:-5000000}"
printf '\n'
case "${STUB_DUMP_MODE:-ok}" in
  ok)        printf -- '--\n-- PostgreSQL database dump complete\n--\n' ;;
  truncated) : ;;                                   # дамп оборвался, код 0
  fail)      echo "pg_dump: error: connection lost" >&2; exit 1 ;;
esac
STUB
  chmod +x "$sb/bin/docker"
  echo "$sb"
}

run_backup() {  # run_backup <sandbox> → код выхода backup.sh
  local sb="$1"
  PATH="$sb/bin:$PATH" bash "$sb/backend/deploy/backup.sh" > "$sb/out.log" 2>&1
}

dumps() { find "$1/backend/backups" -maxdepth 1 -name 'mata_*' 2>/dev/null | wc -l | tr -d ' '; }

echo "E03-1: большой дамп (5 МБ) проходит проверку без SIGPIPE"
SB="$(make_sandbox)"
STUB_DUMP_BYTES=5000000 STUB_DUMP_MODE=ok run_backup "$SB"; rc=$?
if [ "$rc" = 0 ]; then ok "код 0"; else bad "код $rc (141 = SIGPIPE)"; sed 's/^/       /' "$SB/out.log"; fi
f="$(find "$SB/backend/backups" -name 'mata_*.sql.gz' 2>/dev/null | head -n 1)"
if [ -n "$f" ] && gzip -t "$f" && [ "$(gzip -dc "$f" | wc -c)" -gt 5000000 ]; then
  ok "дамп целый: $(basename "$f")"
else
  bad "дамп не создан или битый"
fi
[ "$(dumps "$SB")" = 1 ] && ok "ровно один файл дампа" || bad "файлов дампа: $(dumps "$SB")"

echo "E03-2: pg_dump упал на середине → бэкап провален, недописанный файл убран"
SB="$(make_sandbox)"
STUB_DUMP_BYTES=1000000 STUB_DUMP_MODE=fail run_backup "$SB"; rc=$?
[ "$rc" != 0 ] && ok "код $rc" || bad "код 0 при упавшем pg_dump"
[ "$(dumps "$SB")" = 0 ] && ok "обрывка дампа не осталось" || bad "остался файл-обрывок"

echo "E03-3: дамп без финальной метки pg_dump (оборван, код 0) → провал"
SB="$(make_sandbox)"
STUB_DUMP_BYTES=1000000 STUB_DUMP_MODE=truncated run_backup "$SB"; rc=$?
[ "$rc" != 0 ] && ok "код $rc" || bad "недописанный дамп принят за бэкап"
[ "$(dumps "$SB")" = 0 ] && ok "обрывка дампа не осталось" || bad "остался файл-обрывок"

echo "E03-4: подозрительно маленький дамп → провал"
SB="$(make_sandbox)"
STUB_DUMP_BYTES=10 STUB_DUMP_MODE=ok run_backup "$SB"; rc=$?
[ "$rc" != 0 ] && ok "код $rc" || bad "пустой дамп принят за бэкап"

if command -v shellcheck >/dev/null 2>&1; then
  (cd "$HERE/.." && shellcheck -S warning backup.sh) && ok "shellcheck backup.sh" || bad "shellcheck backup.sh"
fi

[ -z "${DEPLOY_TEST_TMP:-}" ] && rm -rf "$BASE"
[ "$fails" = 0 ] || { echo "test_backup: $fails провал(ов)"; exit 1; }
echo "test_backup: OK"
