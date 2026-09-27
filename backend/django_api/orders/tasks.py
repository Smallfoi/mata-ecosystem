"""Фоновые задачи заказов (D-72)."""
from celery import shared_task


@shared_task(name="orders.expire_unpaid_orders", ignore_result=True)
def expire_unpaid_orders():
    """Отменить заказы, которые не оплатили вовремя, и вернуть списанные баллы."""
    from .lifecycle import expire_unpaid

    return expire_unpaid()


@shared_task(name="orders.reconcile_returns", ignore_result=True)
def reconcile_returns():
    """Досверить с ЮKassa возвраты «в обработке» (аудит B04)."""
    from .returns import reconcile_returns as run

    return run()
