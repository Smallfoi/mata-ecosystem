"""Фоновые задачи программы лояльности v1. При выключенной программе — ничего."""
from celery import shared_task


@shared_task(name="loyalty.release_holds", ignore_result=True)
def release_holds():
    """Выход бонусов из удержания (покупки — после срока возврата)."""
    from . import config, v1

    if not config.enabled():
        return {"enabled": False}
    return v1.release_holds()


@shared_task(name="loyalty.daily", ignore_result=True)
def daily():
    """Сгорание, предупреждения о сгорании, понижение уровней."""
    from . import v1

    return v1.daily()
