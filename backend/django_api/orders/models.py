"""Заказы Store на бэке (D-13). Храним полный payload заказа (контракт SportStore)
как JSON + несколько колонок для запросов. Заказ привязан к пользователю (Bearer)."""
from django.db import models
from django.utils import timezone


class Order(models.Model):
    STATUS_CHOICES = [
        ("pending", "Ожидает"),
        ("paid", "Оплачен"),
        ("shipped", "Отправлен"),
        ("delivered", "Доставлен"),
        ("cancelled", "Отменён"),
    ]

    user_id = models.CharField(max_length=40, db_index=True, verbose_name="Пользователь (ID)")
    order_id = models.CharField(max_length=40, verbose_name="Номер заказа")  # клиентский id (SS-xxxxx)
    total = models.FloatField(default=0, verbose_name="Сумма, ₽")
    status = models.CharField(
        max_length=20, default="pending", choices=STATUS_CHOICES, verbose_name="Статус"
    )
    points_redeemed = models.IntegerField(default=0, verbose_name="Списано баллов")
    # Оплата (каркас, D-13): none — не требуется/dev, pending — ждёт оплаты, paid — оплачен.
    payment_status = models.CharField(max_length=20, default="none", verbose_name="Оплата")
    # db_index: по этому полю ищет вебхук на каждом уведомлении провайдера.
    payment_id = models.CharField(
        max_length=80, blank=True, default="", db_index=True, verbose_name="ID платежа"
    )
    payload = models.JSONField(default=dict, verbose_name="Данные заказа (JSON)")
    created_at = models.DateTimeField(default=timezone.now, verbose_name="Создан")

    # ── Обратный поток «заказ → 1С» (D-62). 1С забирает заказы сама и подтверждает
    # приём: свой сервер 1С обычно за NAT, достучаться до него мы не можем, а без
    # подтверждения потерянная передача означала бы потерянный заказ.
    onec_taken_at = models.DateTimeField(null=True, blank=True, db_index=True,
                                         verbose_name="Забран в 1С")
    onec_number = models.CharField(max_length=64, blank=True, default="",
                                   verbose_name="Номер документа в 1С")
    # Этапы 1С: «принят» и «собран» пары в нашем `status` не имеют — это кухня
    # склада, её показываем отдельной строкой.
    ONEC_STATUS_CHOICES = [
        ("accepted", "Принят в 1С"),
        ("assembled", "Собран"),
        ("shipped", "Отгружен"),
        ("delivered", "Доставлен"),
        ("canceled", "Отменён"),
        ("cancelled", "Отменён"),
    ]
    onec_status = models.CharField(max_length=20, blank=True, default="",
                                   choices=ONEC_STATUS_CHOICES,
                                   verbose_name="Статус в 1С")
    onec_status_at = models.DateTimeField(null=True, blank=True,
                                          verbose_name="Статус обновлён")

    class Meta:
        db_table = "store_orders"
        ordering = ["-created_at"]
        # Идемпотентность: один и тот же заказ пользователя не дублируется.
        unique_together = (("user_id", "order_id"),)
        verbose_name = "Заказ"
        verbose_name_plural = "Заказы"

    def __str__(self) -> str:
        return self.order_id

    def to_json(self) -> dict:
        # payload уже в точном контракте SportStore (Order.fromJson).
        return self.payload


class OrderReturn(models.Model):
    """Возврат по заказу — целиком или частями (D-73).

    Одна запись — одно обращение в ЮKassa. По записям видно, какие вещи уже вернули:
    вторую попытку вернуть ту же вещь сервер отклонит, а сумма всех возвратов не
    превысит оплату.
    """

    STATUS_CHOICES = [
        ("pending", "В обработке"),
        ("done", "Проведён"),
        ("failed", "Не прошёл"),
    ]

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="returns",
                              verbose_name="Заказ")
    # Индексы позиций чека (receipt.allocate): единицы товара и, с последней вещью, доставка.
    lines = models.JSONField(default=list, verbose_name="Позиции чека")
    # В копейках: суммы частичных возвратов обязаны сходиться с оплатой до копейки.
    amount_kop = models.PositiveIntegerField(verbose_name="Сумма, коп.")
    points_returned = models.IntegerField(default=0, verbose_name="Возвращено баллов")
    points_revoked = models.IntegerField(default=0, verbose_name="Снято начисленных баллов")
    refund_id = models.CharField(max_length=80, blank=True, default="",
                                 verbose_name="ID возврата в ЮKassa")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="pending",
                              verbose_name="Статус")
    error = models.CharField(max_length=300, blank=True, default="", verbose_name="Ошибка")
    created_by = models.CharField(max_length=150, blank=True, default="",
                                  verbose_name="Кто оформил")
    created_at = models.DateTimeField(default=timezone.now, verbose_name="Когда")

    class Meta:
        db_table = "store_order_returns"
        ordering = ["-created_at"]
        verbose_name = "Возврат"
        verbose_name_plural = "Возвраты"

    def __str__(self) -> str:
        return f"{self.order.order_id}: {self.amount_kop / 100:.2f} ₽"
