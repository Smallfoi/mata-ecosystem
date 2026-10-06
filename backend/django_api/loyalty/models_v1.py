"""Модели программы лояльности v1 (ТЗ 30.09.2026): лоты, уровень, списания на
заказ, журнал, резерв, настройки с историей. Правила — в `loyalty.v1`."""
import uuid

from django.core.exceptions import PermissionDenied
from django.db import models
from django.db.models import Q
from django.utils import timezone


class LoyaltySetting(models.Model):
    """Настройка программы (ключ → значение). Значение пусто — действует v1 из ТЗ."""

    key = models.CharField(primary_key=True, max_length=40, verbose_name="Параметр")
    value = models.JSONField(null=True, blank=True, verbose_name="Значение",
                             help_text="Пусто — значение по ТЗ v1.")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Изменено")
    updated_by = models.CharField(max_length=150, blank=True, default="",
                                  verbose_name="Кем изменено")

    class Meta:
        db_table = "loyalty_settings"
        ordering = ["key"]
        verbose_name = "Настройка лояльности"
        verbose_name_plural = "Настройки лояльности"

    def __str__(self):
        return self.key


class LoyaltySettingChange(models.Model):
    """История настроек: кто, когда, старое → новое. Только добавление."""

    key = models.CharField(max_length=40, db_index=True, verbose_name="Параметр")
    old_value = models.JSONField(null=True, blank=True, verbose_name="Было")
    new_value = models.JSONField(null=True, blank=True, verbose_name="Стало")
    changed_by = models.CharField(max_length=150, blank=True, default="", verbose_name="Кто")
    changed_at = models.DateTimeField(default=timezone.now, db_index=True, verbose_name="Когда")
    comment = models.CharField(max_length=300, blank=True, default="", verbose_name="Комментарий")

    class Meta:
        db_table = "loyalty_setting_changes"
        ordering = ["-changed_at", "-id"]
        verbose_name = "Изменение настройки лояльности"
        verbose_name_plural = "История настроек лояльности"


class LoyaltyLot(models.Model):
    """Лот — одно начисление (ТЗ §2): сумма, остаток, состояние, даты, источник.

    Доступно = сумма остатков available; ожидает = остатки held. Отрицательный лот
    (`source="debt"`, остаток < 0) — долг после возврата товара, когда начисленные
    за покупку бонусы уже потрачены (ТЗ §4); гасится следующими начислениями.
    """

    HELD, AVAILABLE, SPENT, EXPIRED, CANCELLED = (
        "held", "available", "spent", "expired", "cancelled")
    STATE_CHOICES = [
        (HELD, "Ожидает"), (AVAILABLE, "Доступен"), (SPENT, "Потрачен"),
        (EXPIRED, "Сгорел"), (CANCELLED, "Отменён"),
    ]

    user_id = models.CharField(max_length=40, db_index=True, verbose_name="Пользователь (ID)")
    amount = models.IntegerField(verbose_name="Начислено")
    remaining = models.IntegerField(verbose_name="Остаток")
    state = models.CharField(max_length=10, choices=STATE_CHOICES, verbose_name="Состояние")
    source = models.CharField(max_length=40, verbose_name="Источник")
    source_ref = models.CharField(max_length=80, blank=True, default="",
                                  verbose_name="Основание (заказ/пробежка/…)")
    # Статусные (ТЗ §2): сколько из этого начисления идёт в статусные. Регистрация,
    # ручное, перенос баланса — 0. Возврат покупки уменьшает.
    status_amount = models.IntegerField(default=0, verbose_name="В статусные")
    accrued_at = models.DateTimeField(default=timezone.now, db_index=True,
                                      verbose_name="Начислен")
    available_at = models.DateTimeField(null=True, blank=True, verbose_name="Доступен с")
    expires_at = models.DateTimeField(null=True, blank=True, db_index=True,
                                      verbose_name="Сгорает")
    level_at_accrual = models.PositiveSmallIntegerField(default=0,
                                                        verbose_name="Уровень при начислении")
    meta = models.JSONField(default=dict, blank=True, verbose_name="Подробности")
    created_at = models.DateTimeField(default=timezone.now, verbose_name="Создан")

    class Meta:
        db_table = "loyalty_lots"
        ordering = ["expires_at", "accrued_at", "id"]
        verbose_name = "Лот бонусов"
        verbose_name_plural = "Лоты бонусов"
        indexes = [
            models.Index(fields=["user_id", "state"], name="loyalty_lot_user_state"),
            models.Index(fields=["state", "expires_at"], name="loyalty_lot_state_exp"),
            models.Index(fields=["source", "source_ref"], name="loyalty_lot_source_ref"),
        ]
        constraints = [
            # Одна покупка — один лот; один перенос баланса на пользователя.
            models.UniqueConstraint(fields=["user_id", "source_ref"],
                                    condition=Q(source="purchase"),
                                    name="loyalty_lot_one_purchase"),
            models.UniqueConstraint(fields=["user_id"], condition=Q(source="migration"),
                                    name="loyalty_lot_one_migration"),
        ]

    def __str__(self):
        return f"{self.user_id}: {self.remaining}/{self.amount} ({self.state})"


class LoyaltyStatus(models.Model):
    """Уровень участника и служебное состояние кошелька v1 (одна строка на человека).

    Строка появляется при переносе баланса в v1 (`loyalty_migrate_v1` или лениво —
    при первом обращении к v1): с этого момента операции старого реестра по этому
    человеку зеркалятся в лоты.
    """

    user_id = models.CharField(max_length=40, unique=True, verbose_name="Пользователь (ID)")
    level = models.PositiveSmallIntegerField(default=0, verbose_name="Уровень")
    level_until = models.DateTimeField(null=True, blank=True, verbose_name="Уровень до")
    level_since = models.DateTimeField(null=True, blank=True,
                                       verbose_name="Последнее повышение")
    migrated_at = models.DateTimeField(default=timezone.now, verbose_name="Перенесён в v1")
    legacy_balance = models.IntegerField(default=0, verbose_name="Перенесено из старого реестра")
    expiry_warned_at = models.DateTimeField(null=True, blank=True,
                                            verbose_name="Предупреждён о сгорании")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Обновлено")

    class Meta:
        db_table = "loyalty_status"
        verbose_name = "Уровень участника"
        verbose_name_plural = "Уровни участников"

    def __str__(self):
        return f"{self.user_id}: {self.level}"


class LoyaltyRedemption(models.Model):
    """Списание бонусов на заказ (ТЗ §4): блок при создании, списание при оплате,
    разблокировка при отмене. Разбивка по лотам — `LoyaltyRedemptionPart`."""

    BLOCKED, SPENT, RELEASED = "blocked", "spent", "released"
    STATE_CHOICES = [(BLOCKED, "Заблокировано"), (SPENT, "Списано"),
                     (RELEASED, "Разблокировано")]

    user_id = models.CharField(max_length=40, db_index=True, verbose_name="Пользователь (ID)")
    order_id = models.CharField(max_length=40, verbose_name="Заказ")
    amount = models.IntegerField(verbose_name="Бонусов")
    returned = models.IntegerField(default=0, verbose_name="Возвращено (возвраты товара)")
    state = models.CharField(max_length=10, choices=STATE_CHOICES, default=BLOCKED,
                             verbose_name="Состояние")
    level_at = models.PositiveSmallIntegerField(default=0, verbose_name="Уровень при оформлении")
    eligible_kop = models.BigIntegerField(default=0, verbose_name="Допущено к списанию, коп.")
    ceiling = models.FloatField(default=0, verbose_name="Потолок, доля")
    # Допущенная сумма по каждой единице товара в порядке позиций чека
    # (orders.receipt.allocate): по ней возврат делит списанные бонусы.
    unit_eligible_kop = models.JSONField(default=list, blank=True,
                                         verbose_name="Допущено по единицам, коп.")
    created_at = models.DateTimeField(default=timezone.now, verbose_name="Создано")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Обновлено")

    class Meta:
        db_table = "loyalty_redemptions"
        ordering = ["-created_at"]
        verbose_name = "Списание на заказ"
        verbose_name_plural = "Списания на заказы"
        constraints = [
            models.UniqueConstraint(fields=["user_id", "order_id"],
                                    name="loyalty_redemption_one_per_order"),
        ]


class LoyaltyRedemptionPart(models.Model):
    redemption = models.ForeignKey(LoyaltyRedemption, on_delete=models.CASCADE,
                                   related_name="parts", verbose_name="Списание")
    lot = models.ForeignKey(LoyaltyLot, on_delete=models.CASCADE, related_name="redemptions",
                            verbose_name="Лот")
    amount = models.IntegerField(verbose_name="Бонусов")
    returned = models.IntegerField(default=0, verbose_name="Возвращено")

    class Meta:
        db_table = "loyalty_redemption_parts"
        verbose_name = "Списание из лота"
        verbose_name_plural = "Списания из лотов"


class AppendOnlyQuerySet(models.QuerySet):
    """Журнал только дописывается: массовые update/delete запрещены."""

    def update(self, **kwargs):
        raise PermissionDenied("Журнал лояльности нельзя изменять")

    def delete(self):
        raise PermissionDenied("Журнал лояльности нельзя удалять")

    def bulk_update(self, *args, **kwargs):
        raise PermissionDenied("Журнал лояльности нельзя изменять")


class LoyaltyEvent(models.Model):
    """Журнал loyalty_events (ТЗ §5) — только добавление.

    Запись на каждое изменение баланса или уровня. Человека указывает только
    постоянный случайный псевдоним (`Account.loyalty_pseudonym`): удаление аккаунта
    стирает связь псевдоним → человек, журнал остаётся обезличенным.
    Изменение/удаление запрещено моделью, менеджером, админкой и триггером БД.
    """

    TYPES = [
        "accrue_purchase", "accrue_run", "accrue_capture", "accrue_stage", "accrue_referral",
        "accrue_signup", "accrue_manual", "accrue_migration", "hold_release", "redeem",
        "redeem_return", "cancel", "expire", "level_up", "level_down",
        "stoploss_on", "stoploss_off",
    ]

    event_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False,
                                verbose_name="ID события")
    created_at = models.DateTimeField(default=timezone.now, db_index=True,
                                      verbose_name="Когда (UTC)")
    user_pseudonym = models.CharField(max_length=40, db_index=True, verbose_name="Псевдоним")
    type = models.CharField(max_length=20, choices=[(t, t) for t in TYPES], db_index=True,
                            verbose_name="Тип")
    amount = models.IntegerField(default=0, verbose_name="Сумма (со знаком)")
    balance_after = models.IntegerField(default=0, verbose_name="Доступно после")
    status_points_after = models.IntegerField(default=0, verbose_name="Статусные после")
    level_at_event = models.PositiveSmallIntegerField(default=0, verbose_name="Уровень до")
    level_after = models.PositiveSmallIntegerField(default=0, verbose_name="Уровень после")
    lot_id = models.BigIntegerField(null=True, blank=True, verbose_name="Лот")
    lot_expires_at = models.DateTimeField(null=True, blank=True, verbose_name="Лот сгорает")
    source_ref = models.CharField(max_length=80, blank=True, default="",
                                  verbose_name="Основание")
    order_total = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True,
                                      verbose_name="Сумма заказа")
    eligible_total = models.DecimalField(max_digits=12, decimal_places=2, null=True,
                                         blank=True, verbose_name="Допущено к списанию")
    cash_part = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True,
                                    verbose_name="Денежная часть")
    cogs_total = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True,
                                     verbose_name="Себестоимость (1С)")
    partner_id = models.CharField(max_length=40, blank=True, default="", verbose_name="Партнёр")
    rule_version = models.CharField(max_length=40, verbose_name="Версия правил")
    note = models.CharField(max_length=300, blank=True, default="", verbose_name="Комментарий")

    objects = AppendOnlyQuerySet.as_manager()

    class Meta:
        db_table = "loyalty_events"
        ordering = ["-created_at"]
        verbose_name = "Событие лояльности"
        verbose_name_plural = "Журнал лояльности"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise PermissionDenied("Журнал лояльности нельзя изменять")
        kwargs["force_insert"] = True
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionDenied("Журнал лояльности нельзя удалять")


class LoyaltyRuleSnapshot(models.Model):
    """Слепок констант, действовавших при событии (rule_version → значения)."""

    version = models.CharField(primary_key=True, max_length=40, verbose_name="Версия")
    constants = models.JSONField(verbose_name="Константы")
    created_at = models.DateTimeField(default=timezone.now, verbose_name="Впервые")

    class Meta:
        db_table = "loyalty_rule_snapshots"
        verbose_name = "Версия правил лояльности"
        verbose_name_plural = "Версии правил лояльности"


class LoyaltyReserve(models.Model):
    """Системный счётчик reserve_rub (ТЗ §2): учётная величина для отчётов."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1)
    reserve_rub = models.DecimalField(max_digits=14, decimal_places=2, default=0,
                                      verbose_name="Резерв, ₽")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Обновлён")

    class Meta:
        db_table = "loyalty_reserve"
        verbose_name = "Резерв бонусов"
        verbose_name_plural = "Резерв бонусов"


# ── Этап 2: активность, приглашения, регистрация ─────────────────────────────

class LoyaltyActivity(models.Model):
    """Решение по бонусу за активность (ТЗ §3): пробежка, захват, этап.

    Одна строка на событие (пробежка — наш забег или импорт; захват — CaptureAward;
    этап — 1-е место в месячном итоге дивизиона). Хранит, ЧТО решили и почему:
    начислено / лимит месяца / не прошла условия / дубль / на проверке. По строкам
    `granted` считаются месячные капы. Игра (забег, территория, лиги) от этого
    решения не зависит — здесь только бонусы.
    """

    RUN, CAPTURE, STAGE = "run", "capture", "stage"
    KIND_CHOICES = [(RUN, "Пробежка"), (CAPTURE, "Захват"), (STAGE, "Этап")]

    GRANTED = "granted"        # бонус начислен
    CAPPED = "capped"          # засчитано, лимит месяца исчерпан
    DAY_LIMIT = "day_limit"    # в этот день уже есть зачтённая пробежка
    DUPLICATE = "duplicate"    # та же тренировка другим путём
    INELIGIBLE = "ineligible"  # не прошла условия ТЗ (коротко, медленно, поздно)
    SUSPICIOUS = "suspicious"  # на ручной проверке (очередь в админке)
    FLAGGED = "flagged"        # забег помечен античитом игры — ждёт решения по нему
    WAITING = "waiting"        # захват ждёт решения по своей пробежке
    REJECTED = "rejected"      # отклонено модератором
    STATUS_CHOICES = [
        (GRANTED, "Начислено"), (CAPPED, "Лимит месяца"), (DAY_LIMIT, "Не первая за день"),
        (DUPLICATE, "Дубль"), (INELIGIBLE, "Не прошла условия"),
        (SUSPICIOUS, "На проверке"), (FLAGGED, "Забег помечен"),
        (WAITING, "Ждёт пробежку"), (REJECTED, "Отклонено"),
    ]

    user_id = models.CharField(max_length=40, db_index=True, verbose_name="Пользователь (ID)")
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, verbose_name="Событие")
    ref = models.CharField(max_length=80, verbose_name="Основание (забег/захват/этап)")
    source = models.CharField(max_length=20, blank=True, default="",
                              verbose_name="Источник (app / импорт)")
    run_ref = models.CharField(max_length=80, blank=True, default="", db_index=True,
                               verbose_name="Пробежка захвата")
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, db_index=True,
                              verbose_name="Решение")
    amount = models.IntegerField(default=0, verbose_name="Начислено бонусов")
    lot_id = models.BigIntegerField(null=True, blank=True, verbose_name="Лот")
    # Календарный месяц по Якутску (UTC+9), в счёт которого идёт событие: «2026-10».
    month = models.CharField(max_length=7, db_index=True, verbose_name="Месяц")
    day = models.DateField(null=True, blank=True, verbose_name="День (якут.)")
    started_at = models.DateTimeField(null=True, blank=True, verbose_name="Начало")
    finished_at = models.DateTimeField(null=True, blank=True, verbose_name="Конец")
    distance_m = models.FloatField(default=0, verbose_name="Дистанция для проверки, м")
    duration_s = models.IntegerField(default=0, verbose_name="Время для проверки, с")
    # Чем проверена пробежка: «track» — серверный пересчёт трека, «summary» —
    # итоги от клиента (трека нет: старая сборка, тропы выключены, импорт).
    validated_by = models.CharField(max_length=10, blank=True, default="",
                                    verbose_name="Проверено по")
    reason = models.CharField(max_length=200, blank=True, default="", verbose_name="Причина")
    meta = models.JSONField(default=dict, blank=True, verbose_name="Подробности")
    created_at = models.DateTimeField(default=timezone.now, verbose_name="Создано")
    reviewed_at = models.DateTimeField(null=True, blank=True, verbose_name="Разобрано")
    reviewed_by = models.CharField(max_length=150, blank=True, default="",
                                   verbose_name="Кто разобрал")

    class Meta:
        db_table = "loyalty_activity"
        ordering = ["-created_at"]
        verbose_name = "Бонус за активность"
        verbose_name_plural = "Бонусы за активность"
        indexes = [
            models.Index(fields=["user_id", "month", "status"], name="loyalty_act_month"),
            models.Index(fields=["user_id", "kind", "day"], name="loyalty_act_day"),
        ]
        constraints = [
            models.UniqueConstraint(fields=["user_id", "kind", "ref"],
                                    name="loyalty_act_one_per_event"),
        ]

    def __str__(self):
        return f"{self.user_id}: {self.kind} {self.ref} → {self.status}"


class LoyaltyReferralCode(models.Model):
    """Постоянный код приглашения у аккаунта (ТЗ §3 «Реферал»)."""

    user_id = models.CharField(max_length=40, unique=True, verbose_name="Пользователь (ID)")
    code = models.CharField(max_length=12, unique=True, verbose_name="Код приглашения")
    created_at = models.DateTimeField(default=timezone.now, verbose_name="Выдан")

    class Meta:
        db_table = "loyalty_referral_codes"
        verbose_name = "Код приглашения"
        verbose_name_plural = "Коды приглашения"

    def __str__(self):
        return self.code


class LoyaltyReferral(models.Model):
    """Связь «кто пригласил» — одна на приглашённого, навсегда (ТЗ §3).

    `user_id` — приглашённый, `inviter_id` — пригласивший. Бонус пригласившему —
    когда первый заказ приглашённого вышел из удержания без возврата.
    """

    BOUND, REWARDED, CAPPED, REJECTED = "bound", "rewarded", "capped", "rejected"
    STATUS_CHOICES = [(BOUND, "Привязан"), (REWARDED, "Бонус начислен"),
                      (CAPPED, "Лимит месяца"), (REJECTED, "Отклонено")]

    user_id = models.CharField(max_length=40, unique=True, verbose_name="Приглашённый (ID)")
    inviter_id = models.CharField(max_length=40, db_index=True, verbose_name="Пригласил (ID)")
    code = models.CharField(max_length=12, verbose_name="Код")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=BOUND,
                              db_index=True, verbose_name="Статус")
    lot_id = models.BigIntegerField(null=True, blank=True, verbose_name="Лот бонуса")
    note = models.CharField(max_length=200, blank=True, default="", verbose_name="Пометка")
    created_at = models.DateTimeField(default=timezone.now, verbose_name="Привязан")
    rewarded_at = models.DateTimeField(null=True, blank=True, verbose_name="Решён")

    class Meta:
        db_table = "loyalty_referrals"
        ordering = ["-created_at"]
        verbose_name = "Приглашение"
        verbose_name_plural = "Приглашения"


class LoyaltyPhoneGrant(models.Model):
    """«Этот телефон уже получил разовый бонус» — переживает удаление аккаунта.

    Хранится не номер, а HMAC от нормализованного номера (ключ — SECRET_KEY): по
    строке нельзя узнать телефон, но тот же номер даёт тот же ключ. Пользователя
    здесь нет — строка не персональная и при удалении аккаунта остаётся, иначе
    удалил-зарегистрировался = второй бонус за регистрацию.
    """

    SIGNUP, REFERRAL = "signup", "referral"
    KIND_CHOICES = [(SIGNUP, "Бонус за регистрацию"),
                    (REFERRAL, "Бонус за приглашение этого телефона")]

    key = models.CharField(max_length=64, verbose_name="Ключ телефона (HMAC)")
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, verbose_name="Бонус")
    created_at = models.DateTimeField(default=timezone.now, verbose_name="Когда")

    class Meta:
        db_table = "loyalty_phone_grants"
        verbose_name = "Разовый бонус телефона"
        verbose_name_plural = "Разовые бонусы телефонов"
        constraints = [
            models.UniqueConstraint(fields=["key", "kind"], name="loyalty_phone_grant_once"),
        ]


class LoyaltyStageClose(models.Model):
    """Отметка «месячный этап закрыт» — бонусы за этап выдаются один раз."""

    month = models.CharField(primary_key=True, max_length=7, verbose_name="Месяц")
    closed_at = models.DateTimeField(default=timezone.now, verbose_name="Закрыт")
    winners = models.JSONField(default=list, blank=True, verbose_name="Победители")

    class Meta:
        db_table = "loyalty_stage_closes"
        verbose_name = "Закрытие этапа"
        verbose_name_plural = "Закрытия этапов"
