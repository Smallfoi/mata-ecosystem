"""Настройки программы лояльности v1 (ТЗ владельца 30.09.2026, §1).

Все ЧИСЛА программы — здесь, в таблице настроек (меняются в админке без релиза,
каждое изменение пишется в историю: кто, когда, старое → новое). ПРАВИЛА — в коде
(`loyalty.v1`).

Доступ из кода — одна функция `get(key)`: берёт значение из таблицы, а если его
там нет (строка не заведена или значение «по умолчанию») — значение v1 из ТЗ.
Таблица читается целиком и кэшируется на минуту (общий кэш Django); сохранение
настройки кэш сбрасывает, так что web и фоновые задачи видят новое значение сразу
или не позже чем через минуту.

Жёсткий потолок списания 0,30 от eligible_total зашит в код (`HARD_REDEEM_CEILING`):
настройка REDEEM_CEILING выше него игнорируется (ТЗ §6 «запрещено кодом»).
"""
from dataclasses import dataclass

from django.core.cache import cache

# Код, а не настройка: «верхняя граница 0,30 зашита в код» (ТЗ §1, §6).
HARD_REDEEM_CEILING = 0.30
# «Не меняется» (ТЗ §1) — поэтому константы кода, а не настройки.
STATUS_WINDOW_DAYS = 365
STATUS_TERM_DAYS = 365
# Версия ТЗ — первая часть rule_version в журнале.
RULES_VERSION = "tz-v1"

LEVELS = ("basic", "silver", "gold", "platinum")
LEVEL_TITLES = ("Базовый", "Серебро", "Золото", "Платина")

_CACHE_KEY = "loyalty:settings:v1"
_CACHE_TTL = 60


@dataclass(frozen=True)
class Spec:
    default: object
    title: str
    kind: str          # bool | int | float | levels_int | levels_float | thresholds | codes
    help: str = ""
    who: str = "владелец"


SPECS = {
    "LOYALTY_V1_ENABLED": Spec(
        False, "Программа лояльности v1 включена", "bool",
        "Выключатель новой механики. Выключено — работают прежние правила баллов. "
        "Включать ПОСЛЕ переноса балансов (manage.py loyalty_migrate_v1 --apply)."),
    "RATE_PURCHASE": Spec(
        [0.05, 0.06, 0.07, 0.09], "Начисление за покупку, доля по уровням", "levels_float",
        "Базовый / Серебро / Золото / Платина. От денежной части заказа (без бонусов и доставки)."),
    "BONUS_RUN": Spec(10, "Бонус за пробежку", "int", "Этап 2. Ещё и стоп-кран."),
    "BONUS_CAPTURE": Spec(30, "Бонус за захват квартала", "int", "Этап 2."),
    "BONUS_STAGE": Spec(50, "Бонус за победу в этапе", "int", "Этап 2."),
    "CAP_RUNS_MONTH": Spec(12, "Пробежек с бонусом в месяц", "int", "Этап 2."),
    "CAP_CAPTURES_MONTH": Spec(3, "Захватов с бонусом в месяц", "int", "Этап 2."),
    "CAP_STAGES_MONTH": Spec(1, "Этапов с бонусом в месяц", "int", "Этап 2."),
    "CAP_ACTIVITY_MONTH": Spec(
        [260, 325, 390, 520], "Общий месячный лимит за активность по уровням", "levels_int",
        "Этап 2."),
    "BONUS_REFERRAL": Spec(100, "Бонус за приглашённого", "int", "Этап 2."),
    "CAP_REFERRALS_MONTH": Spec(3, "Приглашённых с бонусом в месяц", "int", "Этап 2."),
    "BONUS_SIGNUP": Spec(75, "Бонус за регистрацию", "int", "Этап 2. В статусные не входит."),
    "REDEEM_CEILING": Spec(
        [0.15, 0.20, 0.25, 0.30], "Потолок списания, доля по уровням", "levels_float",
        f"Доля от суммы допущенных позиций. Выше {HARD_REDEEM_CEILING:.2f} не бывает — "
        "граница зашита в код, большее значение игнорируется."),
    "REDEEM_MIN": Spec(300, "Минимальное списание, бонусов", "int"),
    "HOLD_DAYS": Spec(14, "Удержание покупочных бонусов, дней", "int",
                      "Лот покупки доступен не раньше оплаты + HOLD_DAYS."),
    "DELIVERY_RETURN_DAYS": Spec(
        7, "Срок возврата после получения, дней", "int",
        "Решение координатора: лот покупки держится до max(оплата + HOLD_DAYS, "
        "получение + этот срок). Не получен — держится.", "координатор"),
    "EXPIRY_MONTHS": Spec([6, 12, 12, 18], "Срок жизни бонусов, месяцев по уровням",
                          "levels_int"),
    "EXPIRY_WARN_DAYS": Spec(30, "Предупреждать о сгорании за, дней", "int"),
    "LEVEL_THRESHOLD": Spec(
        [500, 2000, 5000], "Пороги уровней Серебро / Золото / Платина, статусных", "thresholds"),
    "PLATINUM_MIN_SPEND": Spec(60000, "Платина: покупки за 365 дней от, ₽", "int"),
    "RESERVE_PER_BONUS": Spec(0.31, "Резерв на 1 бонус, ₽", "float", "",
                              "аналитик Pareta, раз в полгода"),
    "STOPLOSS_COST_SHARE": Spec(0.07, "Стоп-кран: доля затрат", "float", "Этап 4."),
    "STOPLOSS_MONTHS": Spec(2, "Стоп-кран: месяцев подряд", "int", "Этап 4."),
    "RUN_MIN_KM": Spec(3.0, "Пробежка: минимум, км", "float", "Этап 2."),
    "RUN_PACE_MIN": Spec(180, "Пробежка: самый быстрый темп, сек/км", "int",
                         "Этап 2. 180 = 3:00 мин/км."),
    "RUN_PACE_MAX": Spec(720, "Пробежка: самый медленный темп, сек/км", "int",
                         "Этап 2. 720 = 12:00 мин/км."),
    "EXCLUDED_CATEGORIES_1C": Spec(
        [], "Группы 1С без списания бонусов (коды)", "codes",
        "Коды категорий (Category.id из 1С). Подгруппы исключаются вместе с группой. "
        "Заполнить по названиям из ТЗ: manage.py loyalty_find_excluded_categories --apply"),
}


class ConfigError(ValueError):
    pass


def _num(v, integer):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ConfigError("нужно число")
    if integer and float(v) != int(v):
        raise ConfigError("нужно целое число")
    if v < 0:
        raise ConfigError("не может быть отрицательным")
    return int(v) if integer else float(v)


def validate(key, value):
    """Проверить и привести значение настройки. ConfigError — с понятным текстом."""
    spec = SPECS.get(key)
    if spec is None:
        raise ConfigError(f"Неизвестная настройка {key}")
    kind = spec.kind
    if kind == "bool":
        if not isinstance(value, bool):
            raise ConfigError("нужно true или false")
        return value
    if kind in ("int", "float"):
        return _num(value, kind == "int")
    if kind in ("levels_int", "levels_float", "thresholds"):
        n = 3 if kind == "thresholds" else 4
        if not isinstance(value, list) or len(value) != n:
            raise ConfigError(f"нужен список из {n} чисел")
        out = [_num(v, kind != "levels_float") for v in value]
        if kind == "thresholds" and out != sorted(out):
            raise ConfigError("пороги должны расти: Серебро ≤ Золото ≤ Платина")
        if kind == "levels_float" and any(v > 1 for v in out):
            raise ConfigError("доля — от 0 до 1")
        return out
    if kind == "codes":
        if not isinstance(value, list) or not all(isinstance(v, (str, int)) for v in value):
            raise ConfigError("нужен список кодов")
        return sorted({str(v).strip() for v in value if str(v).strip()})
    raise ConfigError(f"неизвестный тип {kind}")


def _load() -> dict:
    from .models import LoyaltySetting

    data = cache.get(_CACHE_KEY)
    if data is None:
        data = {}
        for key, value in LoyaltySetting.objects.values_list("key", "value"):
            if value is None or key not in SPECS:
                continue
            try:
                data[key] = validate(key, value)
            except ConfigError:
                continue  # битое значение не валит расчёт — действует значение ТЗ
        cache.set(_CACHE_KEY, data, _CACHE_TTL)
    return data


def invalidate() -> None:
    cache.delete(_CACHE_KEY)


def get(key):
    """Действующее значение настройки (из таблицы или значение v1 из ТЗ)."""
    spec = SPECS[key]
    value = _load().get(key, spec.default)
    return list(value) if isinstance(value, list) else value


def snapshot() -> dict:
    """Слепок всех действующих значений — для rule_version в журнале."""
    return {key: get(key) for key in SPECS}


def enabled() -> bool:
    """Включена ли программа v1 (выключатель LOYALTY_V1_ENABLED)."""
    return bool(get("LOYALTY_V1_ENABLED"))


def by_level(key, level: int):
    values = get(key)
    return values[max(0, min(int(level), len(values) - 1))]


def redeem_ceiling(level: int) -> float:
    """Потолок списания уровня — никогда не выше HARD_REDEEM_CEILING."""
    return min(float(by_level("REDEEM_CEILING", level)), HARD_REDEEM_CEILING)


def set_value(key, value, by="", comment=""):
    """Записать настройку с историей (старое → новое). Для кода и команд; в админке
    то же делает форма."""
    from django.db import transaction

    from .models import LoyaltySetting, LoyaltySettingChange

    value = validate(key, value)
    with transaction.atomic():
        row, _ = LoyaltySetting.objects.select_for_update().get_or_create(key=key)
        old = row.value
        if old == value:
            return row
        row.value = value
        row.updated_by = by[:150]
        row.save()
        LoyaltySettingChange.objects.create(
            key=key, old_value=old, new_value=value, changed_by=by[:150],
            comment=comment[:300],
        )
    invalidate()
    return row


def ensure_rows() -> None:
    """Завести строки для всех настроек (значение пусто = «как в ТЗ»), чтобы в
    админке был виден полный список."""
    from .models import LoyaltySetting

    have = set(LoyaltySetting.objects.values_list("key", flat=True))
    missing = [LoyaltySetting(key=k, value=None) for k in SPECS if k not in have]
    if missing:
        LoyaltySetting.objects.bulk_create(missing, ignore_conflicts=True)
