"""Дружба (D-82, этап 2a): заявка → подтверждение → взаимные друзья."""
import hashlib
import json

from accounts.models import Account
from common.testutils import ApiTestCase


class FriendsApiTests(ApiTestCase):
    phone = "+79990003100"

    def setUp(self):
        super().setUp()
        self.t2 = self.new_user("+79990003101")
        self.uid2 = Account.objects.get(phone="+79990003101").id
        Account.objects.filter(id=self.uid).update(name="Алиса")
        Account.objects.filter(id=self.uid2).update(name="Борис")

    def _delete(self, path, token=None):
        return self.client.delete(
            path, HTTP_AUTHORIZATION=f"Bearer {token or self.token}"
        )

    def test_request_then_accept_makes_friends(self):
        r = self.api_post("/v1/friends/request", {"userId": self.uid2})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "outgoing")
        inc = self.api_get("/v1/friends", token=self.t2).json()["incoming"]
        self.assertEqual([x["userId"] for x in inc], [self.uid])
        a = self.api_post(f"/v1/friends/{self.uid}/accept", {}, token=self.t2)
        self.assertEqual(a.json()["status"], "friends")
        f1 = self.api_get("/v1/friends").json()["friends"]
        self.assertEqual([x["userId"] for x in f1], [self.uid2])

    def test_reverse_request_auto_accepts(self):
        self.api_post("/v1/friends/request", {"userId": self.uid2})
        r = self.api_post("/v1/friends/request", {"userId": self.uid}, token=self.t2)
        self.assertEqual(r.json()["status"], "friends")

    def test_reject_removes_pending(self):
        self.api_post("/v1/friends/request", {"userId": self.uid2})
        r = self.api_post(f"/v1/friends/{self.uid}/reject", {}, token=self.t2)
        self.assertEqual(r.json()["status"], "none")
        self.assertEqual(
            self.api_get("/v1/friends", token=self.t2).json()["incoming"], []
        )

    def test_remove_friend(self):
        self.api_post("/v1/friends/request", {"userId": self.uid2})
        self.api_post(f"/v1/friends/{self.uid}/accept", {}, token=self.t2)
        self._delete(f"/v1/friends/{self.uid2}")
        self.assertEqual(self.api_get("/v1/friends").json()["friends"], [])

    def test_cannot_friend_self(self):
        self.assertEqual(
            self.api_post("/v1/friends/request", {"userId": self.uid}).status_code, 400
        )

    def test_search_excludes_self_and_finds_by_name(self):
        res = self.api_get("/v1/friends/search?q=Бор").json()["results"]
        ids = [x["userId"] for x in res]
        self.assertIn(self.uid2, ids)
        self.assertNotIn(self.uid, ids)

    def test_match_contacts_by_phone_hash(self):
        h = hashlib.sha256("+79990003101".encode()).hexdigest()
        res = self.api_post("/v1/friends/match-contacts", {"hashes": [h]}).json()
        self.assertEqual([x["userId"] for x in res["results"]], [self.uid2])

    def test_suggestions_ok(self):
        self.assertEqual(self.api_get("/v1/friends/suggestions").status_code, 200)

    def test_requires_token(self):
        self.assertEqual(self.client.get("/v1/friends").status_code, 401)


class FriendsMapTests(ApiTestCase):
    """Карта друзей (D-83): позиции только взаимным, огрубление, дом, «Тень»."""
    phone = "+79990003200"

    def setUp(self):
        super().setUp()
        self.t2 = self.new_user("+79990003201")
        self.uid2 = Account.objects.get(phone="+79990003201").id
        self.api_post("/v1/friends/request", {"userId": self.uid2})
        self.api_post(f"/v1/friends/{self.uid}/accept", {}, token=self.t2)

    def _prefs(self, body, token=None):
        return self.client.put(
            "/v1/friends/prefs", data=json.dumps(body),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token or self.token}",
        )

    def test_prefs_default_invisible(self):
        self.assertFalse(self.api_get("/v1/friends/prefs").json()["visible"])

    def test_position_not_stored_when_invisible(self):
        r = self.api_post("/v1/friends/position", {"lat": 62.03, "lng": 129.73})
        self.assertFalse(r.json()["stored"])

    def test_visible_position_coarsened_and_seen_by_friend(self):
        self._prefs({"visible": True})
        self.api_post("/v1/friends/position", {"lat": 62.0281, "lng": 129.7325})
        pos = self.api_get("/v1/friends/positions", token=self.t2).json()["positions"]
        self.assertEqual([p["userId"] for p in pos], [self.uid])
        self.assertNotEqual(pos[0]["lat"], 62.0281)   # огрублено, не точная точка

    def test_non_friend_does_not_see(self):
        self._prefs({"visible": True})
        self.api_post("/v1/friends/position", {"lat": 62.03, "lng": 129.73})
        t3 = self.new_user("+79990003202")
        self.assertEqual(
            self.api_get("/v1/friends/positions", token=t3).json()["positions"], []
        )

    def test_home_zone_hides(self):
        self._prefs({"visible": True, "home": {"lat": 62.03, "lng": 129.73}})
        r = self.api_post("/v1/friends/position", {"lat": 62.0301, "lng": 129.7302})
        self.assertFalse(r.json()["stored"])

    def test_shadow_reciprocity(self):
        self._prefs({"visible": True})
        self.api_post("/v1/friends/position", {"lat": 62.03, "lng": 129.73})
        self._prefs({"visible": True}, token=self.t2)
        self.api_post("/v1/friends/position", {"lat": 62.04, "lng": 129.74}, token=self.t2)
        self._prefs({"hideHours": 2})  # я ухожу в «Тень»
        mine = self.api_get("/v1/friends/positions").json()
        self.assertEqual(mine["positions"], [])
        self.assertTrue(mine.get("inShadow"))
        seen = self.api_get("/v1/friends/positions", token=self.t2).json()["positions"]
        self.assertEqual([p["userId"] for p in seen], [])  # меня в тени не видят


    # ── «Маяк» (D-84): точная точка доверенным ──
    def test_beacon_gives_exact_to_trusted(self):
        self.api_post("/v1/friends/beacon", {"hours": 2, "trusted": [self.uid2]})
        self.api_post("/v1/friends/position", {"lat": 62.0281, "lng": 129.7325})
        pos = self.api_get("/v1/friends/positions", token=self.t2).json()["positions"]
        self.assertEqual(len(pos), 1)
        self.assertTrue(pos[0]["beacon"])
        self.assertEqual(pos[0]["lat"], 62.0281)  # точная, не огрублённая

    def test_beacon_not_leaked_to_non_trusted(self):
        t3 = self.new_user("+79990003203")
        uid3 = Account.objects.get(phone="+79990003203").id
        self.api_post("/v1/friends/request", {"userId": uid3})
        self.api_post(f"/v1/friends/{self.uid}/accept", {}, token=t3)
        self.api_post("/v1/friends/beacon", {"hours": 2, "trusted": [self.uid2]})
        self.api_post("/v1/friends/position", {"lat": 62.0281, "lng": 129.7325})
        self.assertEqual(
            self.api_get("/v1/friends/positions", token=t3).json()["positions"], [])
        self.assertTrue(
            self.api_get("/v1/friends/positions", token=self.t2).json()["positions"][0]["beacon"])

    def test_beacon_off_clears_exact(self):
        self.api_post("/v1/friends/beacon", {"hours": 2, "trusted": [self.uid2]})
        self.api_post("/v1/friends/position", {"lat": 62.0281, "lng": 129.7325})
        self.api_post("/v1/friends/beacon", {"off": True})
        self.assertEqual(
            self.api_get("/v1/friends/positions", token=self.t2).json()["positions"], [])

    def test_beacon_trusted_must_be_friends(self):
        t3 = self.new_user("+79990003204")
        uid3 = Account.objects.get(phone="+79990003204").id
        r = self.api_post("/v1/friends/beacon", {"hours": 2, "trusted": [uid3]}).json()
        self.assertEqual(r["beaconTrusted"], [])
