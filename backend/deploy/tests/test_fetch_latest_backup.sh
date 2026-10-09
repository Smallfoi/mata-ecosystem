#!/usr/bin/env bash
# Модельный прогон deploy/fetch-latest-backup.sh с заглушкой curl (S3 ListObjectsV2 + GET).
# Проверяет: берётся самый свежий настоящий дамп, отсечка BACKUP_NOT_AFTER, постраничный
# список (continuation-token), посторонние ключи игнорируются, пустой бакет — ошибка.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="$HERE/../fetch-latest-backup.sh"
BASE="${DEPLOY_TEST_TMP:-$(mktemp -d)}"
mkdir -p "$BASE"
fails=0
ok()  { echo "  ok   $*"; }
bad() { echo "  FAIL $*"; fails=$((fails + 1)); }

# Песочница: backend/{deploy/fetch-latest-backup.sh,.env} + bin/curl (заглушка бакета).
# STUB_PAGE1 / STUB_PAGE2 — ключи страниц списка (через пробел); вторая страница — если не пуста.
make_sandbox() {
  local sb; sb="$(mktemp -d "$BASE/fetch.XXXXXX")"
  mkdir -p "$sb/backend/deploy" "$sb/bin"
  cp "$SRC" "$sb/backend/deploy/fetch-latest-backup.sh"
  printf 'BACKUP_S3_BUCKET=mata-club-backups\nMEDIA_S3_ACCESS_KEY=k\nMEDIA_S3_SECRET_KEY=s\n' > "$sb/backend/.env"
  cat > "$sb/bin/curl" <<'STUB'
#!/usr/bin/env bash
url="${*: -1}"; out=""
prev=""; for a in "$@"; do [ "$prev" = "-o" ] && out="$a"; prev="$a"; done
echo "$url" >> "${STUB_LOG:-/dev/null}"
case "$url" in
  *list-type=2*)
    keys="$STUB_PAGE1"; next=""
    case "$url" in *continuation-token=*) keys="$STUB_PAGE2" ;; *) [ -n "${STUB_PAGE2:-}" ] && next="tok/1+2" ;; esac
    printf '<?xml version="1.0"?><ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
    for k in $keys; do printf '<Contents><Key>%s</Key></Contents>' "$k"; done
    [ -n "$next" ] && printf '<IsTruncated>true</IsTruncated><NextContinuationToken>%s</NextContinuationToken>' "$next"
    printf '</ListBucketResult>' ;;
  *) [ -n "$out" ] || exit 22; printf 'dump of %s' "${url##*/}" > "$out" ;;
esac
STUB
  chmod +x "$sb/bin/curl"
  echo "$sb"
}

run_fetch() {  # run_fetch <sandbox> → stdout скрипта в $sb/path, код выхода
  local sb="$1"
  ( cd "$sb/backend" && PATH="$sb/bin:$PATH" STUB_LOG="$sb/urls.log" \
      bash deploy/fetch-latest-backup.sh > "$sb/path" 2> "$sb/err.log" )
}

echo "F1: самый свежий настоящий дамп, посторонние ключи мимо"
SB="$(make_sandbox)"
STUB_PAGE1="db/mata_20261005_040001.sql.gz.enc db/mata_20261007_040002.sql.gz.enc db/mata_20261006_040001.sql.gz.enc db/mata_20261009_010101.sql.gz.part db/notes.txt" \
STUB_PAGE2="" run_fetch "$SB"; rc=$?
if [ "$rc" = 0 ] && [ "$(cat "$SB/path")" = "backups/mata_20261007_040002.sql.gz.enc" ]; then ok "взят mata_20261007_040002"
else bad "код $rc, путь '$(cat "$SB/path")'"; sed 's/^/       /' "$SB/err.log"; fi
[ -s "$SB/backend/backups/mata_20261007_040002.sql.gz.enc" ] && ok "файл скачан" || bad "файла нет"
ls "$SB/backend/backups/"*.part >/dev/null 2>&1 && bad "остался .part" || ok "без .part"

echo "F2: BACKUP_NOT_AFTER отсекает более свежий (бэкап пустой базы нового сервера)"
SB="$(make_sandbox)"
STUB_PAGE1="db/mata_20261007_040002.sql.gz.enc db/mata_20261009_120000.sql.gz.enc" STUB_PAGE2="" \
BACKUP_NOT_AFTER=20261009000000 run_fetch "$SB"; rc=$?
[ "$rc" = 0 ] && [ "$(cat "$SB/path")" = "backups/mata_20261007_040002.sql.gz.enc" ] \
  && ok "взят дамп до отсечки" || bad "код $rc, путь '$(cat "$SB/path")'"

echo "F3: список на двух страницах — свежий на второй"
SB="$(make_sandbox)"
STUB_PAGE1="db/mata_20261001_040001.sql.gz.enc" STUB_PAGE2="db/mata_20261008_040001.sql.gz.enc" run_fetch "$SB"; rc=$?
[ "$rc" = 0 ] && [ "$(cat "$SB/path")" = "backups/mata_20261008_040001.sql.gz.enc" ] \
  && ok "дошли до второй страницы" || bad "код $rc, путь '$(cat "$SB/path")'"
grep -q 'continuation-token=tok%2F1%2B2' "$SB/urls.log" && ok "токен закодирован" || bad "токен не закодирован"

echo "F4: пустой бакет — ошибка, а не пустой путь"
SB="$(make_sandbox)"
STUB_PAGE1="" STUB_PAGE2="" run_fetch "$SB"; rc=$?
[ "$rc" != 0 ] && [ ! -s "$SB/path" ] && ok "код $rc, путь не напечатан" || bad "код $rc, путь '$(cat "$SB/path")'"

echo "F5: без BACKUP_S3_BUCKET — ошибка"
SB="$(make_sandbox)"
printf 'MEDIA_S3_ACCESS_KEY=k\nMEDIA_S3_SECRET_KEY=s\n' > "$SB/backend/.env"
STUB_PAGE1="db/mata_20261007_040002.sql.gz.enc" STUB_PAGE2="" run_fetch "$SB"; rc=$?
[ "$rc" != 0 ] && ok "код $rc" || bad "прошло без бакета"

[ "$fails" = 0 ]
