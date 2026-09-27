"""Серверная сверка корзины: строки заказа по каталогу и порог суммы (D-37, аудит B09, F03).

Клиент присылает позиции и `total` сам. Раньше сервер сверял только сумму, а
строки принимал на веру: цена и название из корзины уходили в чек и в 1С, не
проверялись ни наличие, ни размер, ни количество. Теперь при приёме заказа
сервер собирает СНИМОК строк по каталогу:

- товар существует и продаётся — опубликован и не снят с продажи в 1С
  (то же правило, что у витрины: `catalog.views._visible_products`);
- есть в наличии — по тому же правилу, что витрина (`catalog.models_api._in_stock`),
  а количество не больше остатка (одинаковые позиции в разных строках складываются);
- размер и цвет есть у позиции, если каталог их знает;
- количество — целое, от 1 до `MAX_LINE_QTY`, всего не больше `MAX_ORDER_UNITS`;
- цена и название строки — из каталога. Именно снимок сохраняется в заказ, и
  по нему строятся чек (`receipt.py`), возвраты и выгрузка в 1С — все видят
  одни и те же строки.

Сумма (`total`) по-прежнему сверяется как МИНИМУМ, а не равенство: доставку
считает клиент, правил доставки у бэкенда пока нет. Занизить сумму нельзя,
завысить (старая цена в корзине) — проблема покупателя, а не магазина.

Деньги в новом коде считаются в Decimal с точностью до копейки. Поля заказа и
товара пока FloatField — перевод хранения на копейки отдельной миграцией (см. PR).

Совместимость со старыми клиентами:
- сайт шлёт позиции без размера и цвета — не проверяем то, чего не прислали;
- у позиции без размеров/цветов в каталоге (1С не заполнила строку) размер
  клиента сверить не с чем — принимаем, как раньше;
- нет `quantity` — 1 шт, как раньше; «2» строкой — 2;
- товар не из каталога при ВЫКЛЮЧЕННОЙ оплате заказ не блокирует (dev, демо-
  каталог старых сборок); при включённой — отказ: сверить сумму не с чем.
"""
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

# Разумный предел строки: розница, не опт.
MAX_LINE_QTY = 50
# Чек: каждая единица товара — своя позиция, у кассы предел 100 позиций, одна —
# доставка (receipt.allocate). Больше в один заказ не поместится.
MAX_ORDER_UNITS = 99

# Списанные баллы уменьшают сумму: 1 балл = 1 ₽ (правила лояльности, Часть 11.5).
_POINT_RUB = Decimal(1)
# Допуск на округление копеек при пересчёте на клиенте.
_EPSILON = Decimal(1)
_KOP = Decimal("0.01")

# Что нужно от товара для сверки — одна выборка на весь заказ (F03).
_FIELDS = ("id", "name", "display_name", "display_name_override", "price", "sizes",
           "colors", "in_stock", "stock_count", "stock_by_size", "is_published",
           "is_active_1c")

UNVERIFIABLE = "Не удалось сверить заказ с каталогом"


class CartError(Exception):
    """Позиция корзины не проходит сверку. `status`: 400 — запрос некорректен,
    409 — каталог изменился (снят с продажи, нет в наличии, нет размера)."""

    def __init__(self, detail, status=400, index=None, product_id=""):
        super().__init__(detail)
        self.detail = detail
        self.status = status
        self.index = index
        self.product_id = product_id

    def body(self) -> dict:
        out = {"detail": self.detail}
        if self.index is not None:
            out["itemIndex"] = self.index
        if self.product_id:
            out["productId"] = self.product_id
        return out


def money(value) -> Decimal:
    """Рубли → Decimal с копейками. Через str: float 0.1 не превращается в 0.1000…055.
    Не число — ValueError."""
    if isinstance(value, bool):
        raise ValueError(f"не число: {value!r}")
    try:
        amount = Decimal(str(value if value not in (None, "") else 0))
    except (InvalidOperation, ValueError):
        raise ValueError(f"не число: {value!r}") from None
    if not amount.is_finite():
        raise ValueError(f"не число: {value!r}")
    return amount.quantize(_KOP, rounding=ROUND_HALF_UP)


def parse_quantity(raw, index=None, product_id="") -> int:
    """Количество строки: целое от 1 до MAX_LINE_QTY. Нет поля — 1 шт (старые клиенты)."""
    bad = CartError("Количество товара должно быть целым числом", 400, index, product_id)
    if raw is None or raw == "":
        return 1
    if isinstance(raw, bool):
        raise bad
    if isinstance(raw, int):
        qty = raw
    elif isinstance(raw, float):
        if not raw.is_integer():
            raise bad
        qty = int(raw)
    elif isinstance(raw, str) and raw.strip().lstrip("-").isdigit():
        qty = int(raw.strip())
    else:
        raise bad
    if not 1 <= qty <= MAX_LINE_QTY:
        raise CartError(f"Количество товара — от 1 до {MAX_LINE_QTY} шт",
                        400, index, product_id)
    return qty


def _norm(text) -> str:
    return str(text or "").strip().upper().replace("Ё", "Е")


def _pick(value, options):
    """Значение клиента в написании каталога; None — такого у позиции нет.
    Пустое у клиента или пустой список в каталоге — сверять нечего: ""."""
    options = [str(o).strip() for o in (options or []) if str(o).strip()]
    wanted = _norm(value)
    if not wanted or not options:
        return ""
    for option in options:
        if _norm(option) == wanted:
            return option
    return None


def _left(product, size):
    """Сколько штук можно продать; None — остаток не ведётся (как у витрины)."""
    by_size = product.stock_by_size or {}
    if size and by_size:
        try:
            return int(by_size.get(str(size), 0) or 0)
        except (TypeError, ValueError):
            return 0
    return product.stock_count


class Cart:
    """Итог сверки: строки для сохранения и сумма товаров по каталогу."""

    def __init__(self, items, goods, known, unknown):
        self.items = items        # снимок строк (dict), в исходном порядке
        self.goods = goods        # Decimal: сумма сверенных с каталогом строк
        self.known = known        # сколько строк сверено с каталогом
        self.unknown = unknown    # сколько строк каталогу неизвестно

    @property
    def verified(self) -> bool:
        """Все строки сверены — сумма товаров достоверна целиком."""
        return self.known > 0 and self.unknown == 0


def normalize_items(items, strict: bool) -> Cart:
    """Снимок строк заказа по каталогу (одна выборка из БД на весь заказ).

    `strict` — оплата включена: строка не из каталога = отказ (сверить сумму не с
    чем), пустая корзина — тоже. Иначе такая строка сохраняется как прислана.
    Бросает CartError с понятным текстом.
    """
    from catalog.models import Product
    from catalog.models_api import _in_stock

    if items is None:
        items = []
    if not isinstance(items, list):
        raise CartError("Позиции заказа должны быть списком")
    if strict and not items:
        raise CartError(UNVERIFIABLE)

    parsed = []
    for i, raw in enumerate(items):
        if not isinstance(raw, dict):
            raise CartError("Некорректная позиция заказа", 400, i)
        pid = str(raw.get("productId") or "").strip()
        qty = parse_quantity(raw.get("quantity"), i, pid)
        if strict and not pid:
            raise CartError(UNVERIFIABLE, 400, i)
        parsed.append((i, raw, pid, qty))

    if sum(qty for _, _, _, qty in parsed) > MAX_ORDER_UNITS:
        raise CartError(f"В одном заказе — не больше {MAX_ORDER_UNITS} товаров")

    ids = {pid for _, _, pid, _ in parsed if pid}
    products = (
        {p.pk: p for p in Product.objects.filter(pk__in=ids).only(*_FIELDS)} if ids else {}
    )

    out, goods, known, unknown = [], Decimal(0), 0, 0
    taken = {}  # (товар, размер) → сколько штук уже в заказе
    for i, raw, pid, qty in parsed:
        product = products.get(pid)
        line = dict(raw)
        line["quantity"] = qty
        if product is None:
            if strict:
                raise CartError(UNVERIFIABLE, 400, i, pid)
            unknown += 1
            out.append(line)
            continue

        title = product.shop_title
        if not (product.is_published and product.is_active_1c):
            raise CartError(f"«{title}» снят с продажи — уберите его из корзины",
                            409, i, pid)
        size = _pick(raw.get("size"), product.sizes)
        if size is None:
            raise CartError(f"У «{title}» нет размера {str(raw.get('size')).strip()} — "
                            "выберите размер заново", 409, i, pid)
        if _pick(raw.get("color"), product.colors) is None:
            raise CartError(f"У «{title}» нет цвета {str(raw.get('color')).strip()} — "
                            "выберите цвет заново", 409, i, pid)
        if not size:
            # Позиция одного размера (так 1С и ведёт склад): остаток — по нему.
            sizes = [str(s).strip() for s in (product.sizes or []) if str(s).strip()]
            size = sizes[0] if len(sizes) == 1 else ""
        label = f"«{title}»" + (f" (размер {size})" if size else "")
        if not _in_stock(product, size):
            raise CartError(f"{label} нет в наличии", 409, i, pid)
        taken[(pid, size)] = taken.get((pid, size), 0) + qty
        left = _left(product, size)
        if left is not None and taken[(pid, size)] > left:
            raise CartError(f"{label}: в наличии только {max(0, left)} шт", 409, i, pid)
        price = money(product.price)
        if price <= 0:
            raise CartError(f"{label} сейчас нельзя купить", 409, i, pid)

        line["productId"] = pid
        line["price"] = float(price)
        line["productName"] = title or str(raw.get("productName") or "")
        goods += price * qty
        known += 1
        out.append(line)
    return Cart(out, goods, known, unknown)


def redeemed_rub(user_id, order_id) -> Decimal:
    """Сколько баллов РЕАЛЬНО списано за этот заказ — по реестру, а не по словам клиента."""
    from loyalty.models import LoyaltyTransaction

    txn = LoyaltyTransaction.objects.filter(
        user_id=user_id, order_id=order_id, source="redeem"
    ).first()
    return abs(Decimal(txn.amount)) * _POINT_RUB if txn else Decimal(0)


def minimum_for(cart: Cart, user_id, order_id):
    """Минимально допустимая сумма заказа или None, если сверить не с чем.

    None — ни одной строки из каталога (товар не из каталога при выключенной
    оплате): проверять нечего, заказ не блокируем.
    """
    if not cart.known:
        return None
    return max(Decimal(0), cart.goods - redeemed_rub(user_id, order_id))


def minimum_total(items, user_id, order_id):
    """Порог суммы по сырым позициям, без отказов за наличие (одна выборка, F03)."""
    from catalog.models import Product

    parsed = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        pid = str(it.get("productId") or "").strip()
        if not pid:
            continue
        try:
            qty = max(1, int(it.get("quantity") or 1))
        except (TypeError, ValueError):
            qty = 1
        parsed.append((pid, qty))
    prices = dict(
        Product.objects.filter(pk__in={pid for pid, _ in parsed}).values_list("pk", "price")
    ) if parsed else {}
    known = [(money(prices[pid]), qty) for pid, qty in parsed if pid in prices]
    if not known:
        return None
    goods = sum((price * qty for price, qty in known), Decimal(0))
    return max(Decimal(0), goods - redeemed_rub(user_id, order_id))


def total_is_acceptable(total, cart: Cart, user_id, order_id) -> bool:
    """Не занижена ли присланная клиентом сумма относительно каталога."""
    minimum = minimum_for(cart, user_id, order_id)
    if minimum is None:
        return True
    return money(total) >= minimum - _EPSILON
