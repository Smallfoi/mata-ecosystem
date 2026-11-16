"""Системные проверки окружения (`manage.py check`, `test`, `runserver`).

Пока одна: образ старее `requirements.txt` — см. `common/imagefresh.py`.
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
            f"Образ старее requirements.txt: не установлено — {', '.join(gone)}.",
            hint="Пакеты ставятся при build, код монтируется томом. "
                 "Пересоберите: docker compose up -d --build",
            id=W_STALE_IMAGE,
        )
    ]
