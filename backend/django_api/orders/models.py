"""Заказы Store на бэке (D-13). Храним полный payload заказа (контракт SportStore)
как JSON + несколько колонок для запросов. Заказ привязан к пользователю (Bearer)."""
from django.db import models
from django.utils import timezone

from .money import kop_to_float, to_kop


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
    # Устаревшее хранение суммы (float, рубли) — пишется и отдаётся в API как раньше.
    # Считаем по `total_kop`. Убрать float-поле — отдельный шаг (см. orders/money.py).
    total = models.FloatField(default=0, verbose_name="Сумма, ₽")
    # Сумма заказа в копейках — основное поле для расчётов (аудит B09): платёж,
    # чек, возвраты, 1С. Заполняется в save() из `total`, если его записал старый
    # путь (админка, тесты), — двойная запись держит поля согласованными.
    total_kop = models.BigIntegerField(null=True, blank=True, editable=False,
                                       verbose_name="Сумма, коп.")
    status = models.CharField(
        max_length=20, default="pending", choices=STATUS_CHOICES, verbose_name="Статус"
    )
    points_redeemed = models.IntegerField(default=0, verbose_name="Списано баллов")
    # Заказ оплачен симуляцией (без денег) — для проверки цикла. Уходит в 1С
    # с признаком «тест», чтобы там его не провели как настоящую продажу.
    is_test = models.BooleanField(default=False, db_index=True,
                                  verbose_name="Тестовый заказ")
    # Доставка по городу своими силами (D-92): курьера заказывают вручную
    # (Яндекс/inDrive) или везёт свой. Здесь — что сказать клиенту: кто везёт,
    # телефон, когда ждать. Уходит ему в уведомление вместе со статусом.
    courier_note = models.CharField(max_length=200, blank=True, default="",
                                    verbose_name="Курьер и время")
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

    # Серверный статус → словарь приложения Store (`pending | processing | shipped |
    # delivered | cancelled`). Старые сборки неизвестный статус читают как «ожидает»,
    # поэтому «оплачен» отдаём как «в обработке».
    CLIENT_STATUS = {
        "pending": "pending",
        "paid": "processing",
        "processing": "processing",
        "shipped": "shipped",
        "delivered": "delivered",
        "cancelled": "cancelled",
    }

    def save(self, *args, **kwargs):
        # Двойная запись (аудит B09): копейки всегда соответствуют рублям. Если
        # поля расходятся, значит `total` записал старый путь (админка, код до
        # копеек) — он и прав.
        kop = to_kop(self.total or 0)
        if self.total_kop != kop:
            self.total_kop = kop
            fields = kwargs.get("update_fields")
            if fields is not None and "total_kop" not in fields:
                kwargs["update_fields"] = [*fields, "total_kop"]
        super().save(*args, **kwargs)

    def set_total_kop(self, kop: int) -> None:
        """Записать сумму в копейках — и её float-зеркало для старых клиентов."""
        self.total_kop = int(kop)
        self.total = kop_to_float(kop)

    @property
    def amount_kop(self) -> int:
        """Сумма заказа в копейках — по ней считаются платёж, чек и возвраты."""
        if self.total_kop is not None:
            return int(self.total_kop)
        return to_kop(self.total or 0)

    def to_json(self) -> dict:
        """Заказ для приложения: payload (контракт SportStore, Order.fromJson) +
        актуальное состояние из колонок (аудит B08).

        payload — то, что прислали при оформлении; оплата, отмена, статусы 1С меняют
        только колонки. Поля payload не убираем (старые клиенты), а `status`
        заменяем серверным — иначе покупатель вечно видит «ожидает».
        """
        data = dict(self.payload or {})
        data.setdefault("id", self.order_id)
        client_status = self.CLIENT_STATUS.get(self.status)
        if client_status:
            data["status"] = client_status
        data.update({
            "serverId": self.pk,
            "serverStatus": self.status,
            "paymentStatus": self.payment_status,
            "onecStatus": self.onec_status,
            "onecStatusAt": self.onec_status_at.isoformat() if self.onec_status_at else None,
            "onecNumber": self.onec_number,
            "courierNote": self.courier_note,
        })
        return data


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


class ShippingOption(models.Model):
    """Способ получения заказа — по образцу ShippingOption из Medusa (D-110).

    Раньше способы и их цена жили в коде приложения и сайта (D-92), а в чек шла
    `deliveryCost`, присланная клиентом. Теперь способы ведёт владелец в админке,
    а цену доставки и итог заказа считает сервер (`orders/shipping.py`).
    `code` — то, что шлют клиенты в `checkoutData.deliveryType`; не менять у
    существующих способов, иначе старые сборки получат «способ недоступен».
    """

    PICKUP = "pickup"
    DELIVERY = "delivery"
    KIND_CHOICES = [(PICKUP, "Самовывоз"), (DELIVERY, "Доставка")]

    code = models.SlugField(max_length=40, unique=True, verbose_name="Код",
                            help_text="Как способ называют приложение и сайт (pickup, courier…). "
                                      "У существующих способов не менять.")
    name = models.CharField(max_length=80, verbose_name="Название")
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default=DELIVERY,
                            verbose_name="Тип")
    zone = models.CharField(max_length=120, blank=True, default="",
                            verbose_name="Зона", help_text="Где работает: «Якутск», «вся Россия»…")
    description = models.CharField(max_length=300, blank=True, default="",
                                   verbose_name="Пояснение покупателю",
                                   help_text="Адрес самовывоза, сроки, как связывается курьер.")
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0,
                                verbose_name="Цена, ₽")
    free_from = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True,
                                    verbose_name="Бесплатно от, ₽",
                                    help_text="Сумма товаров, с которой способ бесплатный. "
                                              "Пусто — порога нет.")
    requires_address = models.BooleanField(default=False, verbose_name="Нужен адрес")
    is_active = models.BooleanField(default=True, verbose_name="Доступен")
    sort_order = models.PositiveIntegerField(default=0, verbose_name="Порядок")

    class Meta:
        db_table = "store_shipping_options"
        ordering = ["sort_order", "id"]
        verbose_name = "Способ доставки"
        verbose_name_plural = "Способы доставки"

    def __str__(self) -> str:
        return self.name


class ReturnRequest(models.Model):
    """Заявка покупателя на возврат (D-112, по образцу return request из Medusa).

    Покупатель оформляет её сам в приложении: какие вещи, почему, как сдаёт.
    Товар он привозит в магазин МАТА сам или присылает посылкой за свой счёт
    (КС РФ 7-П от 17.02.2026: дистанционно купленное можно вернуть дистанционно).
    Решение принимаем только после осмотра в магазине: сроки, вид, ярлыки,
    упаковка, «Честный знак». Одобрили — деньги уходят существующим возвратом
    по строкам чека (`OrderReturn`, D-73). Брак подтверждён — компенсируем и
    расходы покупателя на доставку до магазина.
    """

    AWAITING, RECEIVED, APPROVED, REJECTED, CANCELED, EXPIRED = (
        "awaiting", "received", "approved", "rejected", "canceled", "expired")
    STATUS_CHOICES = [
        (AWAITING, "Ждём товар"),
        (RECEIVED, "Товар получен — на проверке"),
        (APPROVED, "Одобрена — деньги возвращаются"),
        (REJECTED, "Отказ"),
        (CANCELED, "Отменена покупателем"),
        (EXPIRED, "Истекла — товар не сдан"),
    ]
    ACTIVE = (AWAITING, RECEIVED)

    STORE, PARCEL = "store", "parcel"
    METHOD_CHOICES = [(STORE, "Принесёт в магазин"), (PARCEL, "Отправит посылкой за свой счёт")]

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="return_requests",
                              verbose_name="Заказ")
    user_id = models.CharField(max_length=40, db_index=True, verbose_name="Покупатель (ID)")
    # [{index, reason, comment}] — индексы позиций чека (receipt.allocate), как у OrderReturn.
    lines = models.JSONField(default=list, verbose_name="Вещи и причины")
    method = models.CharField(max_length=10, choices=METHOD_CHOICES, default=STORE,
                              verbose_name="Как сдаёт")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=AWAITING,
                              db_index=True, verbose_name="Статус")
    defect_claimed = models.BooleanField(default=False, verbose_name="Покупатель заявил брак")
    defect_confirmed = models.BooleanField(
        null=True, blank=True, verbose_name="Брак подтверждён осмотром",
        help_text="Да — компенсируем и расходы покупателя на доставку до магазина.")
    customer_shipping_kop = models.PositiveIntegerField(
        default=0, verbose_name="Расходы покупателя на доставку, коп.",
        help_text="По квитанции. Выплачиваются, только если брак подтверждён.")
    shipping_paid = models.BooleanField(default=False,
                                        verbose_name="Компенсация доставки выплачена")
    decision_note = models.CharField(max_length=500, blank=True, default="",
                                     verbose_name="Решение / причина отказа",
                                     help_text="Покупатель увидит этот текст. При отказе — обязательно.")
    order_return = models.OneToOneField(OrderReturn, null=True, blank=True,
                                        on_delete=models.SET_NULL, related_name="request",
                                        verbose_name="Возврат денег")
    bring_until = models.DateTimeField(verbose_name="Сдать товар до")
    created_at = models.DateTimeField(default=timezone.now, verbose_name="Создана")
    received_at = models.DateTimeField(null=True, blank=True, verbose_name="Товар получен")
    decided_at = models.DateTimeField(null=True, blank=True, verbose_name="Решение")
    decided_by = models.CharField(max_length=150, blank=True, default="",
                                  verbose_name="Кто решил")

    class Meta:
        db_table = "store_return_requests"
        ordering = ["-created_at"]
        verbose_name = "Заявка на возврат"
        verbose_name_plural = "Заявки на возврат"

    def __str__(self) -> str:
        return f"Заявка {self.number} по заказу {self.order.order_id}"

    @property
    def number(self) -> str:
        return f"В-{self.pk}"
