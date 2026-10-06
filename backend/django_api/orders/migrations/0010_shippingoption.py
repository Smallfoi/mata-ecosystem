from decimal import Decimal

from django.db import migrations, models


def seed(apps, schema_editor):
    """Те же два способа, что были в коде клиентов, и та же цена — 0 ₽ (D-92)."""
    ShippingOption = apps.get_model("orders", "ShippingOption")
    ShippingOption.objects.get_or_create(code="courier", defaults={
        "name": "Курьер по Якутску", "kind": "delivery", "zone": "Якутск",
        "price": Decimal(0), "requires_address": True, "sort_order": 10,
        "description": "Курьер свяжется с вами и договорится о времени.",
    })
    ShippingOption.objects.get_or_create(code="pickup", defaults={
        "name": "Самовывоз", "kind": "pickup", "zone": "Якутск",
        "price": Decimal(0), "sort_order": 20,
        "description": "Из магазина МАТА — сообщим, когда заказ можно забрать.",
    })


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0009_order_total_kop"),
    ]

    operations = [
        migrations.CreateModel(
            name="ShippingOption",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.SlugField(help_text="Как способ называют приложение и сайт (pickup, courier…). У существующих способов не менять.", max_length=40, unique=True, verbose_name="Код")),
                ("name", models.CharField(max_length=80, verbose_name="Название")),
                ("kind", models.CharField(choices=[("pickup", "Самовывоз"), ("delivery", "Доставка")], default="delivery", max_length=10, verbose_name="Тип")),
                ("zone", models.CharField(blank=True, default="", help_text="Где работает: «Якутск», «вся Россия»…", max_length=120, verbose_name="Зона")),
                ("description", models.CharField(blank=True, default="", help_text="Адрес самовывоза, сроки, как связывается курьер.", max_length=300, verbose_name="Пояснение покупателю")),
                ("price", models.DecimalField(decimal_places=2, default=0, max_digits=10, verbose_name="Цена, ₽")),
                ("free_from", models.DecimalField(blank=True, decimal_places=2, help_text="Сумма товаров, с которой способ бесплатный. Пусто — порога нет.", max_digits=10, null=True, verbose_name="Бесплатно от, ₽")),
                ("requires_address", models.BooleanField(default=False, verbose_name="Нужен адрес")),
                ("is_active", models.BooleanField(default=True, verbose_name="Доступен")),
                ("sort_order", models.PositiveIntegerField(default=0, verbose_name="Порядок")),
            ],
            options={
                "verbose_name": "Способ доставки",
                "verbose_name_plural": "Способы доставки",
                "db_table": "store_shipping_options",
                "ordering": ["sort_order", "id"],
            },
        ),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
