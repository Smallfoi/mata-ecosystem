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
    STATUS_REVIEW = "review"            # ИИ отработал, ждёт решения человека
    STATUS_DONE = "done"                # принято и выложено на витрину
    STATUS_REJECTED = "rejected"        # брак: не выкладываем
    STATUS_FAILED = "failed"
    STATUS_SKIPPED = "skipped"          # артикул папки не найден в каталоге
    STATUS_CHOICES = [
        (STATUS_PENDING, "В очереди"),
        (STATUS_PROCESSING, "Генерируется"),
        (STATUS_REVIEW, "На проверке"),
        (STATUS_DONE, "На витрине"),
        (STATUS_REJECTED, "Отклонено"),
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
    # Текст принта словами, если известен: модель рисует надпись точнее (prompts.with_text).
    text = models.CharField("Текст принта", max_length=300, blank=True, default="")
    # Последнее замечание проверяющего: при «Переделать» уходит в промт следующей попытки.
    note = models.TextField("Замечание", blank=True, default="")
    attempts = models.PositiveSmallIntegerField("Попыток генерации", default=0)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="photo_reviews", verbose_name="Проверил")
    reviewed_at = models.DateTimeField("Проверено", null=True, blank=True)
    # Какой версией промта сделан последний результат (None — встроенный промт из кода).
    prompt = models.ForeignKey("PhotoPrompt", null=True, blank=True, on_delete=models.SET_NULL,
                               related_name="jobs", verbose_name="Версия промта")
    # Расход токенов последней генерации (как отдал OpenAI) — основа учёта стоимости.
    usage = models.JSONField("Расход токенов", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    attached_at = models.DateTimeField("Прикреплено", null=True, blank=True)

    class Meta:
        verbose_name = "Задание фото"
        verbose_name_plural = "Задания фото"
        ordering = ["-created_at"]

    def __str__(self):
        return "Фото %s [%s]" % (self.article or "—", self.get_status_display())


class PhotoDetail(models.Model):
    """Крупный план принта/бирки для артикула в партии.

    Не превращается в отдельный снимок витрины: прикладывается к запросу каждого снимка
    этого артикула как справочная картинка, чтобы мелкий текст модель срисовала, а не
    придумала (живой прогон 27.09: мелкое солнце на груди → выдуманное «SUN CARE»).
    """
    batch = models.ForeignKey(PhotoBatch, on_delete=models.CASCADE, related_name="details",
                              verbose_name="Пакет")
    article = models.CharField("Артикул (папка)", max_length=64, db_index=True)
    image = models.FileField("Крупный план", upload_to="photopipeline/detail/")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Крупный план принта"
        verbose_name_plural = "Крупные планы принтов"
        ordering = ["created_at"]

    def __str__(self):
        return "Крупный план %s" % self.article


class PhotoPrompt(models.Model):
    """Версия промта трека. Действует последняя по времени; старые — история для возврата.

    Правит владелец на странице «Промты» без выкладки кода. Нет ни одной версии — работает
    встроенный промт из prompts.py.
    """
    track = models.CharField("Трек", max_length=16, choices=PhotoBatch.TRACK_CHOICES,
                             db_index=True)
    text = models.TextField("Текст промта")
    comment = models.CharField("Что поменяли", max_length=200, blank=True, default="")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="photo_prompts",
                                   verbose_name="Автор")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Версия промта"
        verbose_name_plural = "Версии промтов"
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return "Промт %s v%s" % (self.track, self.pk)

    @classmethod
    def active(cls, track):
        """Действующая версия трека или None (тогда — встроенный промт)."""
        return cls.objects.filter(track=track).order_by("-created_at", "-id").first()
