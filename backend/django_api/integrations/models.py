"""Журнал обмена с 1С (D-62).

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
