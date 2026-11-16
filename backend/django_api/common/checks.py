"""Системные проверки окружения (`manage.py check`, `test`, `runserver`).

Пока одна: установленные пакеты беднее `requirements.txt` — см. `common/imagefresh.py`.

Про формулировку. Проверка знает только своё окружение, не образ, из которого оно
выросло. Разница видна на живом примере (16.11.2026): в работающем `backend-web-1`
сторож назвал только `cryptography`, а в свежем контейнере ИЗ ТОГО ЖЕ ОБРАЗА — ещё и
`fitparse`. Потому что `fitparse` кто-то поставил в живой контейнер руками: в окружении
он есть, в образе его нет, и после `recreate` он пропадёт. Поэтому сообщение говорит
про окружение (что проверено), а про образ — подсказка (что обычно верно в dev).
"""
from django.core.checks import Warning as CheckWarning
from django.core.checks import register

from common import imagefresh

# Предупреждение, а не ошибка — сознательно. Ошибка останавливает ЛЮБУЮ команду
# manage.py, включая `migrate` при деплое: ложное срабатывание сторожа уронило бы
# выкладку на прод. Зато в CI `check --deploy --fail-level WARNING` — значит на
# PR это всё равно красное, а там зависимости ставятся из requirements, и молчание
# проверки означает, что она не врёт.
W_STALE_IMAGE = "common.W001"


@register()
def image_matches_requirements(app_configs, **kwargs):
    gone = imagefresh.stale_report()
    if not gone:
        return []
    return [
        CheckWarning(
            f"Окружение беднее requirements.txt: не установлено — {', '.join(gone)}.",
            hint="В dev это почти всегда устаревший образ: пакеты ставятся при build, "
                 "код монтируется томом. Пересоберите: docker compose up -d --build. "
                 "`pip install` внутрь живого контейнера уберёт это сообщение, но не "
                 "починит образ — после recreate вернётся.",
            id=W_STALE_IMAGE,
        )
    ]
