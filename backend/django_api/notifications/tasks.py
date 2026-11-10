"""Фоновые задачи уведомлений (D-07). Пуш уходит через провайдера, что может быть
медленно/ненадёжно — выносим из HTTP-цикла в Celery. Без брокера (EAGER) задача
выполняется синхронно, как раньше."""
from celery import shared_task


@shared_task(name="notifications.send_push", ignore_result=True)
def send_push_task(user_id, title, body=""):
    """Отправить пуш пользователю (no-op без PUSH_PROVIDER). Возвращает число доставок."""
    from .push import send_push

    return send_push(user_id, title, body)


@shared_task(name="notifications.send_email", ignore_result=True)
def send_email_task(to, subject, text):
    """Отправить письмо (no-op без EMAIL_PROVIDER, D-111)."""
    from .email import send_email

    return send_email(to, subject, text)
