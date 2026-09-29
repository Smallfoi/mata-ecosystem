import os
import secrets
from datetime import timedelta

from django.db import models, transaction
from django.db.models import Max, Min, Q, Sum
from django.utils import timezone

# Баллы за АКТИВНОСТЬ (бег, импорт с часов, захват, вехи, дивизион/сезон) «созревают»
# MATURATION дней, прежде чем их можно потратить (решение владельца 28.09.2026).
# Покупки, бонусы, возвраты и списания доступны сразу. Зачем: накрутчик не может
# вывести баллы в Store в тот же день — у модерации есть окно разобраться.
ACTIVITY_SOURCES = frozenset({
    "runnerRun", "runnerTerritory", "runnerMilestone", "runnerDivision", "runnerSeason",
})
MATURATION = timedelta(days=3)


class LoyaltyTransaction(models.Model):
    """Транзакция баллов — те же поля, что в FastAPI loyalty_transactions."""
    id = models.CharField(primary_key=True, max_length=40, verbose_name="ID")
    user_id = models.CharField(max_length=40, db_index=True, verbose_name="Пользователь (ID)")
    amount = models.IntegerField(verbose_name="Сумма баллов")
    source = models.CharField(max_length=40, verbose_name="Источник")
    description = models.CharField(max_length=300, blank=True, default="", verbose_name="Описание")
    order_id = models.CharField(max_length=40, null=True, blank=True, verbose_name="Заказ (ID)")
    run_id = models.CharField(max_length=80, null=True, blank=True, verbose_name="Забег (ID)")
    created_at = models.DateTimeField(default=timezone.now, verbose_name="Дата")
    # С какого момента баллы можно тратить. Пусто — сразу (покупки, бонусы и всё,
    # что начислено до правила созревания). Заполняется у баллов за активность.
    available_at = models.DateTimeField(
        null=True, blank=True, db_index=True, verbose_name="Доступны с"
    )

    class Meta:
        db_table = "loyalty_transactions"
        verbose_name = "Транзакция баллов"
        verbose_name_plural = "Баллы (транзакции)"

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "amount": self.amount,
            "source": self.source,
            "description": self.description,
            "orderId": self.order_id,
            "createdAt": self.created_at.isoformat(),
            # Новое поле (старые клиенты его не читают): с какого момента баллы
            # можно тратить; null — сразу.
            "availableAt": self.available_at.isoformat() if self.available_at else None,
        }


_AUTO = object()


def _auto_available_at(user_id, amount, source, run_id, now):
    """Срок доступности новой проводки.

    - начисление за активность — через MATURATION;
    - встречная проводка по тому же забегу/захвату (отзыв, корректировка) — тот же
      срок, что у ещё не созревшего начисления: иначе отзыв несозревших баллов
      сразу уменьшал бы тратимый остаток, хотя сами баллы ещё не тратились;
    - всё остальное — сразу.
    """
    if amount > 0 and source in ACTIVITY_SOURCES:
        return now + MATURATION
    if amount < 0 and run_id:
        return LoyaltyTransaction.objects.filter(
            user_id=user_id, run_id=run_id, amount__gt=0, available_at__gt=now,
        ).aggregate(m=Max("available_at"))["m"]
    return None


def add_txn(user_id, amount, source, description="", order_id=None, run_id=None,
            available_at=_AUTO):
    """Записать операцию по кошельку. Под замком кошелька (loyalty.wallet, аудит B03):
    «баланс до» и запись — без гонки с параллельной операцией того же пользователя.
    Проверки «не было ли уже» и «хватает ли» делают вызывающие — тоже под замком
    (wallet.post_once / wallet.redeem), иначе замок здесь их не защитит.

    `available_at` по умолчанию считается сам (созревание баллов за активность)."""
    from .wallet import lock_wallet

    with transaction.atomic():
        lock_wallet(user_id)
        now = timezone.now()
        if available_at is _AUTO:
            available_at = _auto_available_at(user_id, amount, source, run_id, now)
        # Баланс ДО этой транзакции — чтобы поймать пересечение порога уровня.
        before = balance_of(user_id)
        txn = LoyaltyTransaction.objects.create(
            id=f"tx_{secrets.token_hex(8)}",
            user_id=user_id,
            amount=amount,
            source=source,
            description=description,
            order_id=order_id,
            run_id=run_id,
            created_at=now,
            available_at=available_at,
        )
    if amount > 0 and not _v1_enabled():
        # При включённой v1 уровни и их уведомления ведёт loyalty.v1.
        _notify_level_up(user_id, before, before + amount)
    # Баллы юзера изменились (баланс/заработано/потрачено; забег/заказ, породившие
    # транзакцию, уже в БД) → сбрасываем его пер-юзерные кэши: статистика + лояльность (D-29).
    from common.cache import invalidate_user

    invalidate_user(user_id)
    return txn


def _v1_enabled() -> bool:
    from .config import enabled

    return enabled()


_LEVEL_RANK = {"basic": 0, "silver": 1, "gold": 2, "platinum": 3}
_LEVEL_UP = {
    "silver": ("Новый уровень: Серебро", "Вы достигли уровня «Серебро». Так держать!"),
    "gold": ("Новый уровень: Золото", "Вы достигли уровня «Золото» — отличный результат!"),
    "platinum": ("Новый уровень: Платина", "Максимальный уровень «Платина». Легенда!"),
}


def _notify_level_up(user_id, before_balance, after_balance):
    """Уведомление при РОСТЕ уровня (бег/территории/покупки — любой источник через
    add_txn). Срабатывает один раз на реальное пересечение порога: дедуп начислений
    (по run_id/order_id) делается до add_txn, поэтому повторов нет. Сбой уведомления
    не должен ломать начисление баллов."""
    lvl_before = level_for(before_balance)
    lvl_after = level_for(after_balance)
    if _LEVEL_RANK.get(lvl_after, 0) <= _LEVEL_RANK.get(lvl_before, 0):
        return
    title_body = _LEVEL_UP.get(lvl_after)
    if not title_body:
        return
    try:
        from notifications.models import create_notification

        create_notification(user_id, title_body[0], title_body[1], type="level")
    except Exception:
        pass


def seed_runner_points(user_id):
    """Демо-баллы при создании аккаунта. По умолчанию ВЫКЛ — новый пользователь
    начинает с нуля (реальный лидерборд/экономика, не засоряем фейковыми 16 км).
    Включить можно флагом SEED_DEMO_POINTS=1 (например для демо в dev)."""
    if os.environ.get("SEED_DEMO_POINTS", "0") != "1" or _v1_enabled():
        # При включённой программе v1 демо-баллы не начисляются (решение координатора).
        return
    demo = [
        (20, "registration", "Бонус за регистрацию"),
        (120, "runnerRun", "Пробежка 12.0 км"),
        (50, "runnerTerritory", "Захват территории: ул. Спортивная"),
        (200, "runnerCompetition", "Победа в забеге «Весенний круг»"),
        (40, "runnerRun", "Пробежка 4.0 км"),
    ]
    for amount, source, desc in demo:
        add_txn(user_id, amount, source, desc)


def balance_of(user_id) -> int:
    """ПОЛНЫЙ баланс (все проводки, включая несозревшие) одним SQL-агрегатом.

    Для уровня и истории. Сколько можно ПОТРАТИТЬ — `spendable_of`."""
    return (
        LoyaltyTransaction.objects.filter(user_id=user_id).aggregate(s=Sum("amount"))[
            "s"
        ]
        or 0
    )


def on_review(user_id) -> bool:
    """Аккаунт на проверке у модератора (`Account.needs_review`)."""
    from accounts.models import Account

    return Account.objects.filter(id=user_id, needs_review=True).exists()


def wallet_summary(user_id, now=None) -> dict:
    """Разбивка кошелька: всего, можно потратить, ещё недоступно.

    Недоступно (`pending`):
    - баллы за активность, чей срок `available_at` ещё не наступил;
    - если аккаунт на проверке (`Account.needs_review`, решение владельца
      28.09.2026) — ВСЕ баллы за активность, начисленные по правилу созревания
      (у них есть `available_at`), даже уже созревшие: до решения модератора они
      не тратятся (`frozen`). Сняли метку — снова обычный срок.
    Баллы, начисленные до правила (available_at пуст), не замораживаются.

    Тратимое не бывает меньше нуля: если замороженные баллы уже потрачены,
    тратить просто нечего.

    При включённой программе v1 (loyalty.config LOYALTY_V1_ENABLED) — те же ключи
    по лотам v1: total = доступно + ожидает, spendable = можно списать, pending =
    лоты в удержании. Так прежние клиенты и экраны видят баланс новой программы.
    """
    if _v1_enabled():
        from . import v1

        w = v1.wallet(user_id, now)
        return {
            "total": w["available"] + w["held"],
            "spendable": w["redeemable"],
            "pending": w["held"],
            "frozen": w["frozen"],
            "next_at": w["next_at"],
            "next_amount": w["next_amount"],
        }
    now = now or timezone.now()
    frozen = on_review(user_id)
    qs = LoyaltyTransaction.objects.filter(user_id=user_id)
    locked_q = Q(available_at__isnull=False) if frozen else Q(available_at__gt=now)
    agg = qs.aggregate(total=Sum("amount"), locked=Sum("amount", filter=locked_q))
    total = agg["total"] or 0
    locked = max(0, agg["locked"] or 0)
    spendable = max(0, total - locked)
    next_at, next_amount = None, 0
    if locked and not frozen:
        next_at = qs.filter(available_at__gt=now, amount__gt=0).aggregate(
            m=Min("available_at")
        )["m"]
        if next_at is not None:
            # «Ближайшая партия» — всё, что созревает в тот же день (местное время
            # сервера): строка «N баллов станут доступны <дата>» не должна врать.
            day = timezone.localtime(next_at).date()
            next_amount = sum(
                t.amount
                for t in qs.filter(available_at__gt=now).only("amount", "available_at")
                if timezone.localtime(t.available_at).date() == day
            )
    return {
        "total": total,
        "spendable": spendable,
        "pending": locked,
        "frozen": frozen,
        "next_at": next_at,
        "next_amount": max(0, next_amount),
    }


def spendable_of(user_id) -> int:
    """Сколько баллов можно потратить прямо сейчас (списание и показ `balance`)."""
    return wallet_summary(user_id)["spendable"]


def level_for(balance: int) -> str:
    if balance >= 1000:
        return "platinum"
    if balance >= 500:
        return "gold"
    if balance >= 200:
        return "silver"
    return "basic"


class LoyaltyPartner(models.Model):
    """Партнёр программы лояльности на карте (D-81): бизнес, принимающий баллы МАТА.
    Заводит владелец в админке. Публичный GET /v1/loyalty/partners (токен не нужен) —
    слой «Партнёры» на «Карте» приложения (за клиентским флагом, пока не наберём базу)."""

    CATEGORY_CHOICES = [
        ("nutrition", "Спортпитание и витамины"),
        ("coffee", "Кофе"),
        ("gear", "Экипировка"),
        ("food", "Здоровое питание"),
        ("other", "Другое"),
    ]

    name = models.CharField(max_length=160, verbose_name="Название")
    category = models.CharField(
        max_length=20, choices=CATEGORY_CHOICES, default="nutrition",
        db_index=True, verbose_name="Категория",
    )
    emoji = models.CharField(
        max_length=8, blank=True, default="", verbose_name="Значок (эмодзи)",
        help_text="Пока нет логотипа — эмодзи на метке, напр. 🥗 ☕ 👟",
    )
    logo = models.ImageField(
        upload_to="partners/", blank=True, null=True,
        verbose_name="Логотип (необязательно)",
    )
    city = models.CharField(
        max_length=120, blank=True, default="Якутск", db_index=True, verbose_name="Город",
    )
    address = models.CharField(max_length=250, blank=True, default="", verbose_name="Адрес")
    description = models.CharField(
        max_length=250, blank=True, default="", verbose_name="Описание",
        help_text="Коротко: «спортивное питание», «кофе с собой»",
    )
    lat = models.FloatField(verbose_name="Широта")
    lng = models.FloatField(verbose_name="Долгота")
    points_percent = models.PositiveIntegerField(
        default=0, verbose_name="Оплата баллами, % от суммы",
        help_text="До скольких % чека можно оплатить баллами МАТА (напр. 30)",
    )
    is_active = models.BooleanField(
        default=True, db_index=True, verbose_name="Активен (показывать на карте)",
    )
    created_at = models.DateTimeField(default=timezone.now, verbose_name="Заведён")

    class Meta:
        db_table = "loyalty_partners"
        verbose_name = "Партнёр на карте"
        verbose_name_plural = "Партнёры на карте (лояльность)"
        ordering = ["name"]

    def __str__(self):
        return self.name

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "emoji": self.emoji,
            "logoUrl": self.logo.url if self.logo else None,
            "city": self.city,
            "address": self.address,
            "description": self.description,
            "lat": self.lat,
            "lng": self.lng,
            "pointsPercent": self.points_percent,
        }


# Программа лояльности v1 (ТЗ 30.09.2026): лоты, уровень, списания, журнал, настройки.
from .models_v1 import (  # noqa: E402,F401
    LoyaltyEvent,
    LoyaltyLot,
    LoyaltyRedemption,
    LoyaltyRedemptionPart,
    LoyaltyReserve,
    LoyaltyRuleSnapshot,
    LoyaltySetting,
    LoyaltySettingChange,
    LoyaltyStatus,
)
