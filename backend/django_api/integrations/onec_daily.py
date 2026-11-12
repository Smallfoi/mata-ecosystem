"""Поток 6 — итоги дня из 1С (D-124, паспорт §15).

1С раз в сутки присылает день целиком: продажи всех каналов, возвраты,
поступления, остаток на закрытие и контрольные суммы. МАТА проверяет, что день
дошёл целым, и хранит его как прислан — считать ничего не нужно, аналитику
считает Pareta (`docs/ANALYTICS_FOR_PARETA.md`).

Повторная отправка дня заменяет его целиком: в 1С документы перепроводят задним
числом, и «вот как было» чинит обмен само, без слияния строк.
"""
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import OneCDay, OneCDayVersion

YAKUTSK = ZoneInfo("Asia/Yakutsk")
FIRST_DAY = date(2023, 11, 4)        # с этого дня 1С отдаёт историю (§15.8)
ALERT_HOUR = 6                       # к 06:00 по Якутску вчерашний день должен быть
MAX_ERRORS = 50                      # больше замечаний не перечисляем — смысла нет
EPS = 0.005                          # суммы в рублях с копейками

LISTS = ("sales", "returns", "receipts", "stockEnd")
CHANNELS = ("store", "mata")

# Обязательные поля строк (§15.3–15.6). Числа проверяем отдельно.
REQUIRED = {
    "sales": ("docId", "time", "channel", "sellerId", "sellerName", "id", "article", "name"),
    "returns": ("docId", "time", "channel", "id", "article", "name"),
    "receipts": ("docId", "time", "supplier", "id", "article", "name"),
    "stockEnd": ("id",),
}
NUMBERS = {
    "sales": ("qty", "price", "discount", "sum", "costSum"),
    "returns": ("qty", "sum", "costSum"),
    "receipts": ("qty", "costSum"),
    "stockEnd": ("qty",),
}
# Для заказов МАТА — номер заказа (и возврата), иначе продажа не свяжется с §7.
FOR_MATA = {"sales": ("orderId",), "returns": ("orderId", "returnId")}

TOTALS = ("salesLines", "salesQty", "salesSum", "returnsLines", "returnsSum",
          "receiptsLines", "receiptsQty", "stockEndLines")


class DayError(Exception):
    """День не принят. `status` — код ответа, `errors` / `mismatch` — подробности."""

    def __init__(self, detail, status=400, errors=None, mismatch=None):
        super().__init__(detail)
        self.detail = detail
        self.status = status
        self.errors = errors or []
        self.mismatch = mismatch or {}


def today_yakutsk(now=None) -> date:
    return (now or timezone.now()).astimezone(YAKUTSK).date()


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _filled(v) -> bool:
    return v is not None and str(v).strip() != ""


def _parse_date(raw):
    try:
        return date.fromisoformat(str(raw or "").strip())
    except ValueError:
        return None


def _row_errors(name: str, i: int, row) -> list:
    where = f"{name}[{i}]"
    if not isinstance(row, dict):
        return [f"{where}: строка должна быть объектом"]
    out = [f"{where}: нет поля {f}" for f in REQUIRED[name] if not _filled(row.get(f))]
    out += [f"{where}: {f} — нужно число" for f in NUMBERS[name] if not _is_number(row.get(f))]
    channel = row.get("channel")
    if name in ("sales", "returns") and _filled(channel):
        if channel not in CHANNELS:
            out.append(f"{where}: channel — store или mata, пришло «{str(channel)[:20]}»")
        elif channel == "mata":
            out += [f"{where}: для заказа МАТА нужно поле {f}"
                    for f in FOR_MATA[name] if not _filled(row.get(f))]
    return out


def counted(payload) -> dict:
    """Контрольные суммы, посчитанные по присланным строкам."""
    def total(rows, field):
        return round(sum(r.get(field) or 0 for r in rows), 2)

    sales, returns = payload["sales"], payload["returns"]
    receipts, stock = payload["receipts"], payload["stockEnd"]
    return {
        "salesLines": len(sales), "salesQty": total(sales, "qty"), "salesSum": total(sales, "sum"),
        "returnsLines": len(returns), "returnsSum": total(returns, "sum"),
        "receiptsLines": len(receipts), "receiptsQty": total(receipts, "qty"),
        "stockEndLines": len(stock),
    }


def validate(payload, now=None):
    """Проверить день. Возвращает (дата, totals, counts) или бросает DayError."""
    from .onec import MAX_ITEMS

    if not isinstance(payload, dict):
        raise DayError("Ожидается объект дня: {\"date\": …, \"sales\": […], …, \"totals\": {…}}")
    day = _parse_date(payload.get("date"))
    if day is None:
        raise DayError("Поле date — день в виде ГГГГ-ММ-ДД")
    if day < FIRST_DAY:
        raise DayError(f"Итоги принимаем с {FIRST_DAY:%d.%m.%Y}")
    if day > today_yakutsk(now):
        raise DayError("Этот день по Якутску ещё не наступил")

    missing = [name for name in LISTS if not isinstance(payload.get(name), list)]
    if missing:
        raise DayError("Нужны списки " + ", ".join(missing) +
                       " — пустой список, если за день ничего не было")
    rows = sum(len(payload[name]) for name in LISTS)
    if rows > MAX_ITEMS:
        raise DayError(f"В дне {rows} строк — больше {MAX_ITEMS}. Напишите нам: "
                       "делить день на части нельзя, вторая часть заменит первую.", 413)

    errors = []
    for name in LISTS:
        for i, row in enumerate(payload[name]):
            errors += _row_errors(name, i, row)
            if len(errors) >= MAX_ERRORS:
                break
    if errors:
        raise DayError(f"День {day:%d.%m.%Y} не принят: ошибки в строках",
                       errors=errors[:MAX_ERRORS])

    sent = payload.get("totals")
    if not isinstance(sent, dict):
        raise DayError("Нужны контрольные суммы totals")
    have = counted(payload)
    mismatch = {}
    for key in TOTALS:
        got = sent.get(key)
        if not _is_number(got) or abs(got - have[key]) > EPS:
            mismatch[key] = {"sent": got, "counted": have[key]}
    if mismatch:
        raise DayError(f"День {day:%d.%m.%Y} не принят: контрольные суммы не сошлись. "
                       "Прежняя версия дня осталась в силе — пришлите день заново.",
                       422, mismatch=mismatch)
    return day, {k: sent[k] for k in TOTALS}, {name: len(payload[name]) for name in LISTS}


def save(payload, now=None) -> dict:
    """Принять день: проверить и заменить целиком. Ответ — как в паспорте §15.9."""
    day, totals, counts = validate(payload, now)
    generated = parse_datetime(str(payload.get("generatedAt") or "")) if payload.get(
        "generatedAt") else None
    received = now or timezone.now()
    with transaction.atomic():
        old = OneCDay.objects.select_for_update().filter(date=day).first()
        if old:
            OneCDayVersion.objects.create(
                date=old.date, version=old.version, payload=old.payload,
                totals=old.totals, received_at=old.received_at, replaced_at=received)
            version = old.version + 1
        else:
            version = 1
        OneCDay.objects.update_or_create(date=day, defaults={
            "payload": payload, "totals": totals, "counts": counts, "version": version,
            "generated_at": generated, "received_at": received,
        })
    if cache.add("onec_daily_versions_pruned", 1, 24 * 3600):
        OneCDayVersion.prune()
    return {"status": "ok", "date": day.isoformat(), "replaced": old is not None,
            "version": version, "received": counts, "errors": []}


def expected() -> bool:
    """Ждём ли итоги каждый день: включается после первой живой отправки (§3 ТЗ)."""
    return str(getattr(settings, "ONEC_DAILY_EXPECTED", "") or "").strip() in ("1", "true", "yes")


def watch_state(now=None) -> dict:
    """Пришёл ли вчерашний день. late=True — тревога: после 06:00 по Якутску дня нет."""
    now = now or timezone.now()
    local = now.astimezone(YAKUTSK)
    yesterday = local.date() - timedelta(days=1)
    have = OneCDay.objects.filter(date=yesterday).exists()
    due = datetime.combine(local.date(), time(ALERT_HOUR), tzinfo=YAKUTSK)
    late = expected() and not have and now >= due
    return {"expected": expected(), "yesterday": yesterday.isoformat(),
            "received": have, "late": late}
