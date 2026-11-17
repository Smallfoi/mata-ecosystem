"""Заполнить каталог Store данными (идемпотентно: upsert по id).
Запуск: docker compose exec web python manage.py seed_catalog

Только для пустой базы (dev, первый подъём сервера). Как только пришёл каталог
из 1С, сид ничего не делает: иначе он вернул бы на витрину снятые демо-товары
(миграция catalog 0025) и стёр бы настоящие баннеры — их он пересоздаёт целиком."""
from django.core.management.base import BaseCommand

from catalog.models import Banner, Category, Product
from catalog.seed_data import BANNERS, CATEGORIES, PRODUCTS


class Command(BaseCommand):
    help = "Сидирует категории/товары/баннеры каталога Store (upsert)."

    def handle(self, *args, **options):
        if Product.objects.filter(external_id__isnull=False).exists():
            self.stdout.write("catalog seed skipped: каталог уже приходит из 1С")
            return
        for i, c in enumerate(CATEGORIES):
            Category.objects.update_or_create(
                id=c["id"],
                defaults={
                    "name": c["name"],
                    "emoji": c.get("emoji", ""),
                    "image_url": c.get("imageUrl"),
                    "sort": i,
                },
            )
        for i, p in enumerate(PRODUCTS):
            Product.objects.update_or_create(
                id=p["id"],
                defaults={
                    "name": p["name"],
                    "brand": p.get("brand", ""),
                    "category_id": p["categoryId"],
                    "price": p["price"],
                    "old_price": p.get("oldPrice"),
                    "image_urls": p.get("imageUrls", []),
                    "description": p.get("description", ""),
                    "sizes": p.get("sizes", []),
                    "colors": p.get("colors", []),
                    "is_new": p.get("isNew", False),
                    "is_featured": p.get("isFeatured", False),
                    "rating": p.get("rating", 0),
                    "review_count": p.get("reviewCount", 0),
                    "in_stock": p.get("inStock", True),
                    "sort": i,
                },
            )
        # Баннеры пересоздаём целиком (их мало, нет стабильного id).
        Banner.objects.all().delete()
        for i, b in enumerate(BANNERS):
            Banner.objects.create(
                title=b["title"],
                subtitle=b.get("subtitle", ""),
                image_url=b.get("imageUrl", ""),
                action=b.get("action", ""),
                sort=i,
            )
        self.stdout.write(
            self.style.SUCCESS(
                f"catalog seeded: {Category.objects.count()} cat / "
                f"{Product.objects.count()} prod / {Banner.objects.count()} banners"
            )
        )
