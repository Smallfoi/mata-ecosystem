from django.db import models


class Account(models.Model):
    """Пользователь экосистемы — те же поля, что в FastAPI users (контракт сохраняем)."""
    id = models.CharField(primary_key=True, max_length=40, verbose_name="ID")
    name = models.CharField(max_length=200, blank=True, default="", verbose_name="Имя")
    email = models.CharField(max_length=200, unique=True, verbose_name="Email")
    phone = models.CharField(max_length=40, null=True, blank=True, verbose_name="Телефон")
    provider = models.CharField(max_length=20, default="email", verbose_name="Способ входа")
    avatar_path = models.CharField(max_length=500, null=True, blank=True, verbose_name="Аватар")
    city = models.CharField(max_length=120, null=True, blank=True, verbose_name="Город")
    # Адреса доставки — единые для всей экосистемы (сайт/приложения). SavedAddress[] или строки.
    addresses = models.JSONField(default=list, blank=True, verbose_name="Адреса доставки")
    password_hash = models.CharField(max_length=200, null=True, blank=True, verbose_name="Хэш пароля")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата регистрации")

    # Код лояльности: постоянный 6-значный номер за клиентом (для кассы/QR). Выдаётся
    # один раз, не меняется. QR карты лояльности кодирует именно его.
    loyalty_code = models.CharField(max_length=6, blank=True, default="", db_index=True, verbose_name="Код лояльности")

    # Приватность (privacy by design, LAUNCH_READINESS §2): по умолчанию закрыто.
    profile_public = models.BooleanField(default=False, verbose_name="Профиль публичный")
    route_public = models.BooleanField(default=False, verbose_name="Маршруты публичны")
    realtime_public = models.BooleanField(default=False, verbose_name="Геопозиция в реальном времени")

    # Тестовая оплата: этому аккаунту разрешено «оплачивать» заказы без денег,
    # чтобы пройти весь путь — заказ, выгрузка в 1С, статусы. Нужно для проверки
    # обмена со стороны 1С (D-97). Такие заказы помечены как тестовые и в выгрузке,
    # и в админке — спутать их с настоящими нельзя.
    test_payment = models.BooleanField(default=False, db_index=True,
                                       verbose_name="Тестовая оплата (без денег)")

    # Модерация (S-10): бан абьюзеров. Блокирует вход (новые токены).
    is_blocked = models.BooleanField(default=False, db_index=True, verbose_name="Заблокирован")
    block_reason = models.CharField(max_length=300, blank=True, default="", verbose_name="Причина блокировки")

    # Анти-чит (S-04): авто-отметка «на ревью» при накоплении флагнутых забегов —
    # модератору сигнал присмотреться (бан не автоматический, решает человек).
    needs_review = models.BooleanField(default=False, db_index=True, verbose_name="На проверке")

    class Meta:
        db_table = "accounts"
        verbose_name = "Пользователь"
        verbose_name_plural = "Пользователи"

    def __str__(self) -> str:
        return self.name or self.phone or self.email or self.id

    def privacy_json(self) -> dict:
        return {
            "profilePublic": self.profile_public,
            "routePublic": self.route_public,
            "realtimePublic": self.realtime_public,
        }

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "phone": self.phone,
            "city": self.city,
            "provider": self.provider or "email",
            "avatarPath": self.avatar_path,
            "addresses": self.addresses or [],
            "privacy": self.privacy_json(),
        }


def ensure_loyalty_code(uid) -> str:
    """Постоянный 6-значный код лояльности за пользователем. Выдаётся ОДИН раз
    (при первом обращении к карте лояльности) и больше не меняется. Уникален."""
    import secrets

    acc = Account.objects.filter(id=uid).first()
    if not acc:
        return ""
    if acc.loyalty_code:
        return acc.loyalty_code
    for _ in range(12):
        code = "%06d" % secrets.randbelow(1_000_000)
        if not Account.objects.filter(loyalty_code=code).exists():
            acc.loyalty_code = code
            acc.save(update_fields=["loyalty_code"])
            return code
    return ""  # практически недостижимо (1M пространство)
