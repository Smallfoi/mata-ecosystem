"""Сумма заказа в копейках (аудит B09).

Безопасно для прода: поле добавляется пустым (NULL), затем заполняется из
текущего float `total` с округлением ROUND_HALF_UP. Ни данные, ни старое поле
не трогаются; неразбираемое значение (не бывает, но всё же) оставляет NULL —
модель досчитает копейки из `total` на лету (`Order.amount_kop`).
"""
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.db import migrations, models

_BATCH = 500


def _kop(total):
    try:
        value = Decimal(str(total if total is not None else 0))
        if not value.is_finite():
            return None
        return int(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) * 100)
    except (InvalidOperation, ValueError):
        return None


def fill(apps, schema_editor):
    Order = apps.get_model("orders", "Order")
    batch = []
    for order in Order.objects.filter(total_kop__isnull=True).only("pk", "total").iterator():
        kop = _kop(order.total)
        if kop is None:
            continue
        order.total_kop = kop
        batch.append(order)
        if len(batch) >= _BATCH:
            Order.objects.bulk_update(batch, ["total_kop"])
            batch = []
    if batch:
        Order.objects.bulk_update(batch, ["total_kop"])


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0008_order_is_test"),
    ]

    operations = [
        migrations.AddField(
            model_name="order",
            name="total_kop",
            field=models.BigIntegerField(blank=True, editable=False, null=True,
                                         verbose_name="Сумма, коп."),
        ),
        migrations.RunPython(fill, migrations.RunPython.noop),
    ]
