"""Пересчитать витринные названия у всех товаров.

    python manage.py rebuild_shop_names          # пересчитать
    python manage.py rebuild_shop_names --dry    # только показать, что получится

Нужна после правки правил разбора (`catalog/naming.py`) и при первом запуске:
обычно имя пересчитывается само при выгрузке из 1С, но ждать выгрузку незачем.
Ручные правки (`display_name_override`) не трогаем — они сильнее автоматики.
"""
from django.core.management.base import BaseCommand

from catalog.models import Product

CHUNK = 500


class Command(BaseCommand):
    help = "Пересчитывает витринные названия товаров из складских имён 1С."

    def add_arguments(self, parser):
        parser.add_argument("--dry", action="store_true",
                            help="показать изменения, ничего не сохраняя")
        parser.add_argument("--limit", type=int, default=15,
                            help="сколько примеров показать (по умолчанию 15)")

    def handle(self, *args, **o):
        changed, shown, batch = 0, 0, []
        for product in Product.objects.all().iterator(chunk_size=CHUNK):
            was = product.display_name
            now = product.rebuild_display_name()
            if now == was:
                continue
            changed += 1
            if shown < o["limit"]:
                self.stdout.write(f"  {product.name}\n      → {now}")
                shown += 1
            if not o["dry"]:
                batch.append(product)
                if len(batch) >= CHUNK:
                    Product.objects.bulk_update(batch, ["display_name"])
                    batch = []
        if batch and not o["dry"]:
            Product.objects.bulk_update(batch, ["display_name"])

        total = Product.objects.count()
        word = "получилось бы" if o["dry"] else "пересчитано"
        self.stdout.write(self.style.SUCCESS(f"{word} названий: {changed} из {total}"))
