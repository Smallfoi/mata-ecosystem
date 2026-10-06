"""Журнал обмена с 1С (D-62) и подключённые аккаунты часов.

Каждый приход каталога или цен оставляет запись: когда, что пришло, сколько
товаров добавлено и обновлено, чем закончилось. Это нужно, чтобы владелец мог
сам ответить на вопрос «выгрузка сегодня приходила?» и увидеть, где 1С прислала
мусор, — не заглядывая в логи сервера.

Неудачные попытки (нет токена, битый JSON) тоже пишем: молчащий обмен и обмен
с неверным ключом выглядят одинаково, а лечатся по-разному.
"""
from datetime import timedelta

from django.db import models
from django.utils import timezone


class OneCExchange(models.Model):
    """Одна операция обмена с 1С."""

    OPERATIONS = [
        ("categories", "Категории"),
        ("catalog", "Каталог"),
        ("prices", "Цены и остатки"),
        ("orders", "Заказы в 1С"),
        ("order-status", "Статусы из 1С"),
    ]
    STATUSES = [
        ("ok", "Успешно"),
        ("partial", "С замечаниями"),
        ("error", "Ошибка"),
    ]
    # Хранить дольше трёх месяцев смысла нет: журнал нужен для разбора «что было
    # на днях», а не как архив. Чистится при записи, раз в сутки.
    KEEP_DAYS = 90

    created_at = models.DateTimeField(default=timezone.now, db_index=True,
                                      verbose_name="Дата и время")
    operation = models.CharField(max_length=16, choices=OPERATIONS, db_index=True,
                                 verbose_name="Операция")
    status = models.CharField(max_length=16, choices=STATUSES, default="ok", db_index=True,
                              verbose_name="Статус")
    received = models.IntegerField(default=0, verbose_name="Получено позиций")
    created_count = models.IntegerField(default=0, verbose_name="Добавлено товаров")
    updated_count = models.IntegerField(default=0, verbose_name="Обновлено товаров")
    skipped = models.IntegerField(default=0, verbose_name="Пропущено")
    kept_by_owner = models.JSONField(default=list, blank=True,
                                     verbose_name="Оставлено за владельцем")
    errors = models.JSONField(default=list, blank=True, verbose_name="Замечания")
    duration_ms = models.IntegerField(default=0, verbose_name="Длительность, мс")
    detail = models.CharField(max_length=200, blank=True, default="",
                              verbose_name="Пояснение")
    # Что 1С прислала на самом деле: одна позиция как пример и имена полей, которые
    # мы не читаем. Без этого разговор «мы это присылаем» — «а мы не видим» упирается
    # в слово против слова; здесь видно пакет целиком.
    sample = models.JSONField(default=dict, blank=True, verbose_name="Пример позиции")
    unknown_keys = models.JSONField(default=list, blank=True,
                                    verbose_name="Поля, которые мы не читаем")
    fields_report = models.JSONField(default=dict, blank=True,
                                     verbose_name="Заполненность полей")

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Обмен с 1С"
        verbose_name_plural = "Журнал обмена с 1С"

    def __str__(self):
        return f"{self.get_operation_display()} — {self.get_status_display()}"

    @property
    def touched(self) -> int:
        """Сколько карточек реально затронуто — главное число строки."""
        return self.created_count + self.updated_count

    @property
    def errors_count(self) -> int:
        return len(self.errors or [])

    @classmethod
    def prune(cls) -> int:
        """Убрать записи старше KEEP_DAYS. Вызывается при записи не чаще раза в сутки."""
        edge = timezone.now() - timedelta(days=cls.KEEP_DAYS)
        return cls.objects.filter(created_at__lt=edge).delete()[0]

class WatchAccount(models.Model):
    """Подключённый аккаунт часов: чьи тренировки мы вправе забирать.

    Одна таблица на все марки: у Suunto, COROS и Garmin разные API, но одна и та
    же суть — человек разрешил доступ, у нас лежит его токен. Разводить по таблице
    на производителя значит трижды писать продление токена и отключение.

    Токен — это доступ к данным человека, поэтому: отключил источник — строка
    удаляется целиком (см. `workouts.disconnect`), а не помечается «неактивной».
    """

    SOURCES = [
        ("suunto", "Suunto"),
        ("coros", "COROS"),
        ("garmin", "Garmin"),
    ]

    user_id = models.CharField(max_length=40, db_index=True, verbose_name="Пользователь (ID)")
    source = models.CharField(max_length=20, choices=SOURCES, db_index=True, verbose_name="Источник")
    # Идентификатор человека у источника. Suunto присылает его в уведомлении о
    # тренировке (`username`) — по нему и находим, чей это аккаунт.
    external_id = models.CharField(max_length=120, db_index=True, verbose_name="ID у источника")

    access_token = models.TextField(verbose_name="Токен доступа")
    refresh_token = models.TextField(blank=True, default="", verbose_name="Токен продления")
    expires_at = models.DateTimeField(null=True, blank=True, verbose_name="Токен действует до")

    connected_at = models.DateTimeField(default=timezone.now, verbose_name="Подключён")
    last_sync_at = models.DateTimeField(null=True, blank=True, verbose_name="Последняя синхронизация")

    class Meta:
        db_table = "watch_accounts"
        ordering = ["-connected_at"]
        verbose_name = "Аккаунт часов"
        verbose_name_plural = "Аккаунты часов"
        # Один аккаунт одной марки на пользователя: повторное подключение
        # обновляет токены, а не плодит записи.
        unique_together = [("user_id", "source")]
        indexes = [models.Index(fields=["source", "external_id"])]

    def __str__(self):
        return f"{self.get_source_display()} · {self.user_id}"

    @property
    def expired(self) -> bool:
        return bool(self.expires_at and self.expires_at <= timezone.now())

class McpClient(models.Model):
    """Наше приложение, зарегистрированное у партнёра программно (RFC 7591).

    COROS не выдаёт ключи руками: сервер сам заводит приложение через их точку
    саморегистрации и получает client_id/secret. Хранить их негде, кроме как у
    себя — в Lockbox им взяться неоткуда, потому что владелец их в глаза не видит.

    Одна строка на источник: повторная регистрация означала бы новое приложение
    и отвалившиеся подключения всех людей.
    """

    source = models.CharField(max_length=20, primary_key=True, verbose_name="Источник")
    client_id = models.CharField(max_length=200, verbose_name="Client ID")
    client_secret = models.TextField(blank=True, default="", verbose_name="Client secret")
    redirect_uri = models.CharField(max_length=300, verbose_name="Адрес возврата")
    registered_at = models.DateTimeField(default=timezone.now, verbose_name="Зарегистрировано")

    class Meta:
        db_table = "mcp_clients"
        verbose_name = "Приложение у партнёра"
        verbose_name_plural = "Приложения у партнёров"

    def __str__(self):
        return f"{self.source}: {self.client_id[:12]}…"

