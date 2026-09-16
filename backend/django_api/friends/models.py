"""Дружба (D-82, этап 2a «друзья на карте»): граф взаимных друзей.

Одна строка на пару. Заявка (pending) → подтверждение делает дружбу (accepted).
Взаимность обязательна: карту друга и его позицию (этап 2b) видят только accepted.
Незнакомцы не видят ничего личного. Пара уникальна по (requester, addressee);
обратную заявку (B→A при висящей A→B) приём авто-подтверждает.
"""
import math

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


# ── Карта друзей (D-83, этап 2b/2c): позиция + приватность ────────────────────
# «Гекс» приватности: позицию огрубляем до ячейки ~160 м (на широте Якутска) и
# ХРАНИМ уже огрублённую — точной точки на сервере нет вовсе. Позицию видят только
# взаимные (accepted) друзья, и только если человек включил видимость и не в «Тени».

_DLAT = 0.0015   # ~167 м по широте
_DLNG = 0.003    # ~157 м по долготе на 62° с.ш.
HOME_RADIUS_M = 350  # у дома позицию прячем в этом радиусе


def coarsen(lat: float, lng: float):
    """Огрубить точку до центра гекс-ячейки (~160 м). Точную точку не храним."""
    clat = math.floor(lat / _DLAT) * _DLAT + _DLAT / 2
    clng = math.floor(lng / _DLNG) * _DLNG + _DLNG / 2
    return round(clat, 6), round(clng, 6)


def _haversine_m(lat1, lng1, lat2, lng2):
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


class FriendMapPrefs(models.Model):
    """Настройки приватности «друзей на карте». По умолчанию НИКТО не видит."""
    user_id = models.CharField(primary_key=True, max_length=40, verbose_name="Пользователь (ID)")
    visible = models.BooleanField(default=False, verbose_name="Показывать меня друзьям")
    # На этапе 2b — всегда гекс; 'exact' зарезервировано под «Маяк» (доверенным).
    precision = models.CharField(max_length=8, default="hex", verbose_name="Точность")
    hide_until = models.DateTimeField(null=True, blank=True, verbose_name="В «Тени» до")
    home_lat = models.FloatField(null=True, blank=True, verbose_name="Дом: широта")
    home_lng = models.FloatField(null=True, blank=True, verbose_name="Дом: долгота")
    home_hidden = models.BooleanField(default=True, verbose_name="Скрывать точку у дома")
    updated_at = models.DateTimeField(default=timezone.now, verbose_name="Обновлено")

    class Meta:
        db_table = "friend_map_prefs"
        verbose_name = "Приватность карты друзей"
        verbose_name_plural = "Приватность карты друзей"

    def in_shadow(self) -> bool:
        return bool(self.hide_until and self.hide_until > timezone.now())

    def near_home(self, lat, lng) -> bool:
        if not (self.home_hidden and self.home_lat is not None and self.home_lng is not None):
            return False
        return _haversine_m(lat, lng, self.home_lat, self.home_lng) <= HOME_RADIUS_M

    def to_json(self) -> dict:
        return {
            "visible": self.visible,
            "precision": self.precision,
            "hideUntil": self.hide_until.isoformat() if self.hide_until else None,
            "inShadow": self.in_shadow(),
            "homeSet": self.home_lat is not None and self.home_lng is not None,
            "homeHidden": self.home_hidden,
        }


class FriendPosition(models.Model):
    """Последняя ОГРУБЛЁННАЯ позиция человека для карты друзей (не сырой трек)."""
    user_id = models.CharField(primary_key=True, max_length=40, verbose_name="Пользователь (ID)")
    lat = models.FloatField(verbose_name="Широта (огрублённая)")
    lng = models.FloatField(verbose_name="Долгота (огрублённая)")
    status = models.CharField(max_length=20, blank=True, default="", verbose_name="Статус")
    updated_at = models.DateTimeField(default=timezone.now, db_index=True, verbose_name="Обновлено")

    class Meta:
        db_table = "friend_positions"
        verbose_name = "Позиция на карте друзей"
        verbose_name_plural = "Позиции на карте друзей"
