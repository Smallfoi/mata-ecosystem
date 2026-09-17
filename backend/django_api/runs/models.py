"""История пробежек на сервере (синхронизация с устройства).
Храним СВОДКУ забега (дистанция/время/дата/флаги захвата), НЕ сырой GPS-трек —
приватность по умолчанию (LAUNCH_READINESS §2: ограничиваем хранение сырых точек;
маршрут остаётся локально на устройстве). Даёт кросс-девайс историю, бэкап при
переустановке и фундамент под серверный анти-чит (S-04)."""
from django.db import models
from django.utils import timezone


class Run(models.Model):
    # id = клиентский runId → идемпотентность (повторная отправка из офлайн-очереди
    # не задвоит забег).
    id = models.CharField(primary_key=True, max_length=40, verbose_name="ID")
    user_id = models.CharField(max_length=40, db_index=True, verbose_name="Пользователь (ID)")
    distance_m = models.FloatField(default=0, verbose_name="Дистанция, м")
    duration_s = models.IntegerField(default=0, verbose_name="Длительность, с")
    captured_territory = models.BooleanField(default=False, verbose_name="Захват территории")
    captured_zones = models.IntegerField(default=0, verbose_name="Захвачено зон")
    finished_at = models.DateTimeField(verbose_name="Завершён")
    created_at = models.DateTimeField(default=timezone.now, verbose_name="Загружен")

    # Серверный анти-чит (S-04): очки за бег считает сервер, не клиент.
    points_awarded = models.IntegerField(default=0, verbose_name="Начислено баллов")
    flagged = models.BooleanField(default=False, db_index=True, verbose_name="Помечен (чит)")
    flag_reason = models.CharField(max_length=200, blank=True, default="", verbose_name="Причина пометки")

    # Разбор помеченного забега человеком (S-04, фаза 2). Пока `reviewed_at` пуст —
    # забег висит в очереди «Проверка забегов»; решение модератора проставляет дату
    # и имя, и забег из очереди уходит (какое бы решение ни было принято).
    reviewed_at = models.DateTimeField(null=True, blank=True, verbose_name="Разобран")
    reviewed_by = models.CharField(max_length=150, blank=True, default="", verbose_name="Кто разобрал")

    class Meta:
        db_table = "runs"
        ordering = ["-finished_at"]
        verbose_name = "Пробежка"
        verbose_name_plural = "Пробежки"

    @property
    def distance_km(self) -> float:
        return self.distance_m / 1000.0

    @property
    def pending_review(self) -> bool:
        """Ждёт решения модератора: помечен и ещё не разобран."""
        return self.flagged and self.reviewed_at is None

    @property
    def speed_kmh(self) -> float:
        """Средняя скорость забега — первое, на что смотрит модератор."""
        if self.duration_s <= 0:
            return 0.0
        return self.distance_m / self.duration_s * 3.6

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "distanceMeters": self.distance_m,
            "elapsedSeconds": self.duration_s,
            "capturedTerritory": self.captured_territory,
            "capturedZones": self.captured_zones,
            "finishedAtMs": int(self.finished_at.timestamp() * 1000),
            # Анти-чит (S-04): забег помечен и баллы придержаны до разбора модератором.
            # Клиент показывает на карточке истории метку «на проверке».
            "flagged": self.flagged,
            "pendingReview": self.pending_review,
        }
