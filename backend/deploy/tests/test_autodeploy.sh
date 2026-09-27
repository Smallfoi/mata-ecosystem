#!/usr/bin/env bash
# Модельный прогон deploy/prod-autodeploy.sh (аудит E01) в песочнице.
# Настоящий git (локальный «origin» + клон вместо /opt/mata), заглушки docker/curl/flock.
# Пути /opt/… и /var/lock/… в копии скрипта переписываются на песочницу.
# Проверяем: сбой сборки/старта/готовности НЕ помечает релиз выкаченным, следующий проход
# повторяет ту же ревизию; успех записывается только после проверки готовности.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="$HERE/../prod-autodeploy.sh"
BASE="${DEPLOY_TEST_TMP:-$(mktemp -d)}"
mkdir -p "$BASE"
fails=0
ok()  { echo "  ok   $*"; }
bad() { echo "  FAIL $*"; fails=$((fails + 1)); }
G() { git -c core.autocrlf=false -c user.name=test -c user.email=test@example.invalid -c init.defaultBranch=main "$@"; }

make_sandbox() {
  local sb; sb="$(mktemp -d "$BASE/autodeploy.XXXXXX")"
  mkdir -p "$sb/bin" "$sb/opt" "$sb/lock" "$sb/work"
  G init -q --bare "$sb/origin.git"
  G -C "$sb/work" init -q
  mkdir -p "$sb/work/САЙТ МАТА" "$sb/work/backend/nginx" "$sb/work/backend/deploy"
  echo '<h1>site v1</h1>' > "$sb/work/САЙТ МАТА/index.html"
  echo 'server_name api.mata-store.ru;' > "$sb/work/backend/nginx/mata.conf.example"
  echo 'services: {}' > "$sb/work/backend/docker-compose.prod.yml"
  cat > "$sb/work/backend/deploy/smoke.sh" <<'STUB'
#!/usr/bin/env bash
echo "SMOKE" >> "$STUB_LOG"; exit "${STUB_SMOKE_RC:-0}"
STUB
  chmod +x "$sb/work/backend/deploy/smoke.sh"
  G -C "$sb/work" add -A && G -C "$sb/work" commit -q -m v1
  G -C "$sb/work" remote add origin "$sb/origin.git"
  G -C "$sb/work" push -q origin HEAD:main
  G clone -q --branch main "$sb/origin.git" "$sb/opt/mata"
  : > "$sb/opt/mata/backend/.env"
  : > "$sb/opt/mata-deploy.done"
  sed -e "s#/opt/#$sb/opt/#g" -e "s#/var/lock/#$sb/lock/#g" "$SRC" > "$sb/autodeploy.sh"
  # Заглушки.
  cat > "$sb/bin/docker" <<'STUB'
#!/usr/bin/env bash
a="$*"
case "$a" in
  *" up -d --build "*) echo "BUILD_UP" >> "$STUB_LOG"; exit "${STUB_BUILD_RC:-0}" ;;
  *" up -d nginx"*)    echo "NGINX_UP" >> "$STUB_LOG"; exit "${STUB_NGINX_RC:-0}" ;;
  *"exec -T nginx"*)   echo "NGINX_RELOAD" >> "$STUB_LOG"; exit "${STUB_NGINX_RC:-0}" ;;
  *"exec -T web python manage.py publish_legal"*) echo "PUBLISH_LEGAL" >> "$STUB_LOG"; exit 0 ;;
  *" ps -q "*)         echo "cid-${a##* }" ;;
  inspect*)            echo "${STUB_HEALTH:-healthy}" ;;
  *) echo "stub docker: unexpected: $a" >&2; exit 2 ;;
esac
STUB
  cat > "$sb/bin/curl" <<'STUB'
#!/usr/bin/env bash
echo "CURL $*" >> "$STUB_LOG"
[ "${STUB_CURL_RC:-0}" = 0 ] || { echo "curl: (7) Failed to connect" >&2; exit 7; }
echo '{"status":"ok","service":"mata-ecosystem-django","db":true}'
STUB
  command -v flock >/dev/null 2>&1 || printf '#!/usr/bin/env bash\nexit 0\n' > "$sb/bin/flock"
  printf '#!/usr/bin/env bash\necho "NOTIFY $*" >> "$STUB_LOG"\n' > "$sb/opt/mata-autodeploy-notify.sh"
  chmod +x "$sb/bin/"* "$sb/opt/mata-autodeploy-notify.sh"
  : > "$sb/calls.log"
  echo "$sb"
}

push_commit() {  # push_commit <sandbox> <метка> → печатает новую ревизию
  local sb="$1"
  echo "<h1>site $2</h1>" > "$sb/work/САЙТ МАТА/index.html"
  G -C "$sb/work" commit -q -am "$2" && G -C "$sb/work" push -q origin HEAD:main
  G -C "$sb/work" rev-parse HEAD
}

run_ad() {  # run_ad <sandbox> → код выхода; вывод в $sb/out.log (дописывается)
  local sb="$1"
  STUB_LOG="$sb/calls.log" PATH="$sb/bin:$PATH" AUTODEPLOY_READY_TRIES=2 AUTODEPLOY_READY_SLEEP=0 \
    bash "$sb/autodeploy.sh" >> "$sb/out.log" 2>&1
}
deployed() { cat "$1/opt/mata-deployed.rev" 2>/dev/null; }
nbuild()   { grep -c '^BUILD_UP' "$1/calls.log"; }
show()     { sed 's/^/       | /' "$1/out.log"; }

echo "E01-1: новая ревизия, всё зелёное → выкачена и записана после проверки"
SB="$(make_sandbox)"; R=$(push_commit "$SB" v2)
run_ad "$SB"; rc=$?
[ "$rc" = 0 ] && ok "код 0" || { bad "код $rc"; show "$SB"; }
[ "$(deployed "$SB")" = "$R" ] && ok "ревизия записана в mata-deployed.rev" || bad "ревизия не записана"
grep -q 'site v2' "$SB/opt/mata-site/index.html" 2>/dev/null && ok "сайт синхронизирован" || bad "сайт не синхронизирован"
grep -q '^CURL .*/v1/health' "$SB/calls.log" && grep -q '^SMOKE' "$SB/calls.log" \
  && ok "готовность проверена (smoke + https /v1/health)" || bad "готовность не проверялась"
run_ad "$SB"; rc=$?
[ "$rc" = 0 ] && [ "$(nbuild "$SB")" = 1 ] && ok "повторный проход: нечего катить" || bad "повторный проход пересобирал (сборок: $(nbuild "$SB"))"

echo "E01-2: сборка упала → релиз НЕ помечен, следующий проход повторяет"
SB="$(make_sandbox)"; R=$(push_commit "$SB" v2)
STUB_BUILD_RC=1 run_ad "$SB"; rc=$?
[ "$rc" != 0 ] && ok "код $rc (ошибка не подавлена)" || bad "сбой сборки дал код 0"
[ "$(deployed "$SB")" != "$R" ] && ok "ревизия не записана" || bad "упавшая ревизия помечена выкаченной"
grep -q '^NOTIFY AUTODEPLOY FAILED' "$SB/calls.log" && ok "хук уведомления вызван" || bad "уведомления нет"
grep -q 'AUTODEPLOY FAILED' "$SB/out.log" && ok "в логе AUTODEPLOY FAILED" || bad "в логе нет AUTODEPLOY FAILED"
run_ad "$SB"; rc=$?
[ "$(nbuild "$SB")" = 2 ] && ok "следующий проход пересобрал ту же ревизию" || bad "повтора не было (сборок: $(nbuild "$SB"))"
[ "$rc" = 0 ] && [ "$(deployed "$SB")" = "$R" ] && ok "после успешного повтора ревизия записана" || bad "после повтора ревизия не записана"
[ ! -e "$SB/opt/mata-autodeploy.fails" ] && ok "счётчик сбоев сброшен" || bad "счётчик сбоев остался"

echo "E01-3: контейнеры не стали healthy (упал migrate/старт) → не помечен"
SB="$(make_sandbox)"; R=$(push_commit "$SB" v2)
STUB_HEALTH=unhealthy run_ad "$SB"; rc=$?
[ "$rc" != 0 ] && [ "$(deployed "$SB")" != "$R" ] && ok "код $rc, ревизия не записана" || bad "unhealthy-релиз помечен"
grep -q 'web=unhealthy' "$SB/out.log" && ok "в логе причина: web=unhealthy" || bad "в логе нет причины"

echo "E01-4: /v1/health через nginx не отвечает → не помечен"
SB="$(make_sandbox)"; R=$(push_commit "$SB" v2)
STUB_CURL_RC=7 run_ad "$SB"; rc=$?
[ "$rc" != 0 ] && [ "$(deployed "$SB")" != "$R" ] && ok "код $rc, ревизия не записана" || bad "релиз без /v1/health помечен"

echo "E01-5: smoke.sh провален → не помечен"
SB="$(make_sandbox)"; R=$(push_commit "$SB" v2)
STUB_SMOKE_RC=1 run_ad "$SB"; rc=$?
[ "$rc" != 0 ] && [ "$(deployed "$SB")" != "$R" ] && ok "код $rc, ревизия не записана" || bad "релиз с проваленным smoke помечен"

echo "E01-6: nginx не перечитался и не поднялся → не помечен"
SB="$(make_sandbox)"; R=$(push_commit "$SB" v2)
STUB_NGINX_RC=1 run_ad "$SB"; rc=$?
[ "$rc" != 0 ] && [ "$(deployed "$SB")" != "$R" ] && ok "код $rc, ревизия не записана" || bad "сбой nginx проигнорирован"

echo "E01-7: 3 сбоя подряд → пауза между повторами, потом снова попытка"
SB="$(make_sandbox)"; R=$(push_commit "$SB" v2)
for _ in 1 2 3; do STUB_BUILD_RC=1 run_ad "$SB"; done
[ "$(nbuild "$SB")" = 3 ] && ok "3 попытки" || bad "попыток: $(nbuild "$SB")"
STUB_BUILD_RC=1 run_ad "$SB"
[ "$(nbuild "$SB")" = 3 ] && ok "4-й проход сразу — пауза (без сборки)" || bad "нет паузы после 3 сбоев"
AUTODEPLOY_BACKOFF_SEC=0 run_ad "$SB"; rc=$?
[ "$(nbuild "$SB")" = 4 ] && [ "$rc" = 0 ] && [ "$(deployed "$SB")" = "$R" ] \
  && ok "после паузы — повтор и успех" || bad "после паузы повтора не было"

echo "E01-8: git fetch не прошёл → ненулевой код, ничего не трогаем"
SB="$(make_sandbox)"; push_commit "$SB" v2 >/dev/null
G -C "$SB/opt/mata" remote set-url origin "$SB/nowhere.git"
run_ad "$SB"; rc=$?
[ "$rc" != 0 ] && [ "$(nbuild "$SB")" = 0 ] && ok "код $rc, сборки не было" || bad "сбой fetch подавлен (код $rc)"

if command -v shellcheck >/dev/null 2>&1; then
  (cd "$HERE/.." && shellcheck -S warning prod-autodeploy.sh) && ok "shellcheck prod-autodeploy.sh" || bad "shellcheck prod-autodeploy.sh"
fi

[ -z "${DEPLOY_TEST_TMP:-}" ] && rm -rf "$BASE"
[ "$fails" = 0 ] || { echo "test_autodeploy: $fails провал(ов)"; exit 1; }
echo "test_autodeploy: OK"
