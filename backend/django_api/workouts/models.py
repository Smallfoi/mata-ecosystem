"""Тренировки, записанные не нашим приложением: часы, файлы, чужие сервисы.

Зачем отдельная таблица, а не `runs`. Забег в `runs` — это то, что записало наше
приложение: у него есть наш идентификатор, захват территорий, свой путь начисления
очков. Тренировка снаружи приходит с чужим идентификатором, может прийти дважды,
может быть удалена у источника, а человек в любой момент вправе отключить источник
и потребовать всё стереть. Смешивать это с историей собственных забегов — значит
однажды удалить лишнее.

Один и тот же выход на пробежку часто попадает сюда дважды: телефон записал забег
сам, а часы прислали ту же тренировку. Мы связываем их (`run_id`) и начисляем очки
один раз — иначе достаточно бежать с часами и телефоном, чтобы получать двойные баллы.
"""
from django.db import models
from django.utils import timezone


class ExternalWorkout(models.Model):
    SOURCES = [
        ("healthconnect", "Health Connect (Android)"),
        ("applehealth", "Apple Health"),
        ("file", "Файл GPX/TCX/FIT"),
        ("garmin", "Garmin"),
        ("suunto", "Suunto"),
        ("coros", "COROS"),
    ]

    id = models.CharField(primary_key=True, max_length=80, verbose_name="ID")
    user_id = models.CharField(max_length=40, db_index=True, verbose_name="Пользователь (ID)")
    source = models.CharField(max_length=20, choices=SOURCES, db_index=True, verbose_name="Источник")
    # Идентификатор тренировки у источника: по паре (источник, он) отличаем
    # повторную присылку от новой тренировки.
    source_id = models.CharField(max_length=120, verbose_name="ID у источника")

    started_at = models.DateTimeField(db_index=True, verbose_name="Начало")
    duration_s = models.IntegerField(default=0, verbose_name="Длительность, с")
    distance_m = models.FloatField(default=0, verbose_name="Дистанция, м")
    sport = models.CharField(max_length=30, blank=True, default="", verbose_name="Вид спорта")

    # Пульс и калории — отсюда вырастет зачёт «усилие» и режим «Форма».
    avg_hr = models.IntegerField(null=True, blank=True, verbose_name="Средний пульс")
    max_hr = models.IntegerField(null=True, blank=True, verbose_name="Максимальный пульс")
    calories = models.IntegerField(null=True, blank=True, verbose_name="Калории")

    # Наш забег, если это одно и то же событие. Тогда очки уже начислены за него.
    run_id = models.CharField(max_length=40, blank=True, default="", verbose_name="Наш забег (ID)")

    points_awarded = models.IntegerField(default=0, verbose_name="Начислено баллов")
    flagged = models.BooleanField(default=False, db_index=True, verbose_name="Помечен (чит)")
    flag_reason = models.CharField(max_length=200, blank=True, default="", verbose_name="Причина пометки")
    imported_at = models.DateTimeField(default=timezone.now, verbose_name="Импортирована")

    class Meta:
        db_table = "external_workouts"
        ordering = ["-started_at"]
        verbose_name = "Тренировка извне"
        verbose_name_plural = "Тренировки извне"
        unique_together = [("user_id", "source", "source_id")]

    @property
    def distance_km(self) -> float:
        return self.distance_m / 1000.0

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "source": self.source,
            "sourceId": self.source_id,
            "startedAtMs": int(self.started_at.timestamp() * 1000),
            "durationS": self.duration_s,
            "distanceM": round(self.distance_m),
            "sport": self.sport or None,
            "avgHr": self.avg_hr,
            "maxHr": self.max_hr,
            "calories": self.calories,
            "pointsAwarded": self.points_awarded,
            "duplicateOfRun": bool(self.run_id),
            "flagged": self.flagged,
        }


class WorkoutAward(models.Model):
    """Реестр учтённых тренировок (аудит C02): переживает отключение источника.

    `ExternalWorkout` человек вправе стереть целиком — отключил источник, данные
    ушли. Раньше вместе с ними уходила и память «за эту тренировку уже заплатили»:
    переподключил источник — те же тренировки пришли заново и принесли баллы второй
    раз. Здесь остаётся только бухгалтерский след решения: чей, сколько баллов
    и какая транзакция. Сама тренировка (время, дистанция, пульс) и её ID у
    источника не хранятся — только необратимый хэш, тот же, что `ExternalWorkout.id`.

    Запись есть на КАЖДУЮ принятую тренировку, в том числе без баллов (велосипед,
    флаг, дубль нашего забега): решение по ней уже принято и после переподключения
    не пересматривается.
    """

    # sha1("{user}:{source}:{sourceId}")[:32] — совпадает с ExternalWorkout.id.
    id = models.CharField(primary_key=True, max_length=80, verbose_name="Ключ тренировки")
    user_id = models.CharField(max_length=40, db_index=True, verbose_name="Пользователь (ID)")
    source = models.CharField(max_length=20, verbose_name="Источник")
    points = models.IntegerField(default=0, verbose_name="Начислено баллов")
    txn_id = models.CharField(max_length=40, blank=True, default="", verbose_name="Транзакция баллов")
    created_at = models.DateTimeField(default=timezone.now, verbose_name="Учтена")

    class Meta:
        db_table = "workout_awards"
        verbose_name = "Учтённая тренировка"
        verbose_name_plural = "Учтённые тренировки (реестр начислений)"
