"""Демо-партнёры лояльности на карте (D-81) — для локальной проверки слоя «Карты».

НЕ запускать на проде: это витрина. Реальных партнёров владелец заводит в админке
(«Партнёры на карте»). Категория старта — спортпитание и витамины (Якутск).
Идемпотентно по (name, city)."""
from django.core.management.base import BaseCommand

from loyalty.models import LoyaltyPartner

DEMO = [
    dict(name="СпортПит Якутск", emoji="🥗", points_percent=25,
         description="спортивное питание", address="пр. Ленина, 1",
         lat=62.0275, lng=129.7290),
    dict(name="Аптека «Здоровье»", emoji="💊", points_percent=15,
         description="витамины и БАДы", address="ул. Кирова, 18",
         lat=62.0301, lng=129.7360),
    dict(name="Витамин+", emoji="💊", points_percent=20,
         description="витамины", address="ул. Дзержинского, 44",
         lat=62.0250, lng=129.7405),
    dict(name="FitBar", emoji="🥤", points_percent=30,
         description="смузи и протеин", address="пр. Ленина, 27",
         lat=62.0325, lng=129.7250),
]


class Command(BaseCommand):
    help = "Заводит демо-партнёров лояльности (спортпитание/витамины, Якутск) для проверки слоя на карте"

    def handle(self, *args, **opts):
        created = 0
        for d in DEMO:
            _, is_new = LoyaltyPartner.objects.get_or_create(
                name=d["name"], city="Якутск",
                defaults={
                    "category": "nutrition",
                    "emoji": d["emoji"],
                    "points_percent": d["points_percent"],
                    "description": d["description"],
                    "address": d["address"],
                    "lat": d["lat"],
                    "lng": d["lng"],
                    "is_active": True,
                },
            )
            created += 1 if is_new else 0
        self.stdout.write(self.style.SUCCESS(f"Партнёров заведено: {created}"))
