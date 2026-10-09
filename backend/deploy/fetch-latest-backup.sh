#!/usr/bin/env bash
# Скачать из бакета бэкапов САМЫЙ СВЕЖИЙ дамп БД (то, что выгружает deploy/backup.sh).
# Запуск НА СЕРВЕРЕ из backend/:  ./deploy/fetch-latest-backup.sh
# Печатает в stdout ОДНУ строку — путь к скачанному файлу (backups/mata_….sql.gz[.enc]),
# всё остальное — в stderr. Нужен, когда прежний сервер вместе с диском БД недоступен
# (8.10.2026: пожар в ЦОД зоны ru-central1-b) и базу поднимаем на новом сервере.
#
# Какой дамп «последний»: имена mata_YYYYMMDD_HHMMSS.* сортируются по времени. Берём
# только дампы НЕ НОВЕЕ BACKUP_NOT_AFTER (если задан) — чтобы сервер, поднятый с пустой
# базой и успевший выгрузить её бэкап, не подсунул его вместо настоящего.
set -euo pipefail
umask 077

cd "$(dirname "$0")/.."  # → backend/
[ -f .env ] || { echo "Нет .env" >&2; exit 1; }
set -a; . ./.env; set +a

S3_BUCKET="${BACKUP_S3_BUCKET:-}"
[ -n "$S3_BUCKET" ] || { echo "ОШИБКА: BACKUP_S3_BUCKET не задан — откуда брать бэкап?" >&2; exit 1; }
S3_KEY="${BACKUP_S3_ACCESS_KEY:-${MEDIA_S3_ACCESS_KEY:-}}"
S3_SECRET="${BACKUP_S3_SECRET_KEY:-${MEDIA_S3_SECRET_KEY:-}}"
S3_ENDPOINT="${BACKUP_S3_ENDPOINT:-${MEDIA_S3_ENDPOINT:-https://storage.yandexcloud.net}}"
S3_REGION="${BACKUP_S3_REGION:-${MEDIA_S3_REGION:-ru-central1}}"
[ -n "$S3_KEY" ] && [ -n "$S3_SECRET" ] || { echo "ОШИБКА: ключи доступа к бакету пусты" >&2; exit 1; }

s3() {  # s3 <url> [аргументы curl...] — запрос с подписью SigV4
  local url="$1"; shift
  curl -sS --fail --aws-sigv4 "aws:amz:${S3_REGION}:s3" --user "${S3_KEY}:${S3_SECRET}" "$@" "$url"
}

# Список дампов (ListObjectsV2, с продолжением — на случай >1000 объектов).
KEYS=""
TOKEN=""
while :; do
  URL="${S3_ENDPOINT%/}/${S3_BUCKET}?list-type=2&prefix=db/mata_"
  [ -n "$TOKEN" ] && URL="${URL}&continuation-token=$(python3 -c 'import sys,urllib.parse;print(urllib.parse.quote(sys.argv[1],safe=""))' "$TOKEN")"
  PAGE=$(s3 "$URL") || { echo "ОШИБКА: не удалось получить список бакета ${S3_BUCKET}" >&2; exit 1; }
  PARSED=$(printf '%s' "$PAGE" | python3 -c '
import sys, xml.etree.ElementTree as ET
root = ET.fromstring(sys.stdin.read())
ns = {"s": root.tag.split("}")[0].strip("{")} if root.tag.startswith("{") else {}
p = (lambda t: "s:" + t) if ns else (lambda t: t)
for c in root.findall(p("Contents"), ns):
    print("KEY " + c.find(p("Key"), ns).text)
tok = root.find(p("NextContinuationToken"), ns)
if tok is not None and tok.text:
    print("NEXT " + tok.text)
')
  KEYS="${KEYS}$(printf '%s\n' "$PARSED" | sed -n 's/^KEY //p')"$'\n'
  TOKEN=$(printf '%s\n' "$PARSED" | sed -n 's/^NEXT //p')
  [ -n "$TOKEN" ] || break
done

# Только настоящие дампы backup.sh; отсечка по времени; самый свежий — последний по имени.
LATEST=$(printf '%s' "$KEYS" | grep -E '^db/mata_[0-9]{8}_[0-9]{6}\.sql\.gz(\.enc)?$' \
  | awk -v lim="${BACKUP_NOT_AFTER:-}" '{ split($0, a, "_"); ts = substr(a[2], 1, 8) a[3]; ts = substr(ts, 1, 14)
      if (lim == "" || ts <= lim) print }' \
  | sort | tail -n 1)
[ -n "$LATEST" ] || { echo "ОШИБКА: в бакете ${S3_BUCKET} нет подходящих дампов (db/mata_*)" >&2; exit 1; }

mkdir -p backups
OUT="backups/$(basename "$LATEST")"
echo "Скачиваю ${LATEST} → ${OUT}" >&2
s3 "${S3_ENDPOINT%/}/${S3_BUCKET}/${LATEST}" -o "${OUT}.part" \
  || { rm -f "${OUT}.part"; echo "ОШИБКА: скачать ${LATEST} не удалось" >&2; exit 1; }
[ -s "${OUT}.part" ] || { rm -f "${OUT}.part"; echo "ОШИБКА: скачан пустой файл" >&2; exit 1; }
mv -f "${OUT}.part" "$OUT"
echo "$OUT"
