from django.db import models


class AppConfig(models.Model):
    """Серверные флаги видимости приложения (D-87): что показывать в «Квартале».

    Одна строка (singleton), меняется в админке — приложение подхватывает через
    GET /v1/config без пересборки. По умолчанию периферия СКРЫТА (D-75: на старте
    только ядро, недоделанное не показываем «дверями в никуда»). Возвращаем всё
    флагом, когда готово, не собирая новый APK.
    """

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)

    show_trails = models.BooleanField(
        default=False, verbose_name="Показывать «Тропы»"
    )
    show_watch = models.BooleanField(
        default=False, verbose_name="Показывать «Часы» (Health Connect)"
    )
    show_races = models.BooleanField(
        default=False, verbose_name="Показывать «Старты» (календарь забегов)"
    )
    show_league_full = models.BooleanField(
        default=False, verbose_name="Полная «Лига» (дивизионы, все доски и периоды)"
    )
    show_sleeping_medals = models.BooleanField(
        default=False, verbose_name="Показывать «спящие» медали (без критерия)"
    )

    updated_at = models.DateTimeField(auto_now=True, verbose_name="Обновлён")

    class Meta:
        db_table = "app_config"
        verbose_name = "Флаги приложения"
        verbose_name_plural = "Флаги приложения"

    def __str__(self):
        return "Флаги приложения"

    def save(self, *args, **kwargs):
        self.id = 1  # singleton: всегда одна строка
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(id=1)
        return obj

    def to_json(self) -> dict:
        return {
            "showTrails": self.show_trails,
            "showWatch": self.show_watch,
            "showRaces": self.show_races,
            "showLeagueFull": self.show_league_full,
            "showSleepingMedals": self.show_sleeping_medals,
        }
