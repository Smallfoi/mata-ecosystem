#!/usr/bin/env bash
# Бэкап прод-БД STAW (PostgreSQL/PostGIS) через pg_dump.
# Запускать НА СЕРВЕРЕ из каталога backend/:  ./deploy/backup.sh
# Баллы = деньги → бэкап обязателен; повесить на cron (см. docs/DEPLOY.md).
set -euo pipefail
# Дампы содержат ВСЕ персональные данные и реестр баллов — файлы только для владельца.
umask 077

cd "$(dirname "$0")/.."  # → backend/
[ -f .env ] || { echo "Нет .env (см. .env.prod.example)"; exit 1; }
set -a; . ./.env; set +a   # загрузить POSTGRES_USER/DB и пр.

COMPOSE="docker compose -f docker-compose.prod.yml --env-file .env"
DIR="${BACKUP_DIR:-backups}"
KEEP_DAYS="${BACKUP_KEEP_DAYS:-14}"
mkdir -p "$DIR"

TS=$(date +%Y%m%d_%H%M%S)
OUT="$DIR/mata_${TS}.sql.gz"

echo "Бэкап БД '${POSTGRES_DB}' → $OUT"
# Пишем во временный файл и переименовываем только после проверок: обрывок дампа
# (упал pg_dump, кончилось место) не должен лежать рядом под именем настоящего бэкапа.
PART="${OUT}.part"
trap 'rm -f "$PART"' EXIT
$COMPOSE exec -T db pg_dump -U "${POSTGRES_USER}" "${POSTGRES_DB}" | gzip > "$PART"

# Проверки дампа (аудит E03). Каждая читает поток ДО КОНЦА: раньше здесь стояло
# `gzip -dc | head -c 200000`, и при set -o pipefail head закрывал канал раньше gzip →
# gzip получал SIGPIPE (код 141) → бэкап любой БД больше ~200 КБ падал ДО шифрования и
# выгрузки в бакет. Поэтому никаких head/grep -q в конвейере — только полное чтение.
gzip -t "$PART" || { echo "ОШИБКА: архив дампа повреждён"; exit 1; }
SIZE=$(gzip -dc "$PART" | wc -c)
[ "$SIZE" -gt 1000 ] || { echo "ОШИБКА: дамп подозрительно мал ($SIZE байт) — проверь БД"; exit 1; }
# pg_dump пишет эту строку последней — без неё дамп оборван (упал на середине).
LAST=$(gzip -dc "$PART" | tail -c 4096)
case "$LAST" in
  *"PostgreSQL database dump complete"*) ;;
  *) echo "ОШИБКА: дамп оборван (нет финальной метки pg_dump) — бэкап не засчитан"; exit 1 ;;
esac
mv -f "$PART" "$OUT"
trap - EXIT

echo "Готово: $(du -h "$OUT" | cut -f1) (несжатый объём: $SIZE байт)"

# ── Шифрование перед выгрузкой ────────────────────────────────────────────────
# В дампе телефоны, email, адреса и весь реестр баллов. Ключ доступа к бакету лежит
# в .env на том же сервере: компрометация сервера = чтение всех бэкапов. Поэтому шифруем
# ЛОКАЛЬНО, до отправки. Пароль хранить ОТДЕЛЬНО от сервера (менеджер паролей) — иначе
# смысл теряется. Без BACKUP_ENCRYPT_PASSPHRASE поведение прежнее.
if [ -n "${BACKUP_ENCRYPT_PASSPHRASE:-}" ]; then
  ENC="${OUT}.enc"
  BACKUP_ENCRYPT_PASSPHRASE="$BACKUP_ENCRYPT_PASSPHRASE"     openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt       -in "$OUT" -out "$ENC" -pass env:BACKUP_ENCRYPT_PASSPHRASE
  rm -f "$OUT"
  OUT="$ENC"
  echo "Зашифровано: $(basename "$OUT")"
else
  echo "ВНИМАНИЕ: BACKUP_ENCRYPT_PASSPHRASE не задан — дамп с ПДн уедет в бакет открытым."
fi

# ── Выгрузка в объектное хранилище ────────────────────────────────────────────
# Дамп рядом с БД на том же диске — это НЕ бэкап: диск умрёт вместе с обоими.
# Заливаем в Yandex Object Storage подписью SigV4 средствами curl (без доп. пакетов).
S3_BUCKET="${BACKUP_S3_BUCKET:-}"
if [ -z "$S3_BUCKET" ]; then
  echo "ВНИМАНИЕ: BACKUP_S3_BUCKET не задан — дамп остался ТОЛЬКО на диске сервера."
else
  # Ключи по умолчанию — те же, что у медиа (обычно один сервисный аккаунт).
  S3_KEY="${BACKUP_S3_ACCESS_KEY:-${MEDIA_S3_ACCESS_KEY:-}}"
  S3_SECRET="${BACKUP_S3_SECRET_KEY:-${MEDIA_S3_SECRET_KEY:-}}"
  S3_ENDPOINT="${BACKUP_S3_ENDPOINT:-${MEDIA_S3_ENDPOINT:-https://storage.yandexcloud.net}}"
  S3_REGION="${BACKUP_S3_REGION:-${MEDIA_S3_REGION:-ru-central1}}"
  [ -n "$S3_KEY" ] && [ -n "$S3_SECRET" ] || {
    echo "ОШИБКА: BACKUP_S3_BUCKET задан, но ключи доступа пусты"; exit 1; }

  DEST="${S3_ENDPOINT%/}/${S3_BUCKET}/db/$(basename "$OUT")"
  echo "Выгрузка → $DEST"
  CODE=$(curl -sS -o /dev/null -w '%{http_code}' \
           --aws-sigv4 "aws:amz:${S3_REGION}:s3" \
           --user "${S3_KEY}:${S3_SECRET}" \
           --upload-file "$OUT" "$DEST") || CODE="000"
  [ "$CODE" = "200" ] || { echo "ОШИБКА выгрузки в S3: HTTP $CODE"; exit 1; }
  echo "Выгружено в бакет ${S3_BUCKET}."
fi

# Ротация ЛОКАЛЬНЫХ дампов старше KEEP_DAYS дней (в бакете — политика жизненного цикла).
find "$DIR" -name 'mata_*.sql.gz' -mtime +"$KEEP_DAYS" -delete 2>/dev/null || true
find "$DIR" -name 'mata_*.sql.gz.enc' -mtime +"$KEEP_DAYS" -delete 2>/dev/null || true
