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


def _h(phone: str) -> str:
    return hashlib.sha256(phone.encode()).hexdigest()


class MatchContactsScaleTests(ApiTestCase):
    """Сопоставление контактов (аудит F02): поиск по индексу, а не перебор всех
    аккаунтов; запросов к БД не больше, чем при двух совпадениях; вход ограничен."""
    phone = "+79990003300"

    def _accounts(self, n, start=0):
        for i in range(start, start + n):
            Account.objects.create(id=f"u_mc{i}", email=f"mc{i}@x.local",
                                   phone=f"+7999100{i:04d}", name=f"Контакт {i}")

    def _match(self, hashes, token=None):
        return self.api_post("/v1/friends/match-contacts", {"hashes": hashes}, token=token)

    def test_contract_kept(self):
        self._accounts(3)
        Account.objects.create(id="u_mc_old", email="old@x.local", phone="8 (999) 200-00-01")
        res = self._match([_h("+79991000001"), _h("+79992000001"), "мусор", 5]).json()
        got = sorted(res["results"], key=lambda x: x["userId"])
        self.assertEqual([x["userId"] for x in got], ["u_mc1", "u_mc_old"],
                         "номер в старом формате (8, скобки) тоже должен находиться")
        self.assertEqual(set(got[0]), {"userId", "name", "avatarPath", "status"})
        self.assertEqual(got[0]["status"], "none")

    def test_self_is_not_matched(self):
        self.assertEqual(self._match([_h(self.phone)]).json()["results"], [])

    def test_relationship_status_in_results(self):
        self._accounts(2)
        self.api_post("/v1/friends/request", {"userId": "u_mc0"})
        res = {x["userId"]: x["status"]
               for x in self._match([_h("+79991000000"), _h("+79991000001")]).json()["results"]}
        self.assertEqual(res, {"u_mc0": "outgoing", "u_mc1": "none"})

    def test_queries_do_not_grow_with_accounts_or_matches(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        self._accounts(2)
        self._match([_h("+79991000000")])  # прогрев: разовые запросы первого вызова
        with CaptureQueriesContext(connection) as small:
            self._match([_h("+79991000000"), _h("+79991000001")])
        self._accounts(30, start=2)
        hashes = [_h(f"+7999100{i:04d}") for i in range(32)]
        with CaptureQueriesContext(connection) as big:
            res = self._match(hashes).json()
        self.assertEqual(len(res["results"]), 32)
        self.assertEqual(len(big.captured_queries), len(small.captured_queries),
                         "число запросов растёт с числом совпадений/аккаунтов")

    def test_lookup_uses_indexed_hash(self):
        """Аккаунты ищутся по индексированному хешу, а не читаются все подряд."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        self._accounts(3)
        with CaptureQueriesContext(connection) as ctx:
            self._match([_h("+79991000001")])
        acc_sql = [q["sql"] for q in ctx.captured_queries
                   if 'FROM "accounts"' in q["sql"] and "phone_hash" in q["sql"]]
        self.assertTrue(acc_sql, "нет выборки по phone_hash")
        field = Account._meta.get_field("phone_hash")
        self.assertTrue(field.db_index, "phone_hash без индекса")

    def test_hash_follows_phone_change(self):
        acc = Account.objects.create(id="u_mc_ch", email="ch@x.local", phone="")
        self.assertEqual(self._match([_h("+79993000000")]).json()["results"], [])
        acc.phone = "+79993000000"
        acc.save(update_fields=["phone"])
        ids = [x["userId"] for x in self._match([_h("+79993000000")]).json()["results"]]
        self.assertEqual(ids, ["u_mc_ch"])

    def test_oversized_list_is_truncated_not_rejected(self):
        """Старые сборки шлют все контакты без лимита — не отбиваем, а обрезаем."""
        from friends import views
        hashes = [_h(f"+7888{i:07d}") for i in range(views._MAX_CONTACT_HASHES + 50)]
        r = self._match(hashes)
        self.assertEqual(r.status_code, 200)

    def test_rate_limited(self):
        from django.conf import settings
        rate = settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["contacts"]
        limit = int(rate.split("/")[0])
        for _ in range(limit):
            self.assertEqual(self._match([_h("+79991000000")]).status_code, 200)
        self.assertEqual(self._match([_h("+79991000000")]).status_code, 429)

    def test_migration_backfills_existing_accounts(self):
        """Миграция заполняет хеш у уже существующих аккаунтов (на проде они есть)."""
        import importlib

        from django.apps import apps

        mig = importlib.import_module("accounts.migrations.0012_account_phone_hash")
        Account.objects.create(id="u_mc_bf", email="bf@x.local", phone="8-999-400-00-00")
        Account.objects.filter(id="u_mc_bf").update(phone_hash="")
        mig.fill(apps, None)
        self.assertEqual(Account.objects.get(id="u_mc_bf").phone_hash, _h("+79994000000"))
        ids = [x["userId"] for x in self._match([_h("+79994000000")]).json()["results"]]
        self.assertEqual(ids, ["u_mc_bf"])
