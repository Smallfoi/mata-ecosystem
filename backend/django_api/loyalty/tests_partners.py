"""Партнёры лояльности на карте (D-81): публичный список для слоя «Карты»."""
from django.test import TestCase

from loyalty.models import LoyaltyPartner


class LoyaltyPartnersApiTests(TestCase):
    def _mk(self, name, active=True, category="nutrition", city="Якутск", pct=25):
        return LoyaltyPartner.objects.create(
            name=name, category=category, city=city, points_percent=pct,
            lat=62.0, lng=129.7, is_active=active, emoji="🥗",
        )

    def test_public_no_token(self):
        """Слой карты дёргает список без токена — эндпоинт публичный."""
        self._mk("Открытый")
        self.assertEqual(self.client.get("/v1/loyalty/partners").status_code, 200)

    def test_lists_only_active(self):
        self._mk("Активный")
        self._mk("Скрытый", active=False)
        names = [p["name"] for p in
                 self.client.get("/v1/loyalty/partners").json()["partners"]]
        self.assertIn("Активный", names)
        self.assertNotIn("Скрытый", names)

    def test_json_shape(self):
        self._mk("Форма", pct=30)
        p = self.client.get("/v1/loyalty/partners").json()["partners"][0]
        for key in ("id", "name", "category", "emoji", "lat", "lng", "pointsPercent"):
            self.assertIn(key, p)
        self.assertEqual(p["pointsPercent"], 30)

    def test_city_filter(self):
        self._mk("Як", city="Якутск")
        self._mk("Мск", city="Москва")
        names = [p["name"] for p in self.client.get(
            "/v1/loyalty/partners", {"city": "Якутск"}).json()["partners"]]
        self.assertEqual(names, ["Як"])
