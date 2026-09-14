"""Защита баланса SIGMA от накрутки кодов входа (D-76).

Каждый запрос кода стоит денег: звонок SIGMA тарифицируется за попытку (1,49 ₽), даже
если до человека не дошёл. Раньше запрос кода ограничивал только общий анти-брутфорс
`auth` (20 в минуту с адреса) — бот с нескольких адресов мог за час сжечь баланс, а при
нуле SIGMA отключает вход сразу всем.

Лимиты (решение владельца 14.09.2026):
- **90 секунд** между кодами на один номер — столько живёт код;
- **3 кода на номер в сутки** (сутки якутские);
- **с одного адреса** — 30 в час и 100 в сутки: за мобильным адресом оператора (CGNAT)
  сидят сотни абонентов, строже нельзя;
- **сигнал владельцу**, когда за час запросили необычно много кодов.

Счётчики — в кэше: на проде это общий Redis, лимит один на все воркеры (D-07). Лимиты
действуют только с настоящим провайдером: в разработке код 1234 ничего не стоит.

Место под код занимается ДО обращения к провайдеру — иначе два одновременных запроса
прошли бы оба — и возвращается, если провайдер отправку не принял: сбой у SIGMA не
должен отнимать у человека попытку.
"""
import logging
import math
import os
import time
from datetime import timedelta

from django.core.cache import cache
from django.utils import timezone

# Адрес — из того же источника, что у анти-брутфорса админки (X-Real-IP от нашего nginx).
from common.adminsec import _client_ip
from common.security import normalize_phone

from .sms import sms_enabled

log = logging.getLogger(__name__)

COOLDOWN_SECONDS = 90
PHONE_PER_DAY = 3
IP_PER_HOUR = 30
IP_PER_DAY = 100
ALERT_PER_HOUR = 30
CALL_PRICE_RUB = 1.49  # попытка flashcall, письмо SIGMA от 14.09.2026 (SimPush — сверху)

COOLDOWN_TEXT = "Новый код можно запросить через {seconds} сек."
PHONE_DAY_TEXT = (
    "Лимит кодов на этот номер на сегодня исчерпан. "
    "Попробуйте завтра или войдите по паролю."
)
IP_TEXT = "Слишком много запросов кода из вашей сети. Попробуйте позже."


class Refused(Exception):
    """Код не отправляем. `detail` — текст для человека, `retry_after` — секунд до повтора."""

    def __init__(self, detail, retry_after):
        super().__init__(detail)
        self.detail = detail
        self.retry_after = max(1, int(retry_after))


def _now():
    return time.time()


def _local():
    return timezone.localtime()


def _to_next_hour(moment):
    nxt = moment.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    return math.ceil((nxt - moment).total_seconds())


def _to_midnight(moment):
    nxt = moment.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    return math.ceil((nxt - moment).total_seconds())


def _incr(key, ttl):
    """+1 к счётчику (в Redis атомарно). Ключа нет — заводим с нулём и сроком жизни."""
    cache.add(key, 0, ttl)
    try:
        return cache.incr(key)
    except ValueError:  # ключ истёк между add и incr
        cache.set(key, 1, ttl)
        return 1


def _decr(key):
    try:
        cache.decr(key)
    except ValueError:
        pass


class Slot:
    """Занятое место под один код: `release()` — провайдер не принял, `sent()` — принял."""

    def __init__(self, cooldown="", counters=()):
        self._cooldown = cooldown
        self._counters = counters

    def release(self):
        if not self._cooldown:
            return
        cache.delete(self._cooldown)
        for key in self._counters:
            _decr(key)

    def sent(self):
        if not self._cooldown:
            return
        # Считаем только принятые провайдером: платим именно за них. Сигнал — ровно
        # в момент, когда счётчик часа дошёл до порога, то есть не чаще раза в час.
        count = _incr(f"otp:sent:{_local():%Y%m%d%H}", 2 * 3600)
        if count == ALERT_PER_HOUR:
            _alert_owner(count)


def reserve(phone, request) -> Slot:
    """Занять место под код для `phone` или отказать (`Refused`)."""
    if not sms_enabled():
        return Slot()
    now, moment = _now(), _local()
    day = f"{moment:%Y%m%d}"
    phone_day = f"otp:phone:{phone}:{day}"
    # Сначала суточный лимит: исчерпан — «ждите 90 секунд» было бы враньём.
    if (cache.get(phone_day) or 0) >= PHONE_PER_DAY:
        raise Refused(PHONE_DAY_TEXT, _to_midnight(moment))

    cooldown = f"otp:cooldown:{phone}"
    until = now + COOLDOWN_SECONDS
    if not cache.add(cooldown, until, COOLDOWN_SECONDS):
        busy_until = cache.get(cooldown) or 0
        if busy_until > now:
            wait = math.ceil(busy_until - now)
            raise Refused(COOLDOWN_TEXT.format(seconds=wait), wait)
        cache.set(cooldown, until, COOLDOWN_SECONDS)

    ip = _client_ip(request)
    limits = (
        (f"otp:ip:h:{ip}:{moment:%Y%m%d%H}", 2 * 3600, IP_PER_HOUR, IP_TEXT, _to_next_hour(moment)),
        (f"otp:ip:d:{ip}:{day}", 26 * 3600, IP_PER_DAY, IP_TEXT, _to_midnight(moment)),
        (phone_day, 26 * 3600, PHONE_PER_DAY, PHONE_DAY_TEXT, _to_midnight(moment)),
    )
    taken = []
    for key, ttl, limit, text, wait in limits:
        taken.append(key)
        if _incr(key, ttl) > limit:
            Slot(cooldown, taken).release()
            raise Refused(text, wait)
    return Slot(cooldown, taken)


def _alert_owner(count):
    """За час запросили необычно много кодов — пишем в ленту приложения (и пуш, если включён).

    Кому — телефоны из `ALERT_PHONES` через запятую: учётка админки с аккаунтом в
    приложении не связана. Сбой оповещения не должен ломать вход.
    """
    rub = round(count * CALL_PRICE_RUB)
    log.warning("OTP: с начала часа запрошено %s кодов (около %s ₽)", count, rub)
    phones = [
        normalize_phone(p) for p in (os.environ.get("ALERT_PHONES") or "").split(",") if p.strip()
    ]
    if not phones:
        return
    try:
        from notifications.models import create_notification

        from .models import Account

        for uid in Account.objects.filter(phone__in=phones).values_list("id", flat=True):
            create_notification(
                uid,
                "Необычно много кодов для входа",
                f"С начала часа запрошено {count} кодов — около {rub} ₽. "
                "Если столько людей не входило, похоже на накрутку.",
            )
    except Exception:
        log.exception("OTP: не удалось отправить сигнал о расходе")
