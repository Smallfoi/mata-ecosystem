"""Сотрудники админки и их доступ к вкладкам (S-12).

Владелец заводит сотрудника сам, выдаёт ссылку-приглашение и отмечает, какие
вкладки тот видит и может ли в них что-то менять. Пароль сотрудник задаёт себе
сам по ссылке — так пароль не проходит через чужие руки и не оседает в переписке.

Токен приглашения в базе не хранится: лежит только его отпечаток. Утечка дампа
базы не даёт войти по чужому приглашению.
"""
import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from .tabs import BY_KEY

# Уровни доступа к вкладке. Порядок важен: сравниваем по возрастанию прав.
LEVEL_NONE = "none"
LEVEL_VIEW = "view"
LEVEL_EDIT = "edit"
LEVEL_FULL = "full"

LEVELS = (
    (LEVEL_NONE, "Нет доступа"),
    (LEVEL_VIEW, "Смотреть"),
    (LEVEL_EDIT, "Редактировать"),
    (LEVEL_FULL, "Редактировать и удалять"),
)
LEVEL_RANK = {LEVEL_NONE: 0, LEVEL_VIEW: 1, LEVEL_EDIT: 2, LEVEL_FULL: 3}

INVITE_HOURS = 48


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class StaffProfile(models.Model):
    """Сотрудник админки: кто это, кто его завёл и в каком состоянии приглашение."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                related_name="staff_profile", verbose_name="Учётная запись")
    full_name = models.CharField(max_length=120, verbose_name="Имя")
    position = models.CharField(max_length=120, blank=True, default="",
                                verbose_name="Должность или зона ответственности")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+",
                                   verbose_name="Кем заведён")
    created_at = models.DateTimeField(default=timezone.now, verbose_name="Заведён")

    # Приглашение: в базе только отпечаток токена.
    invite_hash = models.CharField(max_length=64, blank=True, default="", db_index=True)
    invite_expires = models.DateTimeField(null=True, blank=True, verbose_name="Ссылка действует до")
    invite_used_at = models.DateTimeField(null=True, blank=True, verbose_name="Приглашение принято")

    class Meta:
        ordering = ["full_name"]
        verbose_name = "Сотрудник"
        verbose_name_plural = "Сотрудники"

    def __str__(self):
        return self.full_name or self.user.get_username()

    # ── Приглашение ──────────────────────────────────────────────────────────
    def issue_invite(self) -> str:
        """Выдать новую одноразовую ссылку. Возвращает токен — его видят один раз."""
        token = secrets.token_urlsafe(32)
        self.invite_hash = _hash(token)
        self.invite_expires = timezone.now() + timedelta(hours=INVITE_HOURS)
        self.invite_used_at = None
        self.save(update_fields=["invite_hash", "invite_expires", "invite_used_at"])
        return token

    def invite_is_live(self) -> bool:
        return bool(self.invite_hash) and self.invite_expires is not None \
            and self.invite_expires > timezone.now() and self.invite_used_at is None

    def accept_invite(self) -> None:
        """Погасить приглашение: повторно по той же ссылке войти нельзя."""
        self.invite_hash = ""
        self.invite_used_at = timezone.now()
        self.save(update_fields=["invite_hash", "invite_used_at"])

    @classmethod
    def by_token(cls, token: str):
        """Найти живое приглашение по токену. Сравнение по отпечатку, за постоянное время."""
        if not token or len(token) > 128:
            return None
        digest = _hash(token)
        for profile in cls.objects.filter(invite_hash__gt="", invite_used_at__isnull=True):
            if secrets.compare_digest(profile.invite_hash, digest):
                return profile if profile.invite_is_live() else None
        return None

    @property
    def status(self) -> str:
        if not self.user.is_active:
            return "off"
        if self.invite_used_at:
            return "active"
        return "invited" if self.invite_is_live() else "expired"

    @property
    def status_ru(self) -> str:
        return {
            "off": "Отключён",
            "active": "Работает",
            "invited": "Приглашён",
            "expired": "Ссылка истекла",
        }[self.status]


class TabPermission(models.Model):
    """Уровень доступа сотрудника к одной вкладке.

    Строки с уровнем «нет доступа» не храним — отсутствие записи и есть отказ.
    Так «забыли выдать» и «отобрали» выглядят одинаково: закрыто.
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="tab_permissions", verbose_name="Сотрудник")
    tab = models.CharField(max_length=48, verbose_name="Вкладка")
    level = models.CharField(max_length=8, choices=LEVELS, default=LEVEL_VIEW,
                             verbose_name="Уровень")

    class Meta:
        unique_together = [("user", "tab")]
        verbose_name = "Доступ к вкладке"
        verbose_name_plural = "Доступы к вкладкам"

    def __str__(self):
        tab = BY_KEY.get(self.tab)
        return f"{self.user}: {tab.title if tab else self.tab} — {self.get_level_display()}"


class StaffAudit(models.Model):
    """Кто, кому и что изменил в доступах. Пишется всегда, стирать нельзя из интерфейса."""

    at = models.DateTimeField(default=timezone.now, db_index=True, verbose_name="Когда")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL,
                              related_name="+", verbose_name="Кто")
    actor_name = models.CharField(max_length=150, blank=True, default="")
    target = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL,
                               related_name="+", verbose_name="Кому")
    target_name = models.CharField(max_length=150, blank=True, default="")
    action = models.CharField(max_length=160, verbose_name="Что сделано")
    ip = models.GenericIPAddressField(null=True, blank=True, verbose_name="IP")

    class Meta:
        ordering = ["-at"]
        verbose_name = "Запись журнала доступов"
        verbose_name_plural = "Журнал доступов"

    def __str__(self):
        return f"{self.at:%d.%m.%Y %H:%M} {self.actor_name}: {self.action}"

    @classmethod
    def write(cls, request, action: str, target=None) -> None:
        actor = getattr(request, "user", None)
        cls.objects.create(
            actor=actor if getattr(actor, "is_authenticated", False) else None,
            actor_name=(actor.get_username() if getattr(actor, "is_authenticated", False) else ""),
            target=target,
            target_name=(target.get_username() if target else ""),
            action=action[:160],
            ip=_client_ip(request),
        )


def _client_ip(request):
    # Раньше брали первый элемент X-Forwarded-For — его задаёт сам клиент, и в журнал
    # можно было записать любой адрес. Теперь — общий доверенный источник (аудит D03).
    from common.clientip import client_ip

    ip = client_ip(request)
    return None if ip == "unknown" else ip


class OwnerPin(models.Model):
    """Закреплённый владелец: одна строка на всю систему (S-13).

    Специально не зарегистрирована в админке: закрепление меняется только с
    сервера (`manage.py mata_owner --set <id>`) или переменной окружения
    `MATA_OWNER_ID`. Иначе «единственный владелец» переписывался бы парой кликов
    там же, где его и защищают.

    Закрепляем идентификатор записи, а не почту и не логин: их владелец меняет,
    а идентификатор — нет.
    """

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                related_name="+", verbose_name="Владелец")
    pinned_at = models.DateTimeField(default=timezone.now, verbose_name="Закреплён")
    note = models.CharField(max_length=200, blank=True, default="",
                            verbose_name="Пояснение")

    class Meta:
        verbose_name = "Закреплённый владелец"
        verbose_name_plural = "Закреплённый владелец"

    def __str__(self):
        return f"Владелец: id={self.user_id} ({self.user})"

    def save(self, *args, **kwargs):
        # Строка ровно одна: второй «владелец» — это уже не владелец.
        if not self.pk:
            OwnerPin.objects.exclude(user_id=self.user_id).delete()
        return super().save(*args, **kwargs)
