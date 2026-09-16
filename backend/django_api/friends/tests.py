"""Дружба (D-82, этап 2a): заявка → подтверждение → взаимные друзья."""
import hashlib

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
