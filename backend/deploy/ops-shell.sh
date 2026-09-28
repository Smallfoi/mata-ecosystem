#!/usr/bin/env bash
# Ограниченный канал управления продом для Claude (D-103).
#
# Зачем. Чтобы агент не ходил на прод с ключом «от всего», этот скрипт
# ПРИБИТ к ключу `claude-ops` в authorized_keys (`command="…"`): что бы ни
# прислала сторона клиента, выполнится только он, и только с одним из глаголов
# ниже. Всё остальное — отказ и запись в журнал. Безопасность держится на
# сервере, а не на честном слове клиента.
#
# Что МОЖНО (полный список, менять — только через PR и переустановку):
#   status                      состояние контейнеров
#   health                      проверка API снаружи (HTTPS)
#   disk                        место на диске
#   logs <сервис> [строк]       логи web|worker|beat|db|redis|nginx, максимум 1000
#                               (телефоны, почта, токены и коды затираются)
#   restart <сервис>            перезапуск web|worker|beat
#   refresh-env                 пересобрать .env из Lockbox и перезапустить
#   flags                       показать флаги направлений (D-89)
#   manage <команда> [--apply]  безопасные management-команды из списка ниже
#   selftest                    проверка затирания персональных данных
#
# Чего НЕЛЬЗЯ по построению: произвольные shell-команды, чтение `.env` и любых
# секретов, SQL, доступ к ключам, проброс портов, интерактивная оболочка.
set -uo pipefail

APP_DIR=/opt/mata/backend
COMPOSE=(sudo docker compose -f "$APP_DIR/docker-compose.prod.yml" --env-file "$APP_DIR/.env")
LOG=/var/log/mata-ops.log

CMD="${SSH_ORIGINAL_COMMAND:-}"

note() { printf '%s  %s\n' "$(date -Is)" "$*" | sudo tee -a "$LOG" >/dev/null 2>&1 || true; }

deny() {
  note "ОТКАЗ: ${CMD:-<пусто>}${1:+ — $1}"
  echo "Отказано: «${CMD:-<пусто>}» не входит в разрешённый список." >&2
  echo "Разрешено: status | health | disk | logs | restart | refresh-env | flags | manage | selftest" >&2
  exit 42
}

# Разбор: только слова, никаких кавычек, подстановок и цепочек.
case "$CMD" in
  *[\;\|\&\$\`\<\>]*|*'$('*) deny "запрещённые символы" ;;
esac
read -r -a ARGS <<< "$CMD"
verb="${ARGS[0]:-}"

# Затирание персональных данных и секретов (28.09.2026). Логи прода — это
# телефоны покупателей, коды входа и токены в заголовках; агенту они не нужны
# ни для одной задачи, а утекать в переписку не должны. Затираем ДО выдачи.
redact() {
  sed -E \
    -e 's/(eyJ[A-Za-z0-9_-]{6,})\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+/<токен скрыт>/g' \
    -e 's/([Bb]earer )[A-Za-z0-9._~+\/-]{8,}=*/\1<токен скрыт>/g' \
    -e 's/([A-Za-z0-9._%+-]+)@([A-Za-z0-9.-]+\.[A-Za-z]{2,})/<почта скрыта>/g' \
    -e 's/([A-Za-z_]*(SECRET|TOKEN|PASSWORD|PASSWD|APIKEY|API_KEY|KEY)[A-Za-z_]*)[=:][^ "'"'"',;]+/\1=<скрыто>/g' \
    -e 's/[0-9]{14,19}/<длинный номер скрыт>/g' \
    -e 's/(^|[^0-9])(\+?[78])[ (-]?[0-9]{3}[) -]?[0-9]{3}[ -]?[0-9]{2}[ -]?[0-9]{2}([^0-9]|$)/\1<телефон скрыт>\3/g' \
    -e 's/([Кк]од|[Cc]ode|otp|OTP)([^0-9A-Za-zА-Яа-я]{1,8})[0-9]{4,6}/\1\2<код скрыт>/g'
}

svc_logs() { case "$1" in web|worker|beat|db|redis|nginx) return 0 ;; *) return 1 ;; esac; }
svc_restart() { case "$1" in web|worker|beat) return 0 ;; *) return 1 ;; esac; }

# Management-команды: только те, что ничего не ломают необратимо и разобраны в PR.
manage_allowed() {
  case "$1" in
    check_launch_readiness|showmigrations|webify_site_videos|seed_trails|clean_seed_trails)
      return 0 ;;
    *) return 1 ;;
  esac
}

case "$verb" in
  status)
    "${COMPOSE[@]}" ps --format '{{.Service}}\t{{.State}}\t{{.Status}}'
    ;;

  health)
    curl -fsS -m 10 https://api.mata-club.ru/v1/health || {
      note "health: API не ответил"
      echo "API не ответил на /v1/health" >&2
      exit 1
    }
    echo
    ;;

  disk)
    df -h / | tail -2
    ;;

  logs)
    svc="${ARGS[1]:-web}"
    lines="${ARGS[2]:-100}"
    svc_logs "$svc" || deny "неизвестный сервис"
    [[ "$lines" =~ ^[0-9]{1,4}$ ]] && [ "$lines" -le 1000 ] || deny "строк: 1..1000"
    "${COMPOSE[@]}" logs --tail "$lines" --no-color "$svc" 2>&1 | redact
    ;;

  restart)
    svc="${ARGS[1]:-}"
    svc_restart "$svc" || deny "перезапускать можно web|worker|beat"
    "${COMPOSE[@]}" restart "$svc"
    ;;

  refresh-env)
    sudo bash "$APP_DIR/deploy/refresh-env.sh"
    ;;

  flags)
    "${COMPOSE[@]}" exec -T web python manage.py shell -c \
      'from core.models import FeatureFlag as F
for f in F.objects.all():
    print(("вкл " if f.enabled else "выкл"), f.key, "—", f.title)'
    ;;

  manage)
    sub="${ARGS[1]:-}"
    manage_allowed "$sub" || deny "management-команда не в списке"
    extra=()
    for a in "${ARGS[@]:2}"; do
      case "$a" in
        --apply|--quality=web|--quality=high) extra+=("$a") ;;
        *) deny "аргумент «$a» не разрешён" ;;
      esac
    done
    "${COMPOSE[@]}" exec -T web python manage.py "$sub" "${extra[@]}" 2>&1 | redact
    ;;

  selftest)
    # Проверяем на заведомо «грязных» строках: что не затёрлось — то утечёт.
    fixture='вход +7 914 827 8470 код 4821; user ivan.petrov@mail.ru
Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abcDEF-123_xyz
YOOKASSA_SECRET_KEY=live_AbCdEf123456 карта 4276380012345678'
    out="$(printf '%s\n' "$fixture" | redact)"
    printf '%s\n' "$out"
    echo "---"
    bad=0
    for leak in "8470" "ivan.petrov" "eyJzdWIiOiIxIn0" "live_AbCdEf123456" "4276380012345678"; do
      if printf '%s' "$out" | grep -qF "$leak"; then
        echo "УТЕЧКА: «$leak» осталось в выводе" >&2
        bad=1
      fi
    done
    [ "$bad" = 0 ] && echo "Затирание работает: телефон, почта, токен, секрет и номер карты скрыты."
    exit "$bad"
    ;;

  ""|help|--help)
    echo "Разрешено: status | health | disk | logs <сервис> [строк] | restart <сервис> |"
    echo "           refresh-env | flags | manage <команда> [--apply] | selftest"
    ;;

  *)
    deny
    ;;
esac

code=$?
note "ВЫПОЛНЕНО (код $code): $CMD"
exit $code
