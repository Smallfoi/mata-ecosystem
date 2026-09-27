#!/usr/bin/env bash
# МАТА — авто-деплой прод-ВМ (STANDALONE). Крон запускает раз в 2 минуты.
# ЗАЧЕМ ОТДЕЛЬНЫЙ ФАЙЛ: как и prod-deploy.sh — `yc --metadata-from-file` вырезает
# простые $-переменные из запекаемого в cloud-init скрипта. Поэтому держим здесь и
# ставим на ВМ копией: `install -m 755 /opt/mata/backend/deploy/prod-autodeploy.sh /opt/prod-autodeploy.sh`
# (это же делают prod-deploy.sh и prod-fixup.sh). Правка ЭТОГО файла в репо на ВМ сама не уезжает.
#
# Аудит E01 — релиз считается выкаченным ТОЛЬКО после проверки готовности:
#  - успешно развёрнутая ревизия хранится ОТДЕЛЬНО в /opt/mata-deployed.rev (раньше
#    мерилом был git HEAD: он сдвигался ДО сборки, и упавшая сборка/старт больше не
#    повторялись — следующий проход видел «HEAD = origin/main, нечего катить»);
#  - любой сбой шага = код 1, запись «AUTODEPLOY FAILED» в лог, счётчик попыток и вызов
#    хука уведомления /opt/mata-autodeploy-notify.sh (если владелец его положил);
#  - следующий проход крона повторяет ту же ревизию; после 3 сбоев подряд — не чаще
#    раза в 15 мин (упавшая сборка не жжёт ВМ каждые 2 минуты);
#  - готовность = healthcheck web/worker/beat «healthy» (E05) + smoke.sh + /v1/health
#    через nginx по HTTPS.
set -uo pipefail
exec 9>/var/lock/mata-autodeploy.lock
flock -n 9 || exit 0                      # прошлый прогон ещё идёт — выходим
[ -f /opt/mata-deploy.done ] || exit 0    # первичный деплой ещё не закончился

STATE=/opt/mata-deployed.rev              # последняя ревизия, прошедшая проверку готовности
FAILS=/opt/mata-autodeploy.fails          # "<ревизия> <число сбоев> <unix-время последней попытки>"
NOTIFY=/opt/mata-autodeploy-notify.sh     # необязательный хук: получает текст ошибки аргументом
SMOKE_LOG=/opt/mata-autodeploy-smoke.log  # вывод последнего smoke.sh (для разбора сбоя)
DOMAIN="api.mata-club.ru"
READY_TRIES="${AUTODEPLOY_READY_TRIES:-30}"   # × READY_SLEEP = сколько ждём готовности
READY_SLEEP="${AUTODEPLOY_READY_SLEEP:-10}"
BACKOFF_AFTER=3                               # после стольких сбоев одной ревизии…
BACKOFF_SEC="${AUTODEPLOY_BACKOFF_SEC:-900}"  # …повторяем не чаще, чем раз в столько секунд
COMPOSE="docker compose -f docker-compose.prod.yml --env-file .env"

log() { echo "=== $(date -u '+%Y-%m-%d %H:%M:%S') $*"; }

REMOTE=""
fail() {  # fail <шаг> — пометить попытку неудачной и выйти с ошибкой (ревизию НЕ записываем)
  local count=1 frev fcount fts
  if read -r frev fcount fts < "$FAILS" 2>/dev/null && [ "$frev" = "$REMOTE" ]; then
    count=$(( ${fcount:-0} + 1 ))
  fi
  echo "$REMOTE $count $(date +%s)" > "$FAILS"
  local msg="AUTODEPLOY FAILED: шаг «$1», ревизия ${REMOTE:0:12}, попытка $count (следующий проход крона повторит)"
  log "$msg"
  if [ -x "$NOTIFY" ]; then timeout 30 "$NOTIFY" "$msg" || log "WARN: хук уведомления вернул ошибку"; fi
  exit 1
}

cd /opt/mata || { log "AUTODEPLOY FAILED: нет /opt/mata"; exit 1; }
git fetch origin main --quiet || { log "AUTODEPLOY FAILED: git fetch (сеть/GitHub) — повтор на следующем проходе"; exit 1; }
REMOTE=$(git rev-parse origin/main) || { log "AUTODEPLOY FAILED: git rev-parse origin/main"; exit 1; }
DEPLOYED=$(cat "$STATE" 2>/dev/null || true)
[ "$REMOTE" = "$DEPLOYED" ] && exit 0     # эта ревизия уже выкачена и проверена

# Повторы упавшей ревизии — с паузой после BACKOFF_AFTER сбоев подряд.
if read -r frev fcount fts < "$FAILS" 2>/dev/null && [ "$frev" = "$REMOTE" ] \
   && [ "${fcount:-0}" -ge "$BACKOFF_AFTER" ] && [ $(( $(date +%s) - ${fts:-0} )) -lt "$BACKOFF_SEC" ]; then
  exit 0
fi

log "autodeploy ${DEPLOYED:-<нет записи>} -> $REMOTE"
git reset --hard "$REMOTE" || fail "git reset"

# Статика САЙТ МАТА → /opt/mata-site (bind-mount в nginx): синхронизируем содержимое ПО МЕСТУ
# (тот же inode), иначе rm -rf сорвёт монтирование и сайт отдаст 403/500.
mkdir -p /opt/mata-site || fail "mkdir /opt/mata-site"
if command -v rsync >/dev/null 2>&1; then
  rsync -a --delete --exclude='*.md' --exclude='AGENTS.md' --exclude='Референсы' \
    /opt/mata/"САЙТ МАТА"/ /opt/mata-site/ || fail "синхронизация сайта (rsync)"
else
  cp -rT /opt/mata/"САЙТ МАТА" /opt/mata-site || fail "синхронизация сайта (cp)"
  find /opt/mata-site -maxdepth 1 -name '*.md' -delete 2>/dev/null || true
  rm -f /opt/mata-site/AGENTS.md 2>/dev/null || true
  rm -rf /opt/mata-site/"Референсы" 2>/dev/null || true
fi
cd /opt/mata/backend || fail "cd backend"
# Конфиг nginx пишем ПО МЕСТУ (тот же inode): mata.conf смонтирован в контейнер ОТДЕЛЬНЫМ
# ФАЙЛОМ (bind-mount файла держит inode). `sed -i` создаёт новый файл с новым inode —
# контейнер оставался на старом и видел конфиг первого прохода после своего создания.
# Перенаправление `>` усекает и переписывает существующий файл — inode прежний.
sed 's/api\.mata-store\.ru/api.mata-club.ru/g' nginx/mata.conf.example > nginx/mata.conf \
  || fail "nginx conf"

# Пересобрать код (migrate+collectstatic — в команде web). timeout — чтобы зависание не
# держало flock вечно; упавшая/зависшая сборка = сбой (ревизия НЕ записывается).
timeout 900 $COMPOSE up -d --build web worker beat || fail "сборка/запуск web worker beat"
# Юр-документы: идемпотентно; сбой не блокирует релиз (иначе при нехватке LEGAL_* был бы
# вечный передеплой), но громко пишется в лог.
timeout 120 $COMPOSE exec -T web python manage.py publish_legal < /dev/null \
  || log "WARN: publish_legal не отработал (релиз не блокирует)"
# nginx: перечитать конфиг. web пересоздан → новый IP; без reload nginx стучит в старый → 502.
# Сначала `nginx -t`: битый конфиг НЕ перечитываем (nginx остаётся на прежнем рабочем),
# пишем WARN и релиз не блокируем. Не запущен nginx — поднимаем.
NGINX_T_LOG=/opt/mata-autodeploy-nginx-t.log
if timeout 60 $COMPOSE exec -T nginx nginx -t < /dev/null > "$NGINX_T_LOG" 2>&1; then
  timeout 60 $COMPOSE exec -T nginx nginx -s reload < /dev/null 2>/dev/null \
    || timeout 120 $COMPOSE up -d nginx || fail "nginx reload"
elif [ -z "$($COMPOSE ps -q --status running nginx 2>/dev/null)" ]; then
  timeout 120 $COMPOSE up -d nginx || fail "nginx up"
else
  log "AUTODEPLOY WARN: nginx -t не прошёл — конфиг НЕ перечитан, nginx работает на прежнем (см. $NGINX_T_LOG)"
  sed 's/^/    nginx -t| /' "$NGINX_T_LOG"
fi

# ── Готовность — условие успеха ─────────────────────────────────────────────
health_of() {  # health_of <сервис> → healthy|unhealthy|starting|none|missing
  local id; id=$($COMPOSE ps -q "$1" 2>/dev/null | head -n 1)
  [ -n "$id" ] || { echo missing; return; }
  docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$id" 2>/dev/null || echo missing
}
ready=0; why=""
for i in $(seq 1 "$READY_TRIES"); do
  why=""
  for svc in web worker beat; do
    h=$(health_of "$svc")
    [ "$h" = healthy ] || why="$why $svc=$h"
  done
  if [ -z "$why" ]; then
    if ! ./deploy/smoke.sh > "$SMOKE_LOG" 2>&1 < /dev/null; then
      why=" smoke.sh (см. $SMOKE_LOG)"
    else
      body=$(curl -sS --max-time 10 --resolve "$DOMAIN:443:127.0.0.1" "https://$DOMAIN/v1/health" 2>&1) || true
      case "$body" in *'"status":"ok"'*) ready=1; break ;; *) why=" https /v1/health: ${body:0:120}" ;; esac
    fi
  fi
  [ "$i" -lt "$READY_TRIES" ] && sleep "$READY_SLEEP"
done
if [ "$ready" != 1 ]; then
  [ -s "$SMOKE_LOG" ] && sed 's/^/    smoke| /' "$SMOKE_LOG"
  fail "проверка готовности:${why}"
fi

# Только теперь ревизия считается выкаченной.
{ echo "$REMOTE" > "$STATE.tmp" && mv -f "$STATE.tmp" "$STATE"; } || fail "запись $STATE"
rm -f "$FAILS"
log "autodeploy done: $REMOTE готов (health ok)"
