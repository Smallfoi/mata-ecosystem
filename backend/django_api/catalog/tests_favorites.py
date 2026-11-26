"""Избранное на едином аккаунте: /v1/favorites (аудит сайта 26.11.2026, пункт 6)."""
import json

from catalog.favorites_api import MAX_FAVORITES
from catalog.models import Favorite
from common.testutils import ApiTestCase


class FavoritesTests(ApiTestCase):
    phone = "+79990077311"

    def put(self, key):
        return self.client.put(f"/v1/favorites/{key}", HTTP_AUTHORIZATION=f"Bearer {self.token}")

    def delete(self, key):
        return self.client.delete(f"/v1/favorites/{key}", HTTP_AUTHORIZATION=f"Bearer {self.token}")

    def test_needs_token(self):
        self.assertEqual(self.client.get("/v1/favorites").status_code, 401)
        self.assertEqual(self.client.put("/v1/favorites/x").status_code, 401)
        self.assertEqual(self.client.post("/v1/favorites/merge", data="{}",
                                          content_type="application/json").status_code, 401)

    def test_add_twice_remove(self):
        self.assertEqual(self.put("812625546").json()["keys"], ["812625546"])
        self.assertEqual(self.put("812625546").json()["keys"], ["812625546"])  # повтор — не ошибка
        self.assertEqual(self.put("ANTA WALK 2.0").json()["keys"][0], "ANTA WALK 2.0")
        self.assertEqual(self.delete("812625546").json()["keys"], ["ANTA WALK 2.0"])
        self.assertEqual(self.api_get("/v1/favorites").json()["keys"], ["ANTA WALK 2.0"])

    def test_merge_guest_list_keeps_existing(self):
        self.put("A1")
        resp = self.api_post("/v1/favorites/merge", {"keys": ["A1", "B2", "", "x" * 200, "C3"]})
        self.assertEqual(sorted(resp.json()["keys"]), ["A1", "B2", "C3"])

    def test_merge_needs_list(self):
        self.assertEqual(self.api_post("/v1/favorites/merge", {"keys": "A1"}).status_code, 400)

    def test_cap(self):
        Favorite.objects.bulk_create(
            [Favorite(user_id=self.uid, model_key=f"k{i}") for i in range(MAX_FAVORITES)])
        self.put("one-more")
        self.assertEqual(Favorite.objects.filter(user_id=self.uid).count(), MAX_FAVORITES)

    def test_users_do_not_see_each_other(self):
        self.put("mine")
        other = self.client.post("/v1/auth/phone/verify",
                                 data=json.dumps({"phone": "+79990077312", "code": "1234"}),
                                 content_type="application/json").json()["token"]
        self.assertEqual(self.api_get("/v1/favorites", token=other).json()["keys"], [])
