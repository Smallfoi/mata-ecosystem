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
    # Рекламное или служебное (LAUNCH_READINESS §6). Канал у нас один — лента и пуши,
    # поэтому различие держится на этом признаке, а не на канале: по закону рекламу
    # нельзя мешать с обязательными сервисными сообщениями, и на неё нужно согласие.
    promotional = models.BooleanField(default=False, db_index=True, verbose_name="Рекламное")
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
            "promotional": self.promotional,
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


def is_promotional(type, promotional=None) -> bool:
    """Рекламное ли это уведомление.

    Явный флаг главнее. Если его не передали, считаем рекламным тип «Акция»: самая
    вероятная ошибка — отправить акцию и забыть про флаг, и ошибаться надо в сторону
    «спросили согласие», а не в сторону «разослали рекламу без согласия».
    """
    if promotional is not None:
        return bool(promotional)
    return type == "promo"


def create_notification(user_id, title, body="", type="system", order_id=None,
                        email_to="", promotional=None):
    """Создать уведомление пользователю + (если настроено) отправить пуш.
    Безопасно (без user_id — ничего не делает).

    `email_to` — продублировать письмом (D-111): один вызов — все каналы.
    Без EMAIL_PROVIDER или без настоящего адреса письмо не уходит.

    `promotional` — рекламное сообщение (LAUNCH_READINESS §6). Без действующего
    согласия на рекламу такое уведомление НЕ создаётся и ни в один канал не уходит;
    функция возвращает None. Служебные уведомления согласия не требуют никогда:
    статус заказа и ответ модератора человек должен получить независимо от того,
    отписался он от рекламы или нет.
    """
    if not user_id:
        return None
    ad = is_promotional(type, promotional)
    if ad and not _marketing_allowed(user_id):
        return None
    # Письмо и пуш — ПОСЛЕ проверки согласия: иначе реклама ушла бы в другой канал,
    # не оставив следа в ленте.
    _send_email(email_to, title, body)
    n = Notification.objects.create(
        user_id=user_id, title=title, body=body, type=type, order_id=order_id,
        promotional=ad,
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


def _marketing_allowed(user_id) -> bool:
    """Есть ли согласие на рекламу. Импорт внутри — `legal` зависит от аккаунтов."""
    from legal.models import has_marketing_consent

    return has_marketing_consent(user_id)


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
