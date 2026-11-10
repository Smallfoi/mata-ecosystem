"""Уведомления экосистемы (ECOSYSTEM_API §2.6): единая лента для всех приложений.
Создаются на сервере (статус заказа, заявки в клуб и т.п.). FCM-пуш — поверх позже."""
from django.db import models
from django.utils import timezone


class Notification(models.Model):
    TYPE_CHOICES = [
        ("system", "Системное"),
        ("order", "Заказ"),
        ("promo", "Акция"),
        ("level", "Новый уровень"),
        ("club", "Клуб"),
    ]

    user_id = models.CharField(max_length=40, db_index=True, verbose_name="Пользователь (ID)")
    title = models.CharField(max_length=200, verbose_name="Заголовок")
    body = models.CharField(max_length=500, blank=True, default="", verbose_name="Текст")
    type = models.CharField(
        max_length=20, default="system", choices=TYPE_CHOICES, verbose_name="Тип"
    )
    order_id = models.CharField(max_length=40, null=True, blank=True, verbose_name="Заказ (ID)")
    read = models.BooleanField(default=False, verbose_name="Прочитано")
    created_at = models.DateTimeField(default=timezone.now, verbose_name="Создано")

    class Meta:
        db_table = "notifications"
        ordering = ["-created_at"]
        verbose_name = "Уведомление"
        verbose_name_plural = "Уведомления"

    def __str__(self) -> str:
        return self.title

    def to_json(self) -> dict:
        return {
            "id": str(self.pk),
            "userId": self.user_id,
            "title": self.title,
            "body": self.body,
            "type": self.type,
            "orderId": self.order_id,
            "read": self.read,
            "createdAt": self.created_at.isoformat(),
        }


class DeviceToken(models.Model):
    """Токен устройства для пушей (D-25). Регистрируется приложением; пуши шлёт
    notifications.push, когда настроен провайдер (RuStore)."""
    user_id = models.CharField(max_length=40, db_index=True, verbose_name="Пользователь (ID)")
    token = models.CharField(max_length=255, unique=True, verbose_name="Токен")
    platform = models.CharField(max_length=20, default="android", verbose_name="Платформа")
    created_at = models.DateTimeField(default=timezone.now, verbose_name="Создан")

    class Meta:
        db_table = "device_tokens"
        verbose_name = "Токен устройства"
        verbose_name_plural = "Токены устройств"


class DeviceAccount(models.Model):
    """След «с этого устройства входил такой-то аккаунт» (анти-чит, S-04).

    `DeviceToken.token` уникален: когда на телефоне входит второй аккаунт, строка
    просто переезжает к нему, и факт, что телефон общий, бесследно исчезает. Для
    модерации важен именно этот факт, поэтому ведём отдельную историю: пара
    «устройство + аккаунт», по одной записи на пару.

    Это подсказка человеку, а не приговор: телефон дают близким, аккаунт заводят
    заново после потери доступа. Храним ограниченное время — старое неинтересно
    и хранить его незачем (приватность, LAUNCH_READINESS §2).
    """
    KEEP_DAYS = 180

    token = models.CharField(max_length=255, db_index=True, verbose_name="Токен устройства")
    user_id = models.CharField(max_length=40, db_index=True, verbose_name="Пользователь (ID)")
    platform = models.CharField(max_length=20, default="android", verbose_name="Платформа")
    first_seen = models.DateTimeField(default=timezone.now, verbose_name="Впервые")
    last_seen = models.DateTimeField(default=timezone.now, verbose_name="Последний раз")

    class Meta:
        db_table = "device_accounts"
        unique_together = ("token", "user_id")
        verbose_name = "Устройство и аккаунт"
        verbose_name_plural = "Устройства и аккаунты"

    @classmethod
    def note(cls, token, user_id, platform="android"):
        """Отметить вход аккаунта с устройства. Тихо: сбой не должен ломать пуши."""
        if not token or not user_id:
            return
        try:
            cls.objects.update_or_create(
                token=token, user_id=user_id,
                defaults={"last_seen": timezone.now(), "platform": platform},
            )
            cls.prune()
        except Exception:
            pass

    @classmethod
    def prune(cls):
        """Чистим раз в сутки, а не на каждом запросе."""
        from django.core.cache import cache

        if not cache.add("device_accounts_pruned", 1, 24 * 3600):
            return
        from datetime import timedelta

        cls.objects.filter(
            last_seen__lt=timezone.now() - timedelta(days=cls.KEEP_DAYS)
        ).delete()


def create_notification(user_id, title, body="", type="system", order_id=None,
                        email_to=""):
    """Создать уведомление пользователю + (если настроено) отправить пуш.
    Безопасно (без user_id — ничего не делает).

    `email_to` — продублировать письмом (D-111): один вызов — все каналы.
    Без EMAIL_PROVIDER или без настоящего адреса письмо не уходит.
    """
    if not user_id:
        return None
    _send_email(email_to, title, body)
    n = Notification.objects.create(
        user_id=user_id, title=title, body=body, type=type, order_id=order_id,
    )
    # Пуш — фоновой задачей (D-07), чтобы не блокировать ответ на провайдере. В EAGER
    # (без брокера) выполнится синхронно. Если брокер задан, но недоступен — не роняем
    # создание уведомления: шлём синхронно запасным путём.
    from .tasks import send_push_task

    try:
        send_push_task.delay(user_id, title, body)
    except Exception:
        from .push import send_push

        send_push(user_id, title, body)  # no-op без PUSH_PROVIDER
    return n


def _send_email(to, subject, text):
    """Письмо фоновой задачей (D-111); брокер недоступен — синхронно, как пуш."""
    from .email import email_enabled, real_address

    if not email_enabled() or not real_address(to):
        return
    from .tasks import send_email_task

    try:
        send_email_task.delay(to, subject, text)
    except Exception:
        from .email import send_email

        send_email(to, subject, text)
