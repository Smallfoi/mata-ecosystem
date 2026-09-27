"""Перенести уже оплаченные заказы в статистику продаж (без покупателя).

Дальше строки пишутся при оплате сигналом; здесь — всё, что оплатили до этого.
Ошибка на одном заказе не валит миграцию (миграции гоняются при старте web).
"""
from django.db import migrations, transaction

SOLD = ("paid", "partially_refunded", "refunded")


def backfill(apps, schema_editor):
    Order = apps.get_model("orders", "Order")
    Product = apps.get_model("catalog", "Product")
    SaleLine = apps.get_model("analytics", "SaleLine")
    for order in Order.objects.filter(payment_status__in=SOLD, is_test=False).iterator():
        try:
            if SaleLine.objects.filter(order_pk=order.pk).exists():
                continue
            items = [i for i in ((order.payload or {}).get("items") or []) if isinstance(i, dict)]
            ids = {str(i.get("productId") or "") for i in items} - {""}
            products = {p.id: p for p in Product.objects.filter(id__in=ids)}
            rows = []
            for n, item in enumerate(items):
                pid = str(item.get("productId") or "")
                p = products.get(pid)
                try:
                    qty = max(1, int(item.get("quantity") or 1))
                except (TypeError, ValueError):
                    qty = 1
                try:
                    price = float(item.get("price") or 0)
                except (TypeError, ValueError):
                    price = 0.0
                key = ((p.model_key_override or p.model_key or "").strip() if p else "")
                rows.append(SaleLine(
                    order_pk=order.pk, line=n, sold_at=order.created_at, product_id=pid[:80],
                    article=((p.article if p else "") or "")[:80], model_key=key[:200],
                    name=str(item.get("productName") or (p.name if p else ""))[:300],
                    brand=str(item.get("productBrand") or (p.brand if p else ""))[:120],
                    category_id=((p.category_id if p else "") or "")[:80],
                    size=str(item.get("size") or "")[:40], color=str(item.get("color") or "")[:80],
                    quantity=qty, price=price, refunded=order.payment_status == "refunded",
                ))
            with transaction.atomic():  # точка отката: сбой одного заказа не рвёт остальные
                SaleLine.objects.bulk_create(rows, ignore_conflicts=True)
        except Exception as e:  # noqa: BLE001
            print(f"\n  [analytics.0003] заказ {order.pk} пропущен: {e}")


class Migration(migrations.Migration):
    dependencies = [
        ("analytics", "0002_sale_line"),
        ("orders", "0008_order_is_test"),
        ("catalog", "0018_product_model_key_product_model_key_override"),
    ]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
