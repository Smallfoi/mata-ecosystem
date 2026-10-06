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


@shared_task(name="orders.expire_return_requests", ignore_result=True)
def expire_return_requests():
    """Заявки на возврат, по которым товар не сдали в срок, — в «истекла» (D-112)."""
    from .return_requests import expire_stale

    return expire_stale()
