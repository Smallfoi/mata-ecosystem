import os
import secrets

from django.db import models
from django.db.models import Sum
from django.utils import timezone


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
        }


def add_txn(user_id, amount, source, description="", order_id=None, run_id=None):
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
    )
    if amount > 0:
        _notify_level_up(user_id, before, before + amount)
    # Баллы юзера изменились (баланс/заработано/потрачено; забег/заказ, породившие
    # транзакцию, уже в БД) → сбрасываем его пер-юзерные кэши: статистика + лояльность (D-29).
    from common.cache import invalidate_user

    invalidate_user(user_id)
    return txn


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
    if os.environ.get("SEED_DEMO_POINTS", "0") != "1":
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
    """Баланс одним SQL-агрегатом (а не загрузкой всех транзакций в Python)."""
    return (
        LoyaltyTransaction.objects.filter(user_id=user_id).aggregate(s=Sum("amount"))[
            "s"
        ]
        or 0
    )


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
