#!/usr/bin/env bash
# Модельный прогон deploy/refresh-env.sh в песочнице (VPS-ветка: секреты из файла).
# Заглушки docker/curl/pgbr.sh; настоящий только сам скрипт.
# Главное: ключи, которые выпускает сервер (GlitchTip connect → /root/mata-server-keys.env),
# переживают обновление секретов из Lockbox. 12.11.2026 их стёрло — ошибки не доходили до GlitchTip.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="$HERE/../refresh-env.sh"
BASE="${DEPLOY_TEST_TMP:-$(mktemp -d)}"
mkdir -p "$BASE"
fails=0
ok()  { echo "  ok   $*"; }
bad() { echo "  FAIL $*"; fails=$((fails + 1)); }

make_sandbox() {
  local sb; sb="$(mktemp -d "$BASE/refreshenv.XXXXXX")"
  mkdir -p "$sb/bin" "$sb/backend/deploy"
  echo "PUBLIC_IP=203.0.113.5" > "$sb/backend/.env"
  cat > "$sb/secrets.env" <<'ENV'
POSTGRES_PASSWORD=pg
DJANGO_SECRET_KEY=dj
JWT_SECRET=jwt
PARETA_READ_TOKEN=new-from-lockbox
ENV
  printf '#!/usr/bin/env bash\necho "PGBR $*" >> "$STUB_LOG"\n' > "$sb/backend/deploy/pgbr.sh"
  printf '#!/usr/bin/env bash\necho "DOCKER $*" >> "$STUB_LOG"\n' > "$sb/bin/docker"
  printf '#!/usr/bin/env bash\necho "CURL $*" >> "$STUB_LOG"\necho "{}"\n' > "$sb/bin/curl"
  chmod +x "$sb/backend/deploy/pgbr.sh" "$sb/bin/docker" "$sb/bin/curl"
  echo "$sb"
}

run() {  # $1 = песочница
  local sb="$1"
  PATH="$sb/bin:$PATH" STUB_LOG="$sb/log" MATA_BACKEND_DIR="$sb/backend" \
    MATA_SECRETS_FILE="$sb/secrets.env" MATA_SERVER_KEYS_FILE="$sb/server-keys.env" \
    bash "$SRC" > "$sb/out" 2>&1
}

echo "== ключи сервера переживают обновление секретов"
sb="$(make_sandbox)"
cat > "$sb/server-keys.env" <<'ENV'
SENTRY_DSN='http://key@glitchtip-web:8000/1'
GLITCHTIP_API_TOKEN=tok
ENV
# Устаревшая копия ключа в файле секретов (как было до исправления) — побеждает файл сервера.
echo "SENTRY_DSN=http://old@glitchtip-web:8000/1" >> "$sb/secrets.env"
if run "$sb"; then ok "скрипт отработал"; else bad "скрипт упал: $(tail -3 "$sb/out")"; fi
env_file="$sb/backend/.env"
[ "$(grep -c '^SENTRY_DSN=' "$env_file")" = 1 ] && ok "SENTRY_DSN ровно один" || bad "SENTRY_DSN: $(grep -c '^SENTRY_DSN=' "$env_file") шт."
grep -q "^SENTRY_DSN='http://key@glitchtip-web:8000/1'$" "$env_file" && ok "SENTRY_DSN из файла сервера" || bad "SENTRY_DSN не тот: $(grep '^SENTRY_DSN=' "$env_file")"
grep -q '^GLITCHTIP_API_TOKEN=tok$' "$env_file" && ok "токен GlitchTip на месте" || bad "нет GLITCHTIP_API_TOKEN"
grep -q '^PARETA_READ_TOKEN=new-from-lockbox$' "$env_file" && ok "новый ключ из Lockbox тоже на месте" || bad "потерян ключ из Lockbox"
grep -q '^JWT_SECRET=jwt$' "$env_file" && ok "секреты магазина на месте" || bad "нет JWT_SECRET"
grep -q '^PUBLIC_IP=203.0.113.5$' "$env_file" && ok "PUBLIC_IP сохранён" || bad "PUBLIC_IP потерян"
grep -q "Ключи сервера:" "$sb/out" && ok "в выводе сказано, откуда ключи" || bad "нет строки «Ключи сервера»"

echo "== без файла ключей сервера — как раньше"
sb="$(make_sandbox)"
if run "$sb"; then ok "скрипт отработал"; else bad "скрипт упал: $(tail -3 "$sb/out")"; fi
grep -q '^JWT_SECRET=jwt$' "$sb/backend/.env" && ok "секреты на месте" || bad "нет JWT_SECRET"
grep -q '^SENTRY_DSN=' "$sb/backend/.env" && bad "SENTRY_DSN взялся из ниоткуда" || ok "SENTRY_DSN нет"

echo "== секреты без обязательных ключей — .env не трогаем"
sb="$(make_sandbox)"
echo "SENTRY_DSN=x" > "$sb/server-keys.env"
grep -v '^JWT_SECRET=' "$sb/secrets.env" > "$sb/s2" && mv "$sb/s2" "$sb/secrets.env"
if run "$sb"; then bad "скрипт не остановился без JWT_SECRET"; else ok "остановился"; fi
[ "$(cat "$sb/backend/.env")" = "PUBLIC_IP=203.0.113.5" ] && ok "старый .env не тронут" || bad ".env испорчен"

[ "$fails" = 0 ] && echo "ALL OK" || echo "$fails FAILED"
exit "$fails"
