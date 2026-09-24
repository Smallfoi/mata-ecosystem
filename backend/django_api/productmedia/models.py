"""Модели фотопайплайна: пакет обработки и задание на один исходник.

Поток: работник грузит партию исходников (папки=артикулы) → на каждый файл заводим
PhotoJob, привязанный к товару по артикулу (Вариант А) → ИИ делает «мастер» → из него
webp → webp цепляется к карточке. Пакет (PhotoBatch) группирует одну загрузку и хранит трек.
Статусы задания видно в админке: что готово, что без товара, где ошибка (например 403 с РФ-IP).
"""
from django.conf import settings
from django.db import models

from catalog.models import Product


class PhotoBatch(models.Model):
    """Одна загрузка партии исходников. Трек общий на пакет (каталог / на модели)."""
    TRACK_CATALOG = "catalog"
    TRACK_MODEL = "model"
    TRACK_CHOICES = [
        (TRACK_CATALOG, "Каталог (товар точь-в-точь)"),
        (TRACK_MODEL, "На модели (маркетинг)"),
    ]

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="photo_batches",
        verbose_name="Кто загрузил")
    track = models.CharField("Трек", max_length=16,
                             choices=TRACK_CHOICES, default=TRACK_CATALOG)
    note = models.CharField("Заметка", max_length=200, blank=True, default="")

    class Meta:
        verbose_name = "Пакет фото"
        verbose_name_plural = "Пакеты фото"
        ordering = ["-created_at"]

    def __str__(self):
        return "Пакет #%s (%s)" % (self.pk, self.get_track_display())


class PhotoJob(models.Model):
    """Один исходник → мастер (ИИ) → webp → привязка к карточке."""
    STATUS_PENDING = "pending"
    STATUS_PROCESSING = "processing"
    STATUS_DONE = "done"
    STATUS_FAILED = "failed"
    STATUS_SKIPPED = "skipped"          # артикул папки не найден в каталоге
    STATUS_CHOICES = [
        (STATUS_PENDING, "В очереди"),
        (STATUS_PROCESSING, "Обрабатывается"),
        (STATUS_DONE, "Готово"),
        (STATUS_FAILED, "Ошибка"),
        (STATUS_SKIPPED, "Без товара"),
    ]
    ATTACH_MAIN = "main"
    ATTACH_GALLERY = "gallery"
    ATTACH_CHOICES = [
        (ATTACH_MAIN, "Главное фото"),
        (ATTACH_GALLERY, "Галерея"),
    ]

    batch = models.ForeignKey(PhotoBatch, on_delete=models.CASCADE,
                              related_name="jobs", verbose_name="Пакет")
    article = models.CharField("Артикул (папка)", max_length=64,
                               db_index=True, blank=True, default="")
    product = models.ForeignKey(Product, null=True, blank=True,
                                on_delete=models.SET_NULL,
                                related_name="photo_jobs", verbose_name="Товар")
    track = models.CharField("Трек", max_length=16, default=PhotoBatch.TRACK_CATALOG)
    attach_as = models.CharField("Куда", max_length=8,
                                 choices=ATTACH_CHOICES, default=ATTACH_MAIN)

    source = models.FileField("Исходник", upload_to="photopipeline/source/")
    master = models.FileField("Мастер (ИИ)", upload_to="photopipeline/master/", blank=True)
    webp = models.FileField("Витринный webp", upload_to="photopipeline/webp/", blank=True)

    status = models.CharField("Статус", max_length=12, choices=STATUS_CHOICES,
                              default=STATUS_PENDING, db_index=True)
    error = models.TextField("Ошибка", blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    attached_at = models.DateTimeField("Прикреплено", null=True, blank=True)

    class Meta:
        verbose_name = "Задание фото"
        verbose_name_plural = "Задания фото"
        ordering = ["-created_at"]

    def __str__(self):
        return "Фото %s [%s]" % (self.article or "—", self.get_status_display())
