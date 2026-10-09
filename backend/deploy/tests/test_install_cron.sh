#!/usr/bin/env bash
# Модельный прогон deploy/install-cron.sh с заглушкой crontab.
# Воспроизводит 9.10.2026 (VPS Beget): на сервере без расписания `crontab -l` даёт ошибку,
# и прежний конвейер под pipefail не ставил НИ ОДНОЙ строки, обрывая prod-deploy.sh.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="$HERE/../install-cron.sh"
BASE="${DEPLOY_TEST_TMP:-$(mktemp -d)}"
mkdir -p "$BASE"
fails=0
ok()  { echo "  ok   $*"; }
bad() { echo "  FAIL $*"; fails=$((fails + 1)); }

# Песочница: mata/backend/deploy/prod-autodeploy.sh + bin/crontab (хранит расписание в файле).
make_sandbox() {
  local sb; sb="$(mktemp -d "$BASE/cron.XXXXXX")"
  mkdir -p "$sb/mata/backend/deploy" "$sb/bin"
  printf '#!/usr/bin/env bash
echo autodeploy
' > "$sb/mata/backend/deploy/prod-autodeploy.sh"
  cat > "$sb/bin/crontab" <<'STUB'
#!/usr/bin/env bash
f="$CRON_FILE"
case "${1:-}" in
  -l) [ -f "$f" ] || { echo "no crontab for root" >&2; exit 1; }; cat "$f" ;;
  -)  cat > "$f" ;;
  *)  echo "stub crontab: $*" >&2; exit 2 ;;
esac
STUB
  chmod +x "$sb/bin/crontab"
  echo "$sb"
}

run_cron() {  # run_cron <sandbox> → код выхода install-cron.sh
  local sb="$1"
  PATH="$sb/bin:$PATH" CRON_FILE="$sb/crontab.txt" MATA_DIR="$sb/mata" \
    AUTODEPLOY="$sb/prod-autodeploy.sh" bash "$SRC" > "$sb/out.log" 2>&1
}

echo "C1: сервер без расписания — строки ставятся, код 0"
SB="$(make_sandbox)"
run_cron "$SB"; rc=$?
[ "$rc" = 0 ] && ok "код 0" || { bad "код $rc"; sed 's/^/       /' "$SB/out.log"; }
for pat in prod-autodeploy tls-when-dns "tls.sh renew" backup.sh; do
  grep -q "$pat" "$SB/crontab.txt" 2>/dev/null && ok "есть $pat" || bad "нет $pat"
done
[ -x "$SB/prod-autodeploy.sh" ] && ok "авто-деплой скопирован" || bad "авто-деплой не скопирован"

echo "C2: повторный запуск — без дублей, чужие строки целы, старые битые убраны"
SB="$(make_sandbox)"
printf '%s\n' "15 1 * * * /usr/local/bin/other-job" "*/2 * * * * /opt/mata-autodeploy.sh" > "$SB/crontab.txt"
run_cron "$SB" && run_cron "$SB"; rc=$?
[ "$rc" = 0 ] && ok "код 0" || bad "код $rc"
[ "$(grep -c 'prod-autodeploy' "$SB/crontab.txt")" = 1 ] && ok "авто-деплой один раз" || bad "дубли авто-деплоя"
grep -q other-job "$SB/crontab.txt" && ok "чужая строка цела" || bad "чужая строка пропала"
grep -q '/opt/mata-autodeploy.sh' "$SB/crontab.txt" && bad "битая старая строка осталась" || ok "старая строка убрана"

[ "$fails" = 0 ]
