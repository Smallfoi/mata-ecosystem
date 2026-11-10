"""Номер заказа выдаёт сервер (D-120).

Старые заказы номер сохраняют: на него ссылаются платежи ЮKassa, баллы,
уведомления и 1С. Их черновой номер = текущий. Если у двух покупателей номер
совпал (до D-120 это было возможно), более поздний заказ получает суффикс
`-<id>` — иначе не встанет уникальный индекс.
"""
from django.db import migrations, models


def forwards(apps, schema_editor):
    Order = apps.get_model("orders", "Order")
    seen = set()
    for row in Order.objects.order_by("pk").only("pk", "order_id"):
        number = row.order_id
        if number in seen:
            number = f"{row.order_id}-{row.pk}"[:40]
        seen.add(number)
        Order.objects.filter(pk=row.pk).update(client_ref=row.order_id, order_id=number)


class Migration(migrations.Migration):
    dependencies = [("orders", "0012_order_paid_at_receipt")]

    operations = [
        migrations.AddField(
            model_name="order",
            name="client_ref",
            field=models.CharField(blank=True, default="", max_length=40,
                                   verbose_name="Черновой номер из приложения"),
        ),
        migrations.RunPython(forwards, migrations.RunPython.noop),
        migrations.AlterUniqueTogether(name="order", unique_together=set()),
        migrations.AlterField(
            model_name="order",
            name="order_id",
            field=models.CharField(max_length=40, unique=True, verbose_name="Номер заказа"),
        ),
        migrations.AddConstraint(
            model_name="order",
            constraint=models.UniqueConstraint(condition=models.Q(("client_ref", ""), _negated=True),
                                               fields=("user_id", "client_ref"),
                                               name="uniq_order_client_ref"),
        ),
    ]
