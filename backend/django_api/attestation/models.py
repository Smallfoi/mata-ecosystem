"""Проверка подлинности приложения (Play Integrity / App Attest) — D-129.

Одна запись = одна проверка запроса, за который начисляются баллы (сейчас —
загрузка пробежки). Режим «наблюдение»: запись — сигнал модератору, начисление
от неё не зависит. Подробности — attestation/service.py.
"""
from django.db import models
from django.utils import timezone


class IntegrityCheck(models.Model):
    STATUS_CHOICES = [
        ("pending", "Ждёт проверки"),
        ("ok", "Подлинное"),
        ("bad", "Есть признаки подделки"),
        ("error", "Не удалось проверить"),
        ("missing", "Без токена (старая сборка)"),
        ("unsupported", "Платформа пока не проверяется"),
    ]

    subject_type = models.CharField(max_length=20, default="run", verbose_name="Что проверяли")
    subject_id = models.CharField(max_length=40, db_index=True, verbose_name="ID (забега)")
    user_id = models.CharField(max_length=40, db_index=True, verbose_name="Пользователь (ID)")
    platform = models.CharField(max_length=10, blank=True, default="", verbose_name="Платформа")
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default="pending",
                              db_index=True, verbose_name="Итог")
    reasons = models.CharField(max_length=300, blank=True, default="", verbose_name="Почему")
    # Токен нужен только до разбора — после проверки стираем (он одноразовый и
    # длинный, хранить его незачем).
    token = models.TextField(blank=True, default="", verbose_name="Токен (до проверки)")
    expected_hash = models.CharField(max_length=64, blank=True, default="",
                                     verbose_name="Ожидаемый отпечаток запроса")
    device = models.CharField(max_length=200, blank=True, default="", verbose_name="Устройство")
    app = models.CharField(max_length=40, blank=True, default="", verbose_name="Приложение")
    licensing = models.CharField(max_length=40, blank=True, default="", verbose_name="Установка")
    verdict = models.JSONField(default=dict, blank=True, verbose_name="Ответ Google (без токена)")
    created_at = models.DateTimeField(default=timezone.now, db_index=True, verbose_name="Получено")
    checked_at = models.DateTimeField(null=True, blank=True, verbose_name="Проверено")

    class Meta:
        db_table = "attestation_integrity_checks"
        ordering = ["-created_at"]
        verbose_name = "Проверка подлинности"
        verbose_name_plural = "Проверки подлинности"
        constraints = [
            models.UniqueConstraint(fields=["subject_type", "subject_id"],
                                    name="attestation_one_check_per_subject"),
        ]

    def __str__(self):
        return f"{self.subject_type} {self.subject_id}: {self.get_status_display()}"
