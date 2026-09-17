"""Профиль бегуна — то, чего не хватает аккаунту для «своей лиги».

Отдельная таблица, а не поля в `accounts`: контракт аккаунта используют все три
продукта экосистемы, и трогать его ради беговых полей нельзя.

Все поля необязательные — и это принципиально. Спрашивать возраст и пол на входе
нельзя: часть людей просто закроет приложение. Не указал — попадаешь в общий
зачёт, «своя лига» тебе не показывается, всё остальное работает.

Год рождения, а не дата: для возрастной группы дата не нужна, а хранить меньше
персональных данных — лучше.
"""
from django.db import models
from django.utils import timezone


class RunnerProfile(models.Model):
    GENDER_CHOICES = [("m", "Мужской"), ("f", "Женский")]
    LEVEL_CHOICES = [
        ("novice", "Новичок"),
        ("amateur", "Любитель"),
        ("advanced", "Опытный"),
    ]
    # Ответ на вопрос «зачем ты бегаешь» при первом запуске. Под него собирается
    # главный экран: гибкость без этого вопроса превращается в кашу — пять зачётов,
    # территории, тропы и клубы разом новичок не осилит.
    FOCUS_CHOICES = [
        ("health", "Для здоровья"),
        ("compete", "Соревноваться"),
        ("social", "С людьми"),
        ("calm", "Разгрузить голову"),
        # «Пропустил» — тоже ответ: вопрос задан, повторять его не нужно.
        ("skip", "Пропустил вопрос"),
    ]

    user_id = models.CharField(primary_key=True, max_length=40, verbose_name="Пользователь (ID)")
    birth_year = models.IntegerField(null=True, blank=True, verbose_name="Год рождения")
    gender = models.CharField(
        max_length=1, blank=True, default="", choices=GENDER_CHOICES, verbose_name="Пол"
    )
    level = models.CharField(
        max_length=12, blank=True, default="", choices=LEVEL_CHOICES, verbose_name="Уровень"
    )
    weekly_goal_km = models.FloatField(null=True, blank=True, verbose_name="Цель на неделю, км")
    focus = models.CharField(
        max_length=10, blank=True, default="", choices=FOCUS_CHOICES, verbose_name="Зачем бегает"
    )
    # Участие в тропах: выключено — трек забега не уходит на сервер вовсе (D-60).
    # По умолчанию включено, иначе функция мертва; выключатель виден в настройках.
    trails_enabled = models.BooleanField(default=True, verbose_name="Участвовать в тропах")
    # Резервная копия треков на сервере (D-86): включено — трек забега хранится
    # долговременно, чтобы маршрут пережил переустановку/смену телефона. По умолчанию
    # ВЫКЛ и только по согласию (сырой GPS — ПДн, 152-ФЗ). Разворот приватности §2/D-60.
    track_backup = models.BooleanField(default=False, verbose_name="Резервная копия треков")
    updated_at = models.DateTimeField(default=timezone.now, verbose_name="Обновлён")

    class Meta:
        db_table = "runner_profile"
        verbose_name = "Профиль бегуна"
        verbose_name_plural = "Профили бегунов"

    def to_json(self) -> dict:
        return {
            "birthYear": self.birth_year,
            "gender": self.gender or None,
            "level": self.level or None,
            "focus": self.focus or None,
            "weeklyGoalKm": self.weekly_goal_km,
            "trailsEnabled": self.trails_enabled,
            "trackBackup": self.track_backup,
        }


# ── Дивизионы недели (Квартал 2.0, Ф0/Ф5) ────────────────────────────────────
#
# Дивизион — группа до 30 бегунов одного уровня (уровень = пожизненные км),
# живущая одну неделю. Формируется лениво: первый запрос бегуна на этой неделе
# кладёт его в открытую группу его уровня (или создаёт новую). По завершении
# недели топ-3 группы получают баллы — начисление ленивое и идемпотентное.


class Division(models.Model):
    """Недельная группа бегунов одного уровня."""

    id = models.CharField(primary_key=True, max_length=40)
    tier = models.IntegerField(verbose_name="Уровень (0=Асфальт … 6=Лайм)")
    week_start = models.DateField(db_index=True, verbose_name="Понедельник недели")
    seq = models.IntegerField(default=1, verbose_name="Номер группы в уровне")
    closed = models.BooleanField(default=False, verbose_name="Неделя закрыта")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "league_divisions"
        unique_together = [("tier", "week_start", "seq")]
        verbose_name = "Дивизион недели"
        verbose_name_plural = "Дивизионы недели"


class DivisionMember(models.Model):
    """Членство бегуна в дивизионе. Одна неделя — один дивизион."""

    division_id = models.CharField(max_length=40, db_index=True)
    user_id = models.CharField(max_length=40, db_index=True)
    week_start = models.DateField()
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "league_division_members"
        unique_together = [("user_id", "week_start")]
        verbose_name = "Участник дивизиона"
        verbose_name_plural = "Участники дивизионов"


# ── Сезоны района (Квартал 2.0, Ф5) ──────────────────────────────────────────
#
# Сезон = календарный месяц. Закрывается лениво при первом запросе нового
# месяца: снапшот мест месячного зачёта + баллы топ-3. Накопленное (уровень,
# медали, баллы) не отнимается — сбрасывается только таблица месяца.


class SeasonClose(models.Model):
    """Отметка «сезон закрыт» — гарантия одноразового закрытия."""

    month = models.CharField(primary_key=True, max_length=7)  # "2026-08"
    closed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "league_season_closes"
        verbose_name = "Закрытие сезона"
        verbose_name_plural = "Закрытия сезонов"


class SeasonResult(models.Model):
    """Итог бегуна в сезоне — вечная строка трофейной истории."""

    id = models.CharField(primary_key=True, max_length=64)  # sr_<month>_<uid>
    month = models.CharField(max_length=7, db_index=True)
    user_id = models.CharField(max_length=40, db_index=True)
    place = models.IntegerField()
    of = models.IntegerField()
    km = models.FloatField()
    runs = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "league_season_results"
        unique_together = [("month", "user_id")]
        verbose_name = "Итог сезона"
        verbose_name_plural = "Итоги сезонов"
