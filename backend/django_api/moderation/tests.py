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


class AppealTests(TestCase):
    """§10: человек видит, чем кончилась его жалоба, и может возразить на меру."""

    def setUp(self):
        from common.security import make_token
        self.a = _acc("a3", "Алекс")   # заявитель
        self.b = _acc("b3", "Борис")   # тот, к кому применили меру
        self.ta = make_token("a3")
        self.tb = make_token("b3")

    def _auth(self, token):
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    def _report(self, resolution=""):
        return Report.objects.create(
            reporter_id="a3", target_type=Report.TARGET_USER, target_id="b3",
            reason="abuse", comment="угрожает", resolution=resolution,
        )

    def _measure(self, **over):
        from moderation.models import ModerationMeasure
        kw = dict(target_type=Report.TARGET_USER, target_id="b3",
                  kind=ModerationMeasure.KIND_WARNING, summary="Оскорбления в чате клуба")
        kw.update(over)
        return ModerationMeasure.objects.create(**kw)

    def test_reporter_sees_status_and_answer(self):
        self._report(resolution="Предупредили")
        Report.objects.update(status=Report.ACCEPTED)

        r = self.client.get("/v1/me/reports", **self._auth(self.ta))
        row = r.json()[0]
        self.assertEqual(row["targetName"], "Борис")
        self.assertEqual(row["status"], "accepted")
        self.assertNotIn("resolution", row)  # решение — о другом человеке

    def test_reporter_sees_only_own_reports(self):
        self._report()
        r = self.client.get("/v1/me/reports", **self._auth(self.tb))
        self.assertEqual(r.json(), [])

    def test_measure_visible_to_its_target(self):
        self._measure()
        r = self.client.get("/v1/me/measures", **self._auth(self.tb))
        rows = r.json()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["summary"], "Оскорбления в чате клуба")
        self.assertTrue(rows[0]["canAppeal"])
        # Жалоба, из которой выросла мера, наружу не уходит: в ней чужое имя.
        self.assertNotIn("report", rows[0])
        self.assertNotIn("reporterId", rows[0])

    def test_measure_invisible_to_others(self):
        self._measure()
        r = self.client.get("/v1/me/measures", **self._auth(self.ta))
        self.assertEqual(r.json(), [])

    def test_appeal_once(self):
        from moderation.models import ModerationMeasure
        m = self._measure()
        ok = self.client.post(f"/v1/me/measures/{m.pk}/appeal", {"text": "Это был не я"},
                              content_type="application/json", **self._auth(self.tb))
        self.assertEqual(ok.status_code, 201)
        m.refresh_from_db()
        self.assertEqual(m.appeal_status, ModerationMeasure.APPEAL_NEW)
        self.assertEqual(m.appeal_text, "Это был не я")

        again = self.client.post(f"/v1/me/measures/{m.pk}/appeal", {"text": "ещё раз"},
                                 content_type="application/json", **self._auth(self.tb))
        self.assertEqual(again.status_code, 409)

    def test_appeal_needs_text(self):
        m = self._measure()
        r = self.client.post(f"/v1/me/measures/{m.pk}/appeal", {"text": "   "},
                             content_type="application/json", **self._auth(self.tb))
        self.assertEqual(r.status_code, 400)

    def test_cannot_appeal_someone_elses_measure(self):
        """Чужая мера и несуществующая отвечают одинаково: перебором id нельзя
        узнать, что к кому применили."""
        m = self._measure()
        mine = self.client.post(f"/v1/me/measures/{m.pk}/appeal", {"text": "не я"},
                                content_type="application/json", **self._auth(self.ta))
        ghost = self.client.post("/v1/me/measures/999999/appeal", {"text": "не я"},
                                 content_type="application/json", **self._auth(self.ta))
        self.assertEqual(mine.status_code, 404)
        self.assertEqual(ghost.status_code, 404)

    def test_club_owner_sees_and_appeals_club_measure(self):
        Club.objects.create(id="c3", name="Клуб", owner_id="b3")
        m = self._measure(target_type=Report.TARGET_CLUB, target_id="c3",
                          summary="Название клуба нарушает правила")

        seen = self.client.get("/v1/me/measures", **self._auth(self.tb))
        self.assertEqual(len(seen.json()), 1)
        r = self.client.post(f"/v1/me/measures/{m.pk}/appeal", {"text": "переименуем"},
                             content_type="application/json", **self._auth(self.tb))
        self.assertEqual(r.status_code, 201)

    def test_admin_action_requires_answer_and_notifies(self):
        """Мера без объяснения — мера, которую нельзя обжаловать: такую не даём."""
        from django.contrib.admin.sites import AdminSite
        from notifications.models import Notification
        from moderation.admin import ReportAdmin
        from moderation.models import ModerationMeasure

        silent = self._report()                       # без resolution
        spoken = self._report(resolution="Предупреждение за оскорбления")
        admin_obj = ReportAdmin(Report, AdminSite())

        request = type("R", (), {})()
        messages_seen = []
        admin_obj.message_user = lambda req, msg, level=None: messages_seen.append(msg)
        admin_obj.mark_accepted(request, Report.objects.filter(
            pk__in=[silent.pk, spoken.pk]))

        self.assertEqual(ModerationMeasure.objects.count(), 1)
        measure = ModerationMeasure.objects.get()
        self.assertEqual(measure.summary, "Предупреждение за оскорбления")
        silent.refresh_from_db()
        self.assertEqual(silent.status, Report.NEW)   # без ответа — не закрыта

        note = Notification.objects.get(user_id="b3")
        self.assertIn("Применена мера", note.body)
        # В уведомлении не должно быть ни заявителя, ни его слов.
        self.assertNotIn("Алекс", note.body)
        self.assertNotIn("угрожает", note.body)

    def test_reporter_is_told_the_outcome_without_details(self):
        from django.contrib.admin.sites import AdminSite
        from notifications.models import Notification
        from moderation.admin import ReportAdmin

        accepted = self._report(resolution="Предупреждение за оскорбления")
        admin_obj = ReportAdmin(Report, AdminSite())
        admin_obj.message_user = lambda *a, **k: None
        admin_obj.mark_accepted(None, Report.objects.filter(pk=accepted.pk))
        note = Notification.objects.get(user_id="a3")
        self.assertIn("приняли меры", note.body)
        # Что именно применили к другому человеку — заявителю не пересказываем.
        self.assertNotIn("оскорбления", note.body)

        rejected = self._report()
        admin_obj.mark_rejected(None, Report.objects.filter(pk=rejected.pk))
        self.assertTrue(Notification.objects.filter(
            user_id="a3", body__contains="нарушения правил не нашли").exists())

    def test_appeal_answer_reaches_the_person_and_lifts_the_measure(self):
        from django.contrib.admin.sites import AdminSite
        from notifications.models import Notification
        from moderation.admin import ModerationMeasureAdmin
        from moderation.models import ModerationMeasure

        m = self._measure()
        self.client.post(f"/v1/me/measures/{m.pk}/appeal", {"text": "Это был не я"},
                         content_type="application/json", **self._auth(self.tb))
        admin_obj = ModerationMeasureAdmin(ModerationMeasure, AdminSite())
        admin_obj.message_user = lambda *a, **k: None
        admin_obj.appeal_accept(None, ModerationMeasure.objects.filter(pk=m.pk))
        m.refresh_from_db()
        self.assertFalse(m.active)
        self.assertEqual(m.appeal_status, ModerationMeasure.APPEAL_ACCEPTED)
        self.assertTrue(Notification.objects.filter(
            user_id="b3", title="Ответ на возражение", body__contains="мера снята").exists())

    def test_bad_measure_id_is_a_plain_not_found(self):
        r = self.client.post("/v1/me/measures/abc/appeal", {"text": "не я"},
                             content_type="application/json", **self._auth(self.tb))
        self.assertEqual(r.status_code, 404)
