#!/usr/bin/env bash
# Модельные прогоны скриптов деплоя (backend/deploy/*.sh) с заглушками docker/curl/git.
# Ничего настоящего не трогают: каждый тест работает во временном каталоге-песочнице.
# Запуск:  bash backend/deploy/tests/run_all.sh     (CI job «Deploy · scripts»)
# Временный каталог можно задать через DEPLOY_TEST_TMP (на Windows — только диск D).
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
fail=0
for t in "$HERE"/test_*.sh; do
  [ -e "$t" ] || continue
  echo "################ $(basename "$t")"
  if bash "$t"; then echo "PASS $(basename "$t")"; else echo "FAIL $(basename "$t")"; fail=1; fi
done
[ "$fail" = 0 ] && echo "ALL DEPLOY-SCRIPT TESTS PASSED" || echo "SOME DEPLOY-SCRIPT TESTS FAILED"
exit "$fail"
