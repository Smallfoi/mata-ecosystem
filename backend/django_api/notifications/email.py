"""Транзакционные письма покупателю (D-111, по образцу Notification Module Medusa).

Уведомление о заказе уходит по всем каналам сразу: лента в приложении, пуш и —
если у покупателя есть настоящий адрес — письмо. Провайдер задаётся окружением,
как у SMS и пушей:

- `EMAIL_PROVIDER` пуст — письма выключены (no-op), ничего не ломается;
- `smtp` — через SMTP (`EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`,
  `EMAIL_HOST_PASSWORD`, `EMAIL_USE_SSL`/`EMAIL_USE_TLS`, `DEFAULT_FROM_EMAIL`):
  Unisender Go, Yandex 360, Mail.ru — любой SMTP;
- `console` — печать в лог (разработка).

Это служебные письма о заказе, не реклама: отдельного согласия не требуют, но в
них нет ничего, кроме заказа.
"""
import logging
import os
import re

log = logging.getLogger(__name__)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# Служебные адреса без почтового ящика: аккаунты по телефону (`runner_…@kvartal.local`).
_FAKE_DOMAINS = (".local", ".test", ".invalid", ".example")

SIGNATURE = "\n\n—\nМАТА Store\nЭто письмо о вашем заказе, отвечать на него не нужно."


def email_enabled() -> bool:
    return (os.environ.get("EMAIL_PROVIDER") or "").strip() in ("smtp", "console")


def real_address(value) -> str:
    """Адрес, на который можно писать, или пустая строка."""
    addr = str(value or "").strip()
    if not _EMAIL_RE.match(addr):
        return ""
    if addr.lower().endswith(_FAKE_DOMAINS):
        return ""
    return addr


def recipient_for(user_id, order=None) -> str:
    """Куда писать: email из оформления заказа, иначе — из аккаунта."""
    if order is not None:
        checkout = (order.payload or {}).get("checkoutData") or {}
        addr = real_address(checkout.get("email") if isinstance(checkout, dict) else "")
        if addr:
            return addr
    if not user_id:
        return ""
    from accounts.models import Account

    acc = Account.objects.filter(id=user_id).only("email").first()
    return real_address(acc.email) if acc else ""


def send_email(to, subject, text) -> bool:
    """Отправить письмо. False — выключено, нет адреса или провайдер отказал."""
    to = real_address(to)
    if not to or not email_enabled():
        return False
    from django.core.mail import send_mail

    try:
        send_mail(subject, text + SIGNATURE, None, [to], fail_silently=False)
    except Exception:  # провайдер недоступен — письмо не главное, заказ не роняем
        log.exception("Письмо «%s» не отправлено", subject)
        return False
    return True
