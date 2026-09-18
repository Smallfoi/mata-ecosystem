from django.conf import settings
from django.db import models


class FeatureFlag(models.Model):
    """Направление приложения и его видимость (D-89): одна строка на функцию.

    Это не просто галочка «показать/скрыть», а карточка направления: что это,
    на каком этапе, что сделано и что осталось. Владелец открывает список
    направлений, проваливается в любое и видит по нему всю картину + переключатель.
    Приложение читает только `enabled` через GET /v1/config (без пересборки, D-89).
    По умолчанию всё скрыто (D-75: на старте только ядро).
    """

    STAGE_CHOICES = [
        ("not_started", "Не начато"),
        ("draft", "Черновик"),
        ("beta", "Бета — не проверено вживую"),
        ("waiting_content", "Готово технически, ждёт контент"),
        ("waiting_owner", "Ждёт решения владельца"),
        ("collapsed", "Свёрнуто до запуска"),
        ("ready", "Готово — можно включать"),
    ]

    # Ключ = суффикс для JSON: trails → showTrails, league_full → showLeagueFull.
    key = models.CharField(primary_key=True, max_length=40, verbose_name="Ключ")
    title = models.CharField(max_length=80, verbose_name="Направление")
    enabled = models.BooleanField(default=False, verbose_name="Показывать в приложении")
    stage = models.CharField(
        max_length=20, choices=STAGE_CHOICES, default="draft", verbose_name="Этап"
    )
    summary = models.TextField(blank=True, verbose_name="Что это")
    done = models.TextField(blank=True, verbose_name="Что сделано")
    todo = models.TextField(blank=True, verbose_name="Что осталось")
    order = models.IntegerField(default=0, verbose_name="Порядок")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Обновлён")

    class Meta:
        db_table = "feature_flag"
        ordering = ["order", "title"]
        verbose_name = "Направление приложения"
        verbose_name_plural = "Флаги приложения"

    def __str__(self):
        return self.title

    @property
    def config_key(self) -> str:
        """JSON-ключ для /v1/config: show + CamelCase(key)."""
        return "show" + "".join(w.capitalize() for w in self.key.split("_"))

    # Клиент ждёт именно эти ключи; дефолт — скрыто, если строка ещё не засеяна.
    DEFAULTS = {
        "showTrails": False,
        "showWatch": False,
        "showRaces": False,
        "showLeagueFull": False,
        "showSleepingMedals": False,
    }

    @classmethod
    def as_config(cls) -> dict:
        cfg = dict(cls.DEFAULTS)
        for f in cls.objects.all():
            cfg[f.config_key] = f.enabled
        return cfg


class AdminColumns(models.Model):
    """Какие столбцы сотрудник скрыл в списке админки — личная настройка.

    В «Товарах» колонок много: всё, что ведёт 1С, плюс наши поля витрины. Нужны
    они не всем и не всегда — кому-то мешает «Старая цена», кому-то размеры.
    Выбор у каждого свой и должен пережить выход из админки, поэтому хранится
    в базе, а не в сессии.
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="admin_columns", verbose_name="Сотрудник")
    model_label = models.CharField(max_length=100, verbose_name="Список")
    hidden = models.JSONField(default=list, blank=True, verbose_name="Скрытые столбцы")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Изменено")

    class Meta:
        db_table = "admin_columns"
        unique_together = ("user", "model_label")
        verbose_name = "Столбцы списка"
        verbose_name_plural = "Столбцы списков"

    def __str__(self):
        return f"{self.user_id} · {self.model_label}"
