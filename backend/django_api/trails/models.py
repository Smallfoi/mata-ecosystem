"""Тропы: участки маршрута, по которым бегают регулярно.

Территория даёт повод бежать КУДА-ТО, тропа — повод бежать СНОВА. Это разные
типы привычки, и вместе они закрывают и исследование, и рутину.

Про хранение (решение D-60). Сервер по-прежнему не держит карту передвижений
людей: телефон присылает прореженный трек, сервер сверяет его с тропами района,
сохраняет РЕЗУЛЬТАТЫ попыток, а сам трек удаляет через 30 дней (было 14; решение
владельца 28.09.2026) — это окно нужно,
чтобы разобрать жалобу на накрутку. Выключил участие в тропах — трек не уходит
вовсе.

Геометрия тропы лежит списком точек в JSON, а не в PostGIS. PostGIS у нас стоит
и держит территории, но там нужны операции над площадями (объединение, разность),
а здесь — «прошёл ли трек по этой линии»: это несколько сравнений расстояний,
которые честнее и понятнее считать явно. Для поиска троп рядом храним рамку
(bbox) обычными числами — по ней и фильтруем в базе.
"""
from django.db import models
from django.utils import timezone


class Trail(models.Model):
    id = models.CharField(primary_key=True, max_length=40, verbose_name="ID")
    name = models.CharField(max_length=120, verbose_name="Название")
    city = models.CharField(max_length=120, blank=True, default="", verbose_name="Город")
    # Точки линии: [[lat, lon], ...] — уже прорежённые, десятки точек, не тысячи.
    points = models.JSONField(default=list, verbose_name="Точки линии")
    length_m = models.FloatField(default=0, verbose_name="Длина, м")

    # Рамка для быстрого отбора «тропы рядом» без геоиндекса.
    min_lat = models.FloatField(default=0, db_index=True, verbose_name="Рамка: мин. широта")
    max_lat = models.FloatField(default=0, verbose_name="Рамка: макс. широта")
    min_lon = models.FloatField(default=0, db_index=True, verbose_name="Рамка: мин. долгота")
    max_lon = models.FloatField(default=0, verbose_name="Рамка: макс. долгота")

    created_by = models.CharField(
        max_length=40, blank=True, default="", db_index=True, verbose_name="Создал (ID)"
    )
    is_public = models.BooleanField(default=True, verbose_name="Видна всем")
    created_at = models.DateTimeField(default=timezone.now, verbose_name="Создана")

    class Meta:
        db_table = "trails"
        ordering = ["name"]
        verbose_name = "Тропа"
        verbose_name_plural = "Тропы"

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "city": self.city or None,
            "lengthM": round(self.length_m),
            "points": self.points,
            "createdByMe": False,   # проставляет представление, оно знает пользователя
        }


class TrailAttempt(models.Model):
    """Одно прохождение тропы. Время считается по входу и выходу, а не по всему забегу."""

    id = models.CharField(primary_key=True, max_length=64, verbose_name="ID")
    trail_id = models.CharField(max_length=40, db_index=True, verbose_name="Тропа (ID)")
    user_id = models.CharField(max_length=40, db_index=True, verbose_name="Пользователь (ID)")
    run_id = models.CharField(max_length=40, db_index=True, verbose_name="Забег (ID)")

    started_at = models.DateTimeField(verbose_name="Начало прохождения")
    duration_s = models.IntegerField(default=0, verbose_name="Время, с")
    created_at = models.DateTimeField(default=timezone.now, verbose_name="Записана")

    class Meta:
        db_table = "trail_attempts"
        ordering = ["duration_s"]
        verbose_name = "Попытка на тропе"
        verbose_name_plural = "Попытки на тропах"
        # Один забег не может дать две попытки на одной тропе: иначе круговой
        # маршрут превратится в накрутку сам собой.
        unique_together = [("trail_id", "run_id")]

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "trailId": self.trail_id,
            "runId": self.run_id,
            "startedAtMs": int(self.started_at.timestamp() * 1000),
            "durationS": self.duration_s,
        }


class PendingTrack(models.Model):
    """Трек забега — временно, только чтобы сверить его с тропами и разобрать споры.

    Живёт 30 дней (D-60; с 28.09.2026 — 30 вместо 14), потом удаляется задачей по расписанию. Это единственное
    место, где на сервере вообще появляется маршрут человека.
    """

    run_id = models.CharField(primary_key=True, max_length=40, verbose_name="Забег (ID)")
    user_id = models.CharField(max_length=40, db_index=True, verbose_name="Пользователь (ID)")
    points = models.JSONField(default=list, verbose_name="Точки трека")
    received_at = models.DateTimeField(default=timezone.now, db_index=True, verbose_name="Получен")

    class Meta:
        db_table = "pending_tracks"
        verbose_name = "Трек на проверке"
        verbose_name_plural = "Треки на проверке"
