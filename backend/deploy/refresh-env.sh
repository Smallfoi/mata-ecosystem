#!/usr/bin/env bash
# МАТА backend — пересборка .env из Yandex Lockbox БЕЗ полного передеплоя (STANDALONE).
#
# ЗАЧЕМ: когда в Lockbox меняются секреты (например OPENAI_API_KEY фотопайплайна или
# реквизиты LEGAL_* при смене ИП), нужно обновить /opt/mata/backend/.env и перезапустить
# web/worker/beat — БЕЗ rm -rf /opt/mata, БЕЗ переоформления TLS, БЕЗ даунтайма БД/redis.
#
# БЕЗОПАСНОСТЬ (не может уронить прод):
#   - собираем во ВРЕМЕННЫЙ .env.new;
#   - валидируем обязательные ключи (POSTGRES_PASSWORD/DJANGO_SECRET_KEY/JWT_SECRET);
#   - только при успехе АТОМАРНО заменяем .env (mv). Если Lockbox не отдал секреты —
#     старый .env остаётся нетронутым, выходим с кодом 1.
#
# Запуск на ВМ:  sudo bash /opt/mata/backend/deploy/refresh-env.sh
#
# Состав .env = статический (не секретный) блок + payload двух секретов Lockbox
# (mata-prod-secrets + mata-eco-image) — тот же источник, что и в prod-deploy.sh.
# Без set -x — чтобы секреты не попали в лог/serial.
set -euo pipefail
cd /opt/mata/backend

# --- статический (НЕ секретный) блок .env — 1:1 как в prod-deploy.sh ---
STATIC_ENV() {
cat <<'ENVEOF'
DJANGO_DEBUG=0
DJANGO_ALLOWED_HOSTS=api.mata-club.ru
DJANGO_CORS_ORIGINS=https://mata-club.ru,https://www.mata-club.ru,https://mata-media.storage.yandexcloud.net
POSTGRES_DB=mata
POSTGRES_USER=mata
POSTGRES_HOST=db
POSTGRES_PORT=5432
REDIS_URL=redis://redis:6379/0
DJANGO_MEDIA_ROOT=/srv/media
DJANGO_STATIC_ROOT=/app/staticfiles
SITE_PREVIEW_URL=https://mata-club.ru
APP_PREVIEW_URL=https://mata-media.storage.yandexcloud.net/mata-app-preview/index.html
LEGAL_DOCS_DIR=/legal_docs
TLS_DOMAIN=api.mata-club.ru
TLS_EMAIL=admin@mata-club.ru
TLS_EXTRA_SAN=mata-club.ru,www.mata-club.ru,158-160-12-117.nip.io
ENVEOF
}

IAM_TOKEN() {
  curl -s -H "Metadata-Flavor: Google" \
    "http://169.254.169.254/computeMetadata/v1/instance/service-accounts/default/token" 2>/dev/null \
    | python3 -c "import sys,json;print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null || true
}

# $1 = secret id → печатает "key=<quoted value>" построчно
PULL_SECRET() {
  local sid="$1" iam
  iam="$(IAM_TOKEN)"
  [ -n "$iam" ] || return 0
  curl -s -H "Authorization: Bearer $iam" \
    "https://payload.lockbox.api.cloud.yandex.net/lockbox/v1/secrets/$sid/payload" 2>/dev/null \
    | python3 -c "import sys,json,shlex;[print(e['key']+'='+shlex.quote(e.get('textValue',''))) for e in json.load(sys.stdin).get('entries',[])]" 2>/dev/null || true
}

LB_SECRET_ID="e6q1ias432ne7vtogghv"        # mata-prod-secrets  (DB/JWT/LEGAL_*/OTP/оплата/1С...)
ECO_IMAGE_SECRET_ID="e6qu8vruift7elbpm6o8" # mata-eco-image     (OPENAI_API_KEY [+ OPENAI_BASE_URL])

umask 077
TMP=".env.new"
STATIC_ENV > "$TMP"

# основной секрет — с ретраем на «прогрев» сервисного аккаунта
for t in $(seq 1 12); do
  PULL_SECRET "$LB_SECRET_ID" >> "$TMP"
  grep -q "^POSTGRES_PASSWORD=" "$TMP" && { echo "Lockbox mata-prod-secrets: получен (попытка $t)"; break; }
  echo "Lockbox mata-prod-secrets: ещё не готов ($t/12) — жду 5с..."; sleep 5
done

# доп. секрет фотопайплайна (опционально — без него пайплайн просто в no-op)
PULL_SECRET "$ECO_IMAGE_SECRET_ID" >> "$TMP"

# ВАЛИДАЦИЯ: без критичных ключей .env НЕ заменяем
for k in POSTGRES_PASSWORD DJANGO_SECRET_KEY JWT_SECRET; do
  grep -q "^$k=" "$TMP" || { echo "FATAL: $k отсутствует в новом .env — НЕ заменяю, abort"; rm -f "$TMP"; exit 1; }
done
grep -q "^OPENAI_API_KEY=" "$TMP" && echo "OK: OPENAI_API_KEY получен" || echo "WARN: OPENAI_API_KEY нет (фотопайплайн в no-op)"
grep -q "^LEGAL_OGRNIP=" "$TMP"  && echo "OK: LEGAL_* получены"        || echo "WARN: LEGAL_* нет — publish_legal подставит плейсхолдеры"

mv "$TMP" .env
echo "=== .env пересобран из Lockbox ==="

# пересоздаём контейнеры с новым окружением (env-only, без rm; --force-recreate гарантирует
# подхват новых переменных в web/worker/beat). db и redis не трогаем.
docker compose -f docker-compose.prod.yml --env-file .env up -d --force-recreate web worker beat
sleep 8

# публикуем юр.документы с актуальными реквизитами (читает LEGAL_* из окружения web)
docker compose -f docker-compose.prod.yml --env-file .env exec -T web python manage.py publish_legal || echo "WARN: publish_legal не отработал"

echo "=== health ==="
curl -s https://api.mata-club.ru/v1/health || true
echo
echo "=== ГОТОВО: .env обновлён, web перезапущен, юр.документы опубликованы ==="
