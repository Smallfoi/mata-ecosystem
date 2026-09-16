"""Дружба (D-82, этап 2a «друзья на карте»): граф взаимных друзей.

Одна строка на пару. Заявка (pending) → подтверждение делает дружбу (accepted).
Взаимность обязательна: карту друга и его позицию (этап 2b) видят только accepted.
Незнакомцы не видят ничего личного. Пара уникальна по (requester, addressee);
обратную заявку (B→A при висящей A→B) приём авто-подтверждает.
"""
from django.db import models
from django.db.models import Q
from django.utils import timezone


class Friendship(models.Model):
    PENDING = "pending"
    ACCEPTED = "accepted"
    STATUS = [(PENDING, "Заявка"), (ACCEPTED, "Друзья")]

    requester_id = models.CharField(max_length=40, db_index=True, verbose_name="Отправитель (ID)")
    addressee_id = models.CharField(max_length=40, db_index=True, verbose_name="Получатель (ID)")
    status = models.CharField(
        max_length=12, choices=STATUS, default=PENDING, db_index=True, verbose_name="Статус",
    )
    created_at = models.DateTimeField(default=timezone.now, verbose_name="Создана")
    updated_at = models.DateTimeField(default=timezone.now, verbose_name="Обновлена")

    class Meta:
        db_table = "friendships"
        unique_together = (("requester_id", "addressee_id"),)
        verbose_name = "Дружба"
        verbose_name_plural = "Дружбы"

    def __str__(self):
        return f"{self.requester_id} → {self.addressee_id} ({self.status})"


def friends_ids(uid: str) -> set:
    """ID взаимных (accepted) друзей пользователя."""
    rows = Friendship.objects.filter(status=Friendship.ACCEPTED).filter(
        Q(requester_id=uid) | Q(addressee_id=uid)
    )
    return {
        (f.addressee_id if f.requester_id == uid else f.requester_id) for f in rows
    }


def relationship(uid: str, other: str) -> str:
    """Отношение uid к other: none | outgoing | incoming | friends."""
    f = Friendship.objects.filter(
        Q(requester_id=uid, addressee_id=other)
        | Q(requester_id=other, addressee_id=uid)
    ).first()
    if not f:
        return "none"
    if f.status == Friendship.ACCEPTED:
        return "friends"
    return "outgoing" if f.requester_id == uid else "incoming"
