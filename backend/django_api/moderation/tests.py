"""Проверяем не «ручка отвечает 200», а что блокировка действительно прячет."""
from django.test import TestCase
from django.utils import timezone

from accounts.models import Account
from clubs.models import Club
from friends.models import Friendship

from .models import Block, Report


def _acc(uid, name, phone_hash=""):
    # email уникален и пустая строка считается значением — в тестах даём свой.
    return Account.objects.create(id=uid, name=name, phone=f"+7999{uid}",
                                  email=f"{uid}@test.local", phone_hash=phone_hash)


class BlockTests(TestCase):
    def setUp(self):
        self.a = _acc("a1", "Алекс")
        self.b = _acc("b1", "Борис")
        self.token = self._login(self.a)
        self.token_b = self._login(self.b)

    def _login(self, acc):
        from common.security import make_token
        return make_token(acc.id)

    def _auth(self, token):
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    def test_block_breaks_friendship(self):
        Friendship.objects.create(requester_id="a1", addressee_id="b1",
                                  status=Friendship.ACCEPTED)
        r = self.client.post("/v1/me/blocks", {"userId": "b1"},
                             content_type="application/json", **self._auth(self.token))
        self.assertEqual(r.status_code, 201)
        self.assertFalse(Friendship.objects.exists())

    def test_blocked_cannot_send_request_back(self):
        """Односторонняя запись, двусторонняя тишина: заявка не проходит и от того,
        кого заблокировали, иначе блокировка ничего не значит."""
        self.client.post("/v1/me/blocks", {"userId": "b1"},
                         content_type="application/json", **self._auth(self.token))
        r = self.client.post("/v1/friends/request", {"userId": "a1"},
                             content_type="application/json", **self._auth(self.token_b))
        self.assertEqual(r.status_code, 403)
        self.assertFalse(Friendship.objects.exists())

    def test_hidden_from_search_both_ways(self):
        self.client.post("/v1/me/blocks", {"userId": "b1"},
                         content_type="application/json", **self._auth(self.token))
        mine = self.client.get("/v1/friends/search?q=Борис", **self._auth(self.token))
        theirs = self.client.get("/v1/friends/search?q=Алекс", **self._auth(self.token_b))
        self.assertEqual(mine.json()["results"], [])
        self.assertEqual(theirs.json()["results"], [])

    def test_unblock_restores_visibility_but_not_friendship(self):
        Friendship.objects.create(requester_id="a1", addressee_id="b1",
                                  status=Friendship.ACCEPTED)
        self.client.post("/v1/me/blocks", {"userId": "b1"},
                         content_type="application/json", **self._auth(self.token))
        r = self.client.delete("/v1/me/blocks/b1", **self._auth(self.token))
        self.assertEqual(r.status_code, 200)
        found = self.client.get("/v1/friends/search?q=Борис", **self._auth(self.token))
        self.assertEqual(len(found.json()["results"]), 1)
        self.assertFalse(Friendship.objects.exists())

    def test_cannot_block_self(self):
        r = self.client.post("/v1/me/blocks", {"userId": "a1"},
                             content_type="application/json", **self._auth(self.token))
        self.assertEqual(r.status_code, 400)

    def test_list_shows_blocked(self):
        self.client.post("/v1/me/blocks", {"userId": "b1"},
                         content_type="application/json", **self._auth(self.token))
        r = self.client.get("/v1/me/blocks", **self._auth(self.token))
        self.assertEqual([x["userId"] for x in r.json()], ["b1"])

    def test_blocks_need_token(self):
        self.assertEqual(self.client.get("/v1/me/blocks").status_code, 401)


class ReportTests(TestCase):
    def setUp(self):
        self.a = _acc("a2", "Алекс")
        self.b = _acc("b2", "Борис")
        from common.security import make_token
        self.token = make_token("a2")

    def _auth(self):
        return {"HTTP_AUTHORIZATION": f"Bearer {self.token}"}

    def _report(self, **over):
        body = {"targetType": "user", "targetId": "b2", "reason": "abuse"}
        body.update(over)
        return self.client.post("/v1/reports", body,
                                content_type="application/json", **self._auth())

    def test_create(self):
        r = self._report(comment="Пишет гадости")
        self.assertEqual(r.status_code, 201)
        rep = Report.objects.get()
        self.assertEqual((rep.reporter_id, rep.target_id, rep.status),
                         ("a2", "b2", Report.NEW))

    def test_repeat_while_unresolved_is_same_signal(self):
        self._report()
        r = self._report()
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["duplicate"])
        self.assertEqual(Report.objects.count(), 1)

    def test_unknown_reason_and_target(self):
        self.assertEqual(self._report(reason="потому что").status_code, 400)
        self.assertEqual(self._report(targetId="нет-такого").status_code, 404)
        self.assertEqual(self._report(targetId="a2").status_code, 400)

    def test_club_target(self):
        Club.objects.create(id="c1", name="Клуб", owner_id="b2")
        self.assertEqual(self._report(targetType="club", targetId="c1").status_code, 201)

    def test_daily_cap(self):
        """Без потолка жалоба становится инструментом травли."""
        for i in range(20):
            Report.objects.create(reporter_id="a2", target_type="user",
                                  target_id="b2", reason="spam",
                                  status=Report.ACCEPTED, created_at=timezone.now())
        self.assertEqual(self._report().status_code, 429)

    def test_reasons_list(self):
        r = self.client.get("/v1/reports/reasons", **self._auth())
        codes = [x["code"] for x in r.json()]
        self.assertIn("abuse", codes)
