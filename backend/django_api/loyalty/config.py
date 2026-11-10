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
    kind: str          # bool | int | float | levels_int | levels_float | thresholds | codes | names
    help: str = ""
    who: str = "владелец"
    # Как показывать в админке «Программа лояльности»: страницы строятся из этого
    # реестра, поэтому новый ключ появляется на своей странице сам.
    page: str = ""     # overview | levels | accrual | products; пусто — по типу (page_of)
    group: str = ""    # блок на странице «Начисления»; пусто — «Другие настройки»
    unit: str = ""     # "%" — хранится долей, вводится процентом; "pace" — сек/км, ввод м:сс
    max_value: object = None   # верхняя граница (в единицах хранения), проверяется при сохранении
    level_only: object = None  # скаляр на странице «Уровни»: в строке какого уровня


# Блоки страницы «Начисления» — в этом порядке; ключ без блока — в «Другие настройки».
GROUPS = ("Бонусы за действия", "Месячные лимиты", "Покупки и удержание", "Списание",
          "Сгорание", "Проверка пробежки", "Стоп-кран", "Учёт")
OTHER_GROUP = "Другие настройки"

SPECS = {
    "LOYALTY_V1_ENABLED": Spec(
        False, "Программа лояльности включена", "bool",
        "Выключено — работают прежние правила баллов. Включать ПОСЛЕ переноса балансов "
        "и после того, как заданы товары-исключения.", page="overview"),
    "RATE_PURCHASE": Spec(
        [0.05, 0.06, 0.07, 0.09], "Бонусы за покупку, % по уровню", "levels_float",
        "Процент от денежной части заказа (без оплаченного бонусами и без доставки).",
        unit="%", max_value=1),
    "BONUS_RUN": Spec(10, "Бонус за пробежку", "int",
                      "Сколько бонусов за одну засчитанную пробежку. Стоп-кран снижает его "
                      "сам, если затраты на программу слишком велики.",
                      group="Бонусы за действия"),
    "BONUS_CAPTURE": Spec(30, "Бонус за захват квартала", "int",
                          "За территорию, перешедшую по засчитанной пробежке.",
                          group="Бонусы за действия"),
    "BONUS_STAGE": Spec(50, "Бонус за победу в этапе", "int",
                        "1-е место в месячном итоге своего зачёта.", group="Бонусы за действия"),
    "BONUS_REFERRAL": Spec(100, "Бонус за приглашённого друга", "int",
                           "Пригласившему — когда первый заказ друга вышел из удержания без "
                           "возврата.", group="Бонусы за действия"),
    "BONUS_SIGNUP": Spec(75, "Бонус за регистрацию", "int",
                         "Один раз на телефон. В статусные (уровень) не входит.",
                         group="Бонусы за действия"),
    "CAP_RUNS_MONTH": Spec(12, "Пробежек с бонусом в месяц", "int",
                           "Сверх лимита пробежка засчитывается в игре, но без бонусов.",
                           group="Месячные лимиты"),
    "CAP_CAPTURES_MONTH": Spec(3, "Захватов с бонусом в месяц", "int", group="Месячные лимиты"),
    "CAP_STAGES_MONTH": Spec(1, "Этапов с бонусом в месяц", "int", group="Месячные лимиты"),
    "CAP_REFERRALS_MONTH": Spec(3, "Приглашённых с бонусом в месяц", "int",
                                group="Месячные лимиты"),
    "CAP_ACTIVITY_MONTH": Spec(
        [260, 325, 390, 520], "Лимит бонусов за активность в месяц", "levels_int",
        "Общий потолок за пробежки, захваты и этапы вместе, по уровню."),
    "REDEEM_CEILING": Spec(
        [0.15, 0.20, 0.25, 0.30], "Оплата бонусами, % по уровню", "levels_float",
        f"Какую долю суммы допущенных товаров можно оплатить бонусами. Больше "
        f"{round(HARD_REDEEM_CEILING * 100)}% нельзя — это потолок, зашитый в код.",
        unit="%", max_value=HARD_REDEEM_CEILING),
    "REDEEM_MIN": Spec(300, "Минимум списания, бонусов", "int",
                       "Меньше этого бонусами не оплатить; кнопка в кассе неактивна с пояснением.",
                       group="Списание"),
    "HOLD_DAYS": Spec(14, "Удержание бонусов за покупку, дней", "int",
                      "Бонусы за покупку становятся доступны не раньше, чем через столько дней "
                      "после оплаты.", group="Покупки и удержание"),
    "DELIVERY_RETURN_DAYS": Spec(
        7, "Срок возврата после получения, дней", "int",
        "Бонусы за покупку держатся до позднего из двух: оплата + удержание или "
        "получение + этот срок. Не получен — держатся.", "координатор",
        group="Покупки и удержание"),
    "EXPIRY_MONTHS": Spec([6, 12, 12, 18], "Срок жизни бонусов, месяцев", "levels_int",
                          "Сколько живёт начисление; считается от даты начисления по уровню."),
    "EXPIRY_WARN_DAYS": Spec(30, "Предупреждать о сгорании за, дней", "int",
                             "Пуш и баннер с суммой и датой, не чаще раза в неделю.",
                             group="Сгорание"),
    "LEVEL_THRESHOLD": Spec(
        [500, 2000, 5000], "Порог уровня, статусных бонусов", "thresholds",
        "Статусные — всё начисленное за 365 дней, кроме бонуса за регистрацию. "
        "Пороги должны расти: Серебро < Золото < Платина."),
    "PLATINUM_MIN_SPEND": Spec(60000, "Покупки за 365 дней, от ₽", "int",
                               "Для Платины мало статусных — нужны ещё покупки на эту сумму.",
                               page="levels", level_only=3),
    "RESERVE_PER_BONUS": Spec(0.31, "Резерв на 1 бонус, ₽", "float",
                              "Учётная величина для отчётов: сколько рублей откладываем на "
                              "каждый начисленный бонус.", "аналитик Pareta, раз в полгода",
                              group="Учёт"),
    "STOPLOSS_COST_SHARE": Spec(0.07, "Стоп-кран: доля затрат от выручки, %", "float",
                                "Если затраты на бонусы выше этой доли выручки Store "
                                "несколько месяцев подряд — бонус за пробежку снижается.",
                                group="Стоп-кран", unit="%", max_value=1),
    "STOPLOSS_MONTHS": Spec(2, "Стоп-кран: месяцев подряд", "int", group="Стоп-кран"),
    "RUN_MIN_KM": Spec(3.0, "Пробежка: минимум, км", "float",
                       "Короче — без бонусов (дистанция по треку, не по цифре клиента).",
                       group="Проверка пробежки"),
    "RUN_PACE_MIN": Spec(180, "Пробежка: самый быстрый темп, мин:сек на км", "int",
                         "Быстрее — без бонусов и на ручную проверку.",
                         group="Проверка пробежки", unit="pace"),
    "RUN_PACE_MAX": Spec(720, "Пробежка: самый медленный темп, мин:сек на км", "int",
                         "Медленнее — без бонусов (это уже ходьба).",
                         group="Проверка пробежки", unit="pace"),
    # ── «Товары в программе» ──────────────────────────────────────────────────
    "EXCLUDED_CATEGORIES_1C": Spec(
        [], "Категории без оплаты бонусами", "codes",
        "Коды категорий 1С. Подкатегории исключаются вместе с категорией. "
        "Заполнить по названиям из ТЗ: manage.py loyalty_find_excluded_categories --apply"),
    "EXCLUDED_BRANDS": Spec(
        [], "Бренды без оплаты бонусами", "names",
        "Названия брендов как в карточке товара (регистр не важен)."),
    "EXCLUDED_PRODUCTS": Spec(
        [], "Товары без оплаты бонусами", "codes", "ID карточек товаров из каталога."),
    "NO_ACCRUAL_CATEGORIES_1C": Spec(
        [], "Категории без начисления бонусов", "codes",
        "За покупку товаров этих категорий (с подкатегориями) бонусы не начисляются."),
    "NO_ACCRUAL_BRANDS": Spec(
        [], "Бренды без начисления бонусов", "names",
        "За покупку товаров этих брендов бонусы не начисляются."),
    "NO_ACCRUAL_PRODUCTS": Spec(
        [], "Товары без начисления бонусов", "codes",
        "За покупку этих товаров бонусы не начисляются."),
}


def page_of(key) -> str:
    """На какой странице раздела «Программа лояльности» живёт настройка."""
    spec = SPECS[key]
    if spec.page:
        return spec.page
    if spec.kind in ("levels_int", "levels_float", "thresholds"):
        return "levels"
    if spec.kind in ("codes", "names"):
        return "products"
    return "accrual"


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


def _limit_text(spec) -> str:
    if spec.unit == "%":
        return f"не больше {round(spec.max_value * 100, 2):g}%"
    return f"не больше {spec.max_value:g}"


def validate(key, value, strict=False):
    """Проверить и привести значение настройки. ConfigError — с понятным текстом.

    `strict` — при сохранении (админка, команды): ещё и верхние границы `max_value`
    (например, оплата бонусами ≤ 30%). При чтении таблицы границы не проверяются:
    старое значение выше границы не «пропадает», его срезает код (`redeem_ceiling`).
    """
    spec = SPECS.get(key)
    if spec is None:
        raise ConfigError(f"Неизвестная настройка {key}")
    kind = spec.kind
    if kind == "bool":
        if not isinstance(value, bool):
            raise ConfigError("нужно true или false")
        return value
    if kind in ("int", "float"):
        out = _num(value, kind == "int")
        if strict and spec.max_value is not None and out > spec.max_value:
            raise ConfigError(_limit_text(spec))
        return out
    if kind in ("levels_int", "levels_float", "thresholds"):
        n = 3 if kind == "thresholds" else 4
        if not isinstance(value, list) or len(value) != n:
            raise ConfigError(f"нужен список из {n} чисел")
        out = [_num(v, kind != "levels_float") for v in value]
        if kind == "thresholds" and any(b <= a for a, b in zip(out, out[1:])):
            raise ConfigError("пороги должны расти: Серебро < Золото < Платина")
        if kind == "levels_float" and any(v > 1 for v in out):
            raise ConfigError("доля — от 0 до 1 (от 0 до 100%)")
        if strict and spec.max_value is not None and any(v > spec.max_value for v in out):
            raise ConfigError(_limit_text(spec))
        return out
    if kind == "codes":
        if not isinstance(value, list) or not all(isinstance(v, (str, int)) for v in value):
            raise ConfigError("нужен список кодов")
        return sorted({str(v).strip() for v in value if str(v).strip()})
    if kind == "names":
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise ConfigError("нужен список названий")
        seen, out = set(), []
        for v in value:
            name = " ".join(v.split())
            if name and name.casefold() not in seen:
                seen.add(name.casefold())
                out.append(name)
        return sorted(out, key=str.casefold)
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

    value = validate(key, value, strict=True)
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


def set_many(values: dict, by="", comment="") -> list:
    """Сохранить несколько настроек разом: сначала проверка ВСЕХ (ошибка — ничего не
    пишется), потом запись одной транзакцией. Каждое изменение — строка истории.
    Значение, совпадающее с действующим (в том числе «по ТЗ»), не пишется.
    Возвращает список изменённых ключей. ConfigError({ключ: текст}) — при ошибках."""
    from django.db import transaction

    errors, clean = {}, {}
    for key, value in values.items():
        try:
            clean[key] = validate(key, value, strict=True)
        except ConfigError as e:
            errors[key] = str(e)
    if errors:
        raise ConfigError(errors)
    changed = [k for k, v in clean.items() if v != get(k)]
    with transaction.atomic():
        for key in changed:
            set_value(key, clean[key], by=by, comment=comment)
    invalidate()
    return changed


def ensure_rows() -> None:
    """Завести строки для всех настроек (значение пусто = «как в ТЗ»), чтобы в
    админке был виден полный список."""
    from .models import LoyaltySetting

    have = set(LoyaltySetting.objects.values_list("key", flat=True))
    missing = [LoyaltySetting(key=k, value=None) for k in SPECS if k not in have]
    if missing:
        LoyaltySetting.objects.bulk_create(missing, ignore_conflicts=True)
