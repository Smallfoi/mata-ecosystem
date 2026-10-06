"""Способы доставки и итог заказа — считает сервер (D-110, по образцу Medusa).

Раньше цену доставки знал только клиент (`OrderProvider.costFor`, сайт —
`deliveryCost: 0`), а сервер сверял сумму заказа лишь как минимум: правил
доставки у него не было. Из-за этого `deliveryCost` из запроса уходил в чек как
есть. Теперь:

- способы получения ведёт владелец в админке (`ShippingOption`);
- клиент присылает только код способа (`checkoutData.deliveryType`);
- цену доставки и итог (`товары + доставка − баллы`) считает сервер, и именно они
  попадают в заказ, чек и 1С. Клиентская сумма должна совпасть с серверной —
  иначе покупатель увидел бы одну цену, а заплатил другую.
"""
from decimal import Decimal

from .money import money

# Старые клиенты и тесты не присылают способ: без адреса это самовывоз.
DEFAULT_CODE = "pickup"


class ShippingError(Exception):
    """Способ получения не подходит. 400 — не прислан/неизвестен, 409 — выключен."""

    def __init__(self, detail, status=400):
        super().__init__(detail)
        self.detail = detail
        self.status = status


def active_options():
    from .models import ShippingOption

    return list(ShippingOption.objects.filter(is_active=True))


def resolve(code):
    """Способ по коду из `checkoutData.deliveryType`. Пусто — способ по умолчанию."""
    from .models import ShippingOption

    code = str(code or "").strip() or DEFAULT_CODE
    option = ShippingOption.objects.filter(code=code).first()
    if option is None and code == DEFAULT_CODE and not ShippingOption.objects.exists():
        # Таблица пуста (база без начальных данных): прежнее поведение — самовывоз
        # бесплатно (D-92), а не отказ в любом заказе.
        return ShippingOption(code=DEFAULT_CODE, name="Самовывоз",
                              kind=ShippingOption.PICKUP, price=0)
    if option is None:
        raise ShippingError("Неизвестный способ получения заказа")
    if not option.is_active:
        raise ShippingError(f"Способ «{option.name}» сейчас недоступен — выберите другой", 409)
    return option


def cost(option, goods) -> Decimal:
    """Цена доставки для суммы товаров `goods` (Decimal, рубли)."""
    if option.free_from is not None and money(goods) >= money(option.free_from):
        return Decimal(0)
    return money(option.price)


def to_json(option, goods=None) -> dict:
    out = {
        "code": option.code,
        "name": option.name,
        "kind": option.kind,
        "zone": option.zone,
        "description": option.description,
        "price": float(money(option.price)),
        "freeFrom": float(money(option.free_from)) if option.free_from is not None else None,
        "requiresAddress": option.requires_address,
    }
    if goods is not None:
        out["cost"] = float(cost(option, goods))
    return out
