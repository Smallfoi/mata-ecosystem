"""Продуктовая аналитика (D-30): единый поток СОБЫТИЙ по всей экосистеме МАТА.

Один аккаунт (SSO) → одна лента событий из всех продуктов (Квартал/Store/Сайт).
Пишется и сервером (`track(...)` в ключевых местах: регистрация/забег/покупка/захват),
и клиентами (`POST /v1/events` — экраны, клики). Пропсы — свободный JSON.

Событие — факт, а не деньги: сбой записи НЕ должен ломать основной поток (см. `track`).
Ретеншн/когорты считаются поверх событий и существующих сигналов — см. `analytics.retention`.
"""
from django.db import models
from django.utils import timezone

# Канонические имена серверных событий — единый словарь, чтобы не плодить опечатки строк.
E_REGISTER = "account_registered"
E_LOGIN = "account_login"
E_RUN_FINISHED = "run_finished"
E_PURCHASE = "purchase"
E_TERRITORY_CAPTURED = "territory_captured"


class Event(models.Model):
    """Одно событие аналитики. user_id — общий ID экосистемы (может быть пустым для
    анонимных клиентских событий). source — откуда пришло (kvartal/store/site/server)."""

    id = models.BigAutoField(primary_key=True, verbose_name="ID")
    user_id = models.CharField(
        max_length=40, db_index=True, blank=True, default="", verbose_name="Пользователь (ID)"
    )
    name = models.CharField(max_length=60, db_index=True, verbose_name="Событие")
    source = models.CharField(max_length=20, blank=True, default="server", verbose_name="Источник")
    props = models.JSONField(default=dict, blank=True, verbose_name="Свойства")
    created_at = models.DateTimeField(
        default=timezone.now, db_index=True, verbose_name="Время"
    )

    class Meta:
        db_table = "analytics_events"
        verbose_name = "Событие"
        verbose_name_plural = "Аналитика (события)"
        indexes = [models.Index(fields=["name", "created_at"])]

    def to_json(self) -> dict:
        return {
            "name": self.name,
            "source": self.source,
            "props": self.props or {},
            "createdAt": self.created_at.isoformat(),
        }


# Разрешённые источники клиентских событий (POST /v1/events). server — только внутренне.
CLIENT_SOURCES = {"kvartal", "store", "site"}


def track(name, user_id="", source="server", **props):
    """Записать событие. БЕЗОПАСНО: аналитика не критична — любой сбой глотаем, чтобы
    не ломать основной поток (начисления/заказы/захваты). Пустое имя игнорируем."""
    if not name:
        return None
    try:
        return Event.objects.create(
            user_id=user_id or "",
            name=str(name)[:60],
            source=(source or "server")[:20],
            props=props or {},
        )
    except Exception:
        return None


class SaleLine(models.Model):
    """Строка продажи для статистики — БЕЗ связи с человеком (решение владельца 28.09.2026).

    Что купили, какой размер, цвет, сколько, по какой цене, когда. Кто купил — не
    хранится: ни id аккаунта, ни имени, ни адреса. Пишется при оплате заказа
    (`analytics.sales.record`) и живёт отдельно от заказа: когда человек удаляет
    аккаунт, его заказы удаляются полностью, а статистика продаж остаётся.
    `order_pk` — только чтобы не записать строку дважды; после удаления заказа он
    ни на что не указывает.
    """

    order_pk = models.BigIntegerField(db_index=True, verbose_name="Заказ (служебно)")
    line = models.PositiveIntegerField(verbose_name="Строка")
    sold_at = models.DateTimeField(db_index=True, verbose_name="Продано")
    product_id = models.CharField(max_length=80, blank=True, default="", verbose_name="Товар (ID)")
    article = models.CharField(max_length=80, blank=True, default="", verbose_name="Артикул")
    model_key = models.CharField(max_length=200, blank=True, default="", verbose_name="Модель")
    name = models.CharField(max_length=300, blank=True, default="", verbose_name="Название")
    brand = models.CharField(max_length=120, blank=True, default="", verbose_name="Бренд")
    category_id = models.CharField(max_length=80, blank=True, default="", verbose_name="Категория")
    size = models.CharField(max_length=40, blank=True, default="", verbose_name="Размер")
    color = models.CharField(max_length=80, blank=True, default="", verbose_name="Цвет")
    quantity = models.PositiveIntegerField(default=1, verbose_name="Количество")
    price = models.FloatField(default=0, verbose_name="Цена, ₽")
    refunded = models.BooleanField(default=False, verbose_name="Возвращено")

    class Meta:
        db_table = "analytics_sale_lines"
        verbose_name = "Продажа (статистика)"
        verbose_name_plural = "Продажи (статистика, без покупателя)"
        constraints = [models.UniqueConstraint(fields=["order_pk", "line"],
                                               name="sale_line_once")]
