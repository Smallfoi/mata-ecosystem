"""Защита от другого человека: чёрный список и жалобы (§9–§10 LAUNCH_READINESS).

До этого в экосистеме не было ни того, ни другого: модератор мог спрятать клуб
(`Club.is_hidden`), но у ПОЛЬЗОВАТЕЛЯ не было ни одной кнопки — ни пожаловаться
на чужое имя, аватар или поведение, ни перестать быть видимым для конкретного
человека. Для продукта с живой картой друзей это дыра: позиции огрублены и
выключены по умолчанию, но защита «от всех сразу» не заменяет защиту «от него».

Два решения, которые стоит знать до чтения кода:

1. **Блокировка хранится односторонне, а действует в обе стороны.** В таблице
   одна строка «я заблокировал его». Но прятать только одного — полумера: если
   он продолжает видеть меня в поиске и слать заявки, блокировка не работает.
   Поэтому `hidden_ids` объединяет оба направления.
2. **Разблокировка не возвращает дружбу.** Блокировка рвёт связь; вернуться в
   друзья можно только новой заявкой, которую второй примет.
"""
from django.db import models
from django.db.models import Q
from django.utils import timezone


class Block(models.Model):
    """«Я не хочу, чтобы этот человек меня видел и писал мне»."""

    user_id = models.CharField(max_length=40, db_index=True, verbose_name="Кто заблокировал")
    blocked_id = models.CharField(max_length=40, db_index=True, verbose_name="Кого заблокировали")
    created_at = models.DateTimeField(default=timezone.now, verbose_name="Когда")

    class Meta:
        db_table = "moderation_blocks"
        unique_together = (("user_id", "blocked_id"),)
        ordering = ["-created_at"]
        verbose_name = "Блокировка"
        verbose_name_plural = "Чёрный список"

    def __str__(self):
        return f"{self.user_id} ⊘ {self.blocked_id}"


class Report(models.Model):
    """Жалоба на человека или клуб. Разбирает модератор в админке."""

    TARGET_USER = "user"
    TARGET_CLUB = "club"
    TARGETS = [(TARGET_USER, "Пользователь"), (TARGET_CLUB, "Клуб")]

    # Причины видит пользователь — списком в приложении, поэтому короткие и
    # на человеческом языке, без юридических формулировок.
    REASONS = [
        ("spam", "Спам или реклама"),
        ("abuse", "Оскорбления или угрозы"),
        ("fake", "Выдаёт себя за другого"),
        ("content", "Неприемлемое имя, фото или описание"),
        ("cheating", "Нечестная игра"),
        ("other", "Другое"),
    ]

    NEW = "new"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    STATUSES = [
        (NEW, "Новая"),
        (ACCEPTED, "Приняты меры"),
        (REJECTED, "Отклонена"),
    ]

    reporter_id = models.CharField(max_length=40, db_index=True, verbose_name="Кто пожаловался")
    target_type = models.CharField(
        max_length=10, choices=TARGETS, default=TARGET_USER, verbose_name="На кого",
    )
    target_id = models.CharField(max_length=40, db_index=True, verbose_name="ID цели")
    reason = models.CharField(max_length=20, choices=REASONS, verbose_name="Причина")
    comment = models.TextField(blank=True, default="", verbose_name="Комментарий")
    status = models.CharField(
        max_length=12, choices=STATUSES, default=NEW, db_index=True, verbose_name="Статус",
    )
    # Что модератор ответил заявителю. Апелляция (§10) без следа решения
    # невозможна: человек должен знать, что с его жалобой стало.
    resolution = models.TextField(blank=True, default="", verbose_name="Решение модератора")
    created_at = models.DateTimeField(default=timezone.now, db_index=True, verbose_name="Создана")
    resolved_at = models.DateTimeField(null=True, blank=True, verbose_name="Разобрана")

    class Meta:
        db_table = "moderation_reports"
        ordering = ["-created_at"]
        verbose_name = "Жалоба"
        verbose_name_plural = "Жалобы"

    def __str__(self):
        return f"{self.get_reason_display()} → {self.target_type}:{self.target_id}"


def blocked_ids(uid: str) -> set:
    """Кого заблокировал я."""
    return set(
        Block.objects.filter(user_id=uid).values_list("blocked_id", flat=True)
    )


def hidden_ids(uid: str) -> set:
    """С кем мы друг для друга невидимы — обе стороны блокировки.

    Односторонняя блокировка оставляла бы заблокировавшего на виду у того, от
    кого он спрятался: тот видел бы его в поиске, в подсказках и мог бы слать
    заявки. Поэтому скрываем симметрично.
    """
    rows = Block.objects.filter(Q(user_id=uid) | Q(blocked_id=uid))
    out = set()
    for b in rows:
        out.add(b.blocked_id if b.user_id == uid else b.user_id)
    return out
