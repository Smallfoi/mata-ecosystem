"""Программа лояльности v1, этап 2 — бонусы за активность, приглашение, регистрацию.

Приёмка ТЗ §6 №4 (13 пробежек → 120; 12 + 3 захвата + этап + ещё захват → 260)
и №5 (2,9 км; 5 км за 12 мин → suspicious); плюс реферал, регистрация, дубль
источников, 48 ч, одна в день, трек, соседний аккаунт, очередь в админке и
«флаг выключен → как раньше».
"""
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Account
from common.testutils import ApiTestCase, login_admin
from league.models import Division, DivisionMember
from loyalty import activity, config, v1
from loyalty.models import (
    LoyaltyActivity as Act,
    LoyaltyEvent,
    LoyaltyLot,
    LoyaltyPhoneGrant,
    LoyaltyReferral,
    LoyaltyTransaction,
)
from notifications.models import DeviceAccount
from runs.models import Run
from territories.models import CaptureAward
from trails.models import PendingTrack
from workouts.models import ExternalWorkout

YKT = ZoneInfo("Asia/Yakutsk")


def enable():
    config.set_value("LOYALTY_V1_ENABLED", True, by="test")


class ResetConfig:
    """Настройки кэшируются на минуту, а откат тестовой транзакции кэш не сбрасывает:
    без этого «программа включена» протекала бы в следующие тесты."""

    def tearDown(self):
        config.invalidate()
        super().tearDown()


def at(day, hour=8, month=9):
    return datetime(2026, month, day, hour, 0, tzinfo=YKT)


def line_track(start, km, sec_per_100m=30, lat0=62.0, lon0=129.7, fast=None):
    """Прямая на север: точка каждые 100 м. `fast` — (с какой сотни, сколько сотен,
    секунд на 100 м) — быстрый участок."""
    pts, t = [], int(start.timestamp() * 1000)
    n = int(round(km * 10))
    for i in range(n + 1):
        pts.append([lat0 + i * 0.0008993, lon0, t])
        step = sec_per_100m
        if fast and fast[0] <= i < fast[0] + fast[1]:
            step = fast[2]
        t += step * 1000
    return pts


class ActivityBase(ResetConfig, TestCase):
    uid = "u_act"

    def setUp(self):
        cache.clear()
        Account.objects.create(id=self.uid, email=f"{self.uid}@t.dev", phone="+79990061001")
        enable()

    def go(self, rid, finished, km=5.0, minutes=30, uid=None, upload=None, track=None,
            flagged=False):
        uid = uid or self.uid
        run = Run.objects.create(
            id=rid, user_id=uid, distance_m=km * 1000, duration_s=int(minutes * 60),
            finished_at=finished, created_at=upload or finished + timedelta(hours=1),
            flagged=flagged, flag_reason="Подделка" if flagged else "")
        if track is not None:
            PendingTrack.objects.create(run_id=rid, user_id=uid, points=track)
        return activity.on_run(run, now=run.created_at)

    def capture(self, cid, run_act_ref, when):
        run = Run.objects.get(id=run_act_ref)
        award = CaptureAward.objects.create(capture_id=cid, user_id=run.user_id, points=10,
                                            run_id=run.id, status=CaptureAward.AWARDED,
                                            created_at=when)
        return activity.on_capture(award, run, now=when)

    def available(self, uid=None):
        return v1.wallet(uid or self.uid)["available"]


class AcceptanceRuns(ActivityBase):
    """ТЗ §6 №4 — пробежки и общий лимит месяца на Базовом."""

    def test_13_runs_give_120(self):
        acts = [self.go(f"r{d}", at(d)) for d in range(1, 14)]
        self.assertEqual([a.status for a in acts[:12]], [Act.GRANTED] * 12)
        self.assertEqual(acts[12].status, Act.CAPPED)
        self.assertEqual(acts[12].amount, 0)
        self.assertEqual(self.available(), 120)
        p = activity.payload(acts[12])
        self.assertTrue(p["monthCapReached"])
        self.assertEqual(p["message"], activity.CAP_MESSAGE)
        self.assertEqual(p["runsLeft"], 0)
        self.assertEqual(p["activityLeft"], 140)
        # Лоты — available сразу, событие accrue_run, статусные идут.
        lot = LoyaltyLot.objects.filter(user_id=self.uid, source="run").first()
        self.assertEqual(lot.state, "available")
        self.assertEqual(lot.status_amount, 10)
        self.assertEqual(LoyaltyEvent.objects.filter(type="accrue_run").count(), 12)

    def stage_win(self, month="2026-09"):
        div = Division.objects.create(id="d_t0", tier=0, week_start=at(7).date(), seq=1)
        DivisionMember.objects.create(division_id=div.id, user_id=self.uid,
                                      week_start=div.week_start)
        return activity.close_stage_month(month, now=at(1, 2, month=10))

    def test_12_runs_3_captures_stage_and_more_capture_give_260(self):
        for d in range(1, 13):
            self.go(f"r{d}", at(d))
        caps = [self.capture(f"c{d}", f"r{d}", at(d, 9)) for d in range(1, 4)]
        self.assertEqual([c.status for c in caps], [Act.GRANTED] * 3)
        self.assertEqual(self.available(), 210)
        self.assertEqual(self.stage_win()["winners"], 1)
        self.assertEqual(self.available(), 260)
        fourth = self.capture("c4", "r4", at(4, 9))
        self.assertEqual(fourth.status, Act.CAPPED)
        self.assertEqual(self.available(), 260)

    def test_general_cap_cuts_even_when_kind_cap_is_free(self):
        config.set_value("CAP_CAPTURES_MONTH", 10, by="test")
        for d in range(1, 13):
            self.go(f"r{d}", at(d))
        for d in range(1, 4):
            self.capture(f"c{d}", f"r{d}", at(d, 9))
        self.stage_win()
        fourth = self.capture("c4", "r4", at(4, 9))
        self.assertEqual(fourth.status, Act.CAPPED)  # общий 260 исчерпан
        self.assertEqual(self.available(), 260)

    def test_stage_closes_once_and_only_first_place(self):
        Account.objects.create(id="u_b", email="b@t.dev", phone="+79990061002")
        div = Division.objects.create(id="d_t0", tier=0, week_start=at(7).date(), seq=1)
        for uid in (self.uid, "u_b"):
            DivisionMember.objects.create(division_id=div.id, user_id=uid,
                                          week_start=div.week_start)
        Run.objects.create(id="s1", user_id=self.uid, distance_m=20000, duration_s=7200,
                           finished_at=at(8))
        Run.objects.create(id="s2", user_id="u_b", distance_m=10000, duration_s=3600,
                           finished_at=at(8))
        self.assertEqual(activity.close_stage_month("2026-09", now=at(1, 2, 10))["winners"], 1)
        self.assertEqual(self.available(), 50)
        self.assertEqual(self.available("u_b"), 0)
        again = activity.close_stage_month("2026-09", now=at(2, 2, 10))
        self.assertEqual(again["skipped"], "closed")
        self.assertEqual(self.available(), 50)

    def test_stage_not_closed_before_month_end(self):
        self.assertEqual(activity.close_stage_month("2026-09", now=at(30, 12))["skipped"],
                         "not_finished")

    def test_month_resets_on_first_by_yakutsk_time(self):
        for d in range(1, 13):
            self.go(f"r{d}", at(d))
        # 1 октября 00:30 по Якутску — это ещё 30 сентября по UTC, но новый месяц.
        act = self.go("oct1", datetime(2026, 10, 1, 0, 30, tzinfo=YKT))
        self.assertEqual(act.month, "2026-10")
        self.assertEqual(act.status, Act.GRANTED)


class AcceptanceValidation(ActivityBase):
    """ТЗ §6 №5 и условия §3."""

    def test_2_9_km_gives_nothing(self):
        act = self.go("short", at(5), km=2.9, minutes=17)
        self.assertEqual(act.status, Act.INELIGIBLE)
        self.assertEqual(self.available(), 0)
        self.assertFalse(activity.suspicious_queue().exists())

    def test_5_km_in_12_minutes_is_suspicious(self):
        act = self.go("rocket", at(5), km=5, minutes=12)
        self.assertEqual(act.status, Act.SUSPICIOUS)
        self.assertEqual(self.available(), 0)
        self.assertIn(act, list(activity.suspicious_queue()))

    def test_too_slow_is_not_counted(self):
        self.assertEqual(self.go("walk", at(5), km=3.5, minutes=60).status, Act.INELIGIBLE)

    def test_uploaded_later_than_48h(self):
        act = self.go("late", at(5), upload=at(5) + timedelta(hours=49))
        self.assertEqual(act.status, Act.INELIGIBLE)
        self.assertIn("48", act.reason)
        self.assertEqual(self.go("ok47", at(6), upload=at(6) + timedelta(hours=47)).status,
                         Act.GRANTED)

    def test_one_counted_run_per_day(self):
        self.assertEqual(self.go("m", at(5, 7)).status, Act.GRANTED)
        self.assertEqual(self.go("e", at(5, 19)).status, Act.DAY_LIMIT)
        self.assertEqual(self.available(), 10)

    def test_duplicate_import_after_app_run(self):
        self.go("app", at(5, 8))
        w = ExternalWorkout.objects.create(
            id="w1", user_id=self.uid, source="healthconnect", source_id="hc1",
            started_at=at(5, 8) - timedelta(minutes=28), duration_s=1800, distance_m=5050,
            sport="running", imported_at=at(5, 9))
        act = activity.on_workout(w, None, now=at(5, 9))
        self.assertEqual(act.status, Act.DUPLICATE)
        self.assertEqual(self.available(), 10)

    def test_duplicate_app_run_after_import(self):
        w = ExternalWorkout.objects.create(
            id="w2", user_id=self.uid, source="healthconnect", source_id="hc2",
            started_at=at(5, 7, ) + timedelta(minutes=30), duration_s=1800, distance_m=5000,
            sport="running", imported_at=at(5, 9))
        self.assertEqual(activity.on_workout(w, None, now=at(5, 9)).status, Act.GRANTED)
        act = self.go("app2", at(5, 8) + timedelta(minutes=2))
        self.assertEqual(act.status, Act.DUPLICATE)
        self.assertEqual(self.available(), 10)

    def test_reimport_after_disconnect_does_not_pay_twice(self):
        w = ExternalWorkout.objects.create(
            id="w3", user_id=self.uid, source="file", source_id="f1",
            started_at=at(5, 7), duration_s=1800, distance_m=5000, sport="run",
            imported_at=at(5, 9))
        activity.on_workout(w, None, now=at(5, 9))
        w.delete()
        w = ExternalWorkout.objects.create(
            id="w3", user_id=self.uid, source="file", source_id="f1",
            started_at=at(5, 7), duration_s=1800, distance_m=5000, sport="run",
            imported_at=at(5, 10))
        activity.on_workout(w, None, now=at(5, 10))
        self.assertEqual(self.available(), 10)

    def test_summary_only_is_marked(self):
        act = self.go("sum", at(5))
        self.assertEqual(act.validated_by, "summary")
        self.assertEqual(act.status, Act.GRANTED)

    def test_track_distance_beats_client_number(self):
        act = self.go("liar", at(5), km=5, minutes=30,
                       track=line_track(at(5) - timedelta(minutes=30), 2.0, 90))
        self.assertEqual(act.validated_by, "track")
        self.assertEqual(act.status, Act.INELIGIBLE)

    def test_fast_segment_is_suspicious(self):
        track = line_track(at(5) - timedelta(minutes=30), 5.0, 30, fast=(10, 4, 10))
        act = self.go("seg", at(5), track=track)
        self.assertEqual(act.status, Act.SUSPICIOUS)
        self.assertIn("2:30", act.reason)

    def test_honest_track_passes(self):
        act = self.go("honest", at(5), track=line_track(at(5) - timedelta(minutes=25), 5.0))
        self.assertEqual((act.status, act.validated_by), (Act.GRANTED, "track"))

    def test_track_after_summary_rechecks_and_revokes(self):
        act = self.go("later", at(5))
        self.assertEqual(self.available(), 10)
        PendingTrack.objects.create(run_id="later", user_id=self.uid,
                                    points=line_track(at(5) - timedelta(minutes=30), 1.0, 180))
        act = activity.on_track("later", self.uid, now=at(5, 10))
        self.assertEqual(act.status, Act.SUSPICIOUS)
        self.assertEqual(self.available(), 0)
        self.assertEqual(LoyaltyEvent.objects.filter(type="cancel").count(), 1)

    def test_twin_accounts_on_one_device_both_suspicious(self):
        Account.objects.create(id="u_twin", email="tw@t.dev", phone="+79990061009")
        DeviceAccount.note("one-phone", self.uid)
        DeviceAccount.note("one-phone", "u_twin")
        track = line_track(at(5) - timedelta(minutes=25), 5.0)
        first = self.go("tw1", at(5), uid="u_twin", track=track)
        self.assertEqual(first.status, Act.GRANTED)
        self.assertEqual(self.available("u_twin"), 10)
        second = self.go("tw2", at(5), track=[list(p) for p in track])
        self.assertEqual(second.status, Act.SUSPICIOUS)
        first.refresh_from_db()
        self.assertEqual(first.status, Act.SUSPICIOUS)
        self.assertEqual(self.available("u_twin"), 0)
        self.assertEqual(self.available(), 0)

    def test_different_route_on_shared_device_is_fine(self):
        Account.objects.create(id="u_kid", email="k@t.dev", phone="+79990061010")
        DeviceAccount.note("family", self.uid)
        DeviceAccount.note("family", "u_kid")
        self.go("k1", at(5), uid="u_kid", track=line_track(at(5) - timedelta(minutes=25), 5.0))
        mine = self.go("k2", at(5), track=line_track(at(5) - timedelta(minutes=25), 5.0,
                                                       lon0=129.9))
        self.assertEqual(mine.status, Act.GRANTED)

    def test_capture_only_for_valid_run(self):
        self.go("short", at(5), km=2.0, minutes=12)
        self.assertEqual(self.capture("cs", "short", at(5, 9)).status, Act.INELIGIBLE)
        self.go("fast", at(6), km=5, minutes=12)
        waiting = self.capture("cf", "fast", at(6, 9))
        self.assertEqual(waiting.status, Act.WAITING)
        self.assertEqual(self.available(), 0)
        # Модератор подтвердил пробежку — приходят бонусы и за неё, и за захват.
        activity.approve(Act.objects.get(ref="fast"), by="mod")
        waiting.refresh_from_db()
        self.assertEqual(waiting.status, Act.GRANTED)
        self.assertEqual(self.available(), 40)

    def test_reject_suspicious(self):
        self.go("fast", at(6), km=5, minutes=12)
        act = activity.reject(Act.objects.get(ref="fast"), by="mod")
        self.assertEqual(act.status, Act.REJECTED)
        self.assertEqual(self.available(), 0)

    def test_game_flagged_run_waits_for_moderator(self):
        from runs.review import approve_run

        act = self.go("fl", at(5), flagged=True)
        self.assertEqual(act.status, Act.FLAGGED)
        run = Run.objects.get(id="fl")
        self.assertEqual(approve_run(run, by="mod", notify=False), 10)
        self.assertEqual(Act.objects.get(ref="fl").status, Act.GRANTED)

    def test_game_reject_revokes_bonus(self):
        from runs.review import reject_run

        self.go("rj", at(5))
        reject_run(Run.objects.get(id="rj"), by="mod", notify=False)
        self.assertEqual(Act.objects.get(ref="rj").status, Act.REJECTED)
        self.assertEqual(self.available(), 0)

    def test_frozen_while_on_review(self):
        self.go("rv", at(5))
        Account.objects.filter(id=self.uid).update(needs_review=True)
        self.assertEqual(v1.redeemable(self.uid), 0)


class RunsApi(ResetConfig, ApiTestCase):
    phone = "+79990061101"

    def post_run(self, rid, km=5.0, minutes=30):
        return self.api_post("/v1/runs", {
            "id": rid, "distanceMeters": km * 1000, "elapsedSeconds": int(minutes * 60),
            "finishedAtMs": int(timezone.now().timestamp() * 1000)}).json()

    def test_flag_off_as_before(self):
        out = self.post_run("off1")
        self.assertEqual(out["pointsAwarded"], 50)
        self.assertNotIn("bonus", out)
        self.assertFalse(Act.objects.exists())
        self.assertEqual(self.balance(), 50)

    def test_flag_on_bonus_not_game_points(self):
        enable()
        out = self.post_run("on1")
        self.assertEqual(out["pointsAwarded"], 10)
        self.assertEqual(out["bonus"]["amount"], 10)
        self.assertEqual(out["bonus"]["runsLeft"], 11)
        self.assertEqual(out["bonus"]["activityLeft"], 250)
        self.assertNotIn("dailyCapReached", out)
        # Контракт клиентов этапа 3 (mata_kvartal run_bonus.dart).
        self.assertEqual(out["loyalty"], {"awarded": 10, "monthLeft": 250, "capped": False,
                                          "text": "+10 бонусов"})
        # Уведомление на каждое начисление (ТЗ §6) — тип, который показывают ленты.
        from notifications.models import Notification

        n = Notification.objects.filter(user_id=self.uid, title="+10 бонусов").get()
        self.assertEqual(n.type, "system")
        self.assertIn("пробежку", n.body)
        # Игровой счёт (км рейтингов) пишется, но деньгами не становится.
        self.assertEqual(self.balance(), 50)
        self.assertFalse(LoyaltyLot.objects.filter(user_id=self.uid,
                                                   source="legacy_activity").exists())
        self.assertFalse(LoyaltyLot.objects.filter(user_id=self.uid, source="migration").exists())
        self.assertEqual(v1.wallet(self.uid)["available"], 10)
        self.assertEqual(self.api_get("/v1/loyalty/account").json()["v1"]["available"], 10)
        # Повтор из офлайн-очереди — тот же ответ, без второго бонуса.
        again = self.post_run("on1")
        self.assertTrue(again["duplicate"])
        self.assertEqual(again["pointsAwarded"], 10)
        self.assertEqual(v1.wallet(self.uid)["available"], 10)

    def test_month_cap_fields(self):
        enable()
        config.set_value("CAP_RUNS_MONTH", 0, by="test")
        out = self.post_run("cap1")
        self.assertEqual(out["pointsAwarded"], 0)
        self.assertTrue(out["monthCapReached"])
        self.assertEqual(out["capReason"], "Лимит месяца исчерпан, обновится 1 числа")
        self.assertEqual(out["bonus"]["runsLeft"], 0)
        self.assertTrue(out["loyalty"]["capped"])
        self.assertEqual(out["loyalty"]["awarded"], 0)
        self.assertEqual(out["loyalty"]["text"], "Лимит месяца исчерпан, обновится 1 числа")
        self.assertEqual(self.balance(), 50)  # в игре засчитано

    def test_daily_cap_d107_replaced(self):
        enable()
        from runs.budget import grant

        self.assertEqual(grant(self.uid, 5000), (5000, 0, ""))

    def test_migrated_user_old_registry_not_mirrored(self):
        v1.migrate_user(self.uid, apply=True)
        enable()
        self.post_run("mig1")
        sources = set(LoyaltyLot.objects.filter(user_id=self.uid).values_list("source",
                                                                              flat=True))
        self.assertEqual(sources, {"run"})

    def test_flag_off_migrated_user_still_mirrors(self):
        v1.migrate_user(self.uid, apply=True)
        self.post_run("mir1")
        self.assertTrue(LoyaltyLot.objects.filter(user_id=self.uid,
                                                  source="legacy_activity").exists())
        self.assertFalse(Act.objects.exists())

    def test_capture_api_gives_capture_bonus(self):
        enable()
        self.post_run("cr1")
        poly = [[62.000, 129.700], [62.001, 129.700], [62.001, 129.701], [62.000, 129.701]]
        r = self.api_post("/v1/territories/capture", {
            "points": poly, "captureId": "cap-cr1", "distanceMeters": 5000.0,
            "elapsedSeconds": 1800, "runId": "cr1"})
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertEqual(body["points"], 30)
        self.assertEqual(body["bonus"]["status"], "granted")
        self.assertEqual(body["bonus"]["capturesLeft"], 2)
        self.assertEqual(v1.wallet(self.uid)["available"], 40)

    def test_workout_import_api_bonus_and_duplicate(self):
        enable()
        start = timezone.now() - timedelta(minutes=40)
        item = {"sourceId": "hc-1", "startedAtMs": int(start.timestamp() * 1000),
                "durationS": 1800, "distanceM": 5000, "sport": "running"}
        out = self.api_post("/v1/workouts/import", {"source": "healthconnect",
                                                    "items": [item]}).json()
        self.assertEqual(out["points"], 10)
        self.assertEqual(out["items"][0]["bonus"]["status"], "granted")
        self.assertEqual(out["loyalty"]["awarded"], 10)
        self.assertEqual(out["loyalty"]["monthLeft"], 250)
        # Тот же выход, записанный ещё и приложением, — бонус один раз.
        self.assertEqual(self.post_run("same-as-watch")["bonus"]["status"], "duplicate")
        self.assertEqual(v1.wallet(self.uid)["available"], 10)

    def test_track_endpoint_rechecks(self):
        enable()
        self.post_run("trk1")
        now = timezone.now()
        pts = line_track(now - timedelta(minutes=30), 1.0, 180)
        r = self.api_post("/v1/runs/track", {"runId": "trk1", "points": pts})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(Act.objects.get(ref="trk1").status, Act.SUSPICIOUS)


class SignupAndReferral(ResetConfig, ApiTestCase):
    phone = "+79990061201"

    def verify(self, phone, **extra):
        return self.client.post("/v1/auth/phone/verify",
                                data=json.dumps({"phone": phone, "code": "1234", **extra}),
                                content_type="application/json").json()

    def test_signup_bonus_once_per_phone(self):
        enable()
        out = self.verify("+79990061202")
        self.assertEqual(out["signupBonus"], 75)
        uid = out["user"]["id"]
        lot = LoyaltyLot.objects.get(user_id=uid, source="signup")
        self.assertEqual((lot.amount, lot.state, lot.status_amount), (75, "available", 0))
        self.assertEqual(v1.wallet(uid)["status_points"], 0)
        # Вход тем же номером — не регистрация.
        self.assertNotIn("signupBonus", self.verify("+79990061202"))
        # Удалил аккаунт и зарегистрировался снова — бонуса нет.
        from accounts import userdata

        userdata.erase_atomic(uid)
        Account.objects.filter(id=uid).delete()
        again = self.verify("+79990061202")
        self.assertNotIn("signupBonus", again)
        self.assertFalse(LoyaltyLot.objects.filter(source="signup",
                                                   user_id=again["user"]["id"]).exists())
        self.assertEqual(LoyaltyPhoneGrant.objects.count(), 1)

    def test_no_signup_bonus_when_off_or_for_existing(self):
        self.assertNotIn("signupBonus", self.verify("+79990061203"))
        enable()
        v1.migrate_user(self.uid, apply=True)  # перенос существующего — без бонуса
        self.assertFalse(LoyaltyLot.objects.filter(user_id=self.uid, source="signup").exists())

    def test_referral_full_path(self):
        enable()
        code = self.api_get("/v1/loyalty/referral").json()["code"]
        self.assertEqual(len(code), 6)
        out = self.verify("+79990061204", referralCode=code.lower())
        self.assertTrue(out["referral"]["ok"], out)
        invitee = out["user"]["id"]
        ref = LoyaltyReferral.objects.get(user_id=invitee)
        self.assertEqual(ref.inviter_id, self.uid)
        # Первый заказ приглашённого вышел из удержания без возврата.
        lot = LoyaltyLot.objects.create(
            user_id=invitee, amount=300, remaining=300, state="held", source="purchase",
            source_ref="SS-REF", status_amount=300,
            available_at=timezone.now() - timedelta(minutes=1), meta={"revoked": 0})
        v1.release_holds()
        ref.refresh_from_db()
        self.assertEqual(ref.status, LoyaltyReferral.REWARDED)
        self.assertEqual(v1.wallet(self.uid)["available"], 100)
        self.assertEqual(LoyaltyEvent.objects.filter(type="accrue_referral").count(), 1)
        from notifications.models import Notification

        self.assertTrue(Notification.objects.filter(user_id=self.uid,
                                                    title="+100 бонусов").exists())
        self.assertTrue(Notification.objects.filter(user_id=invitee,
                                                    title="+75 бонусов").exists())
        lot.refresh_from_db()
        self.assertEqual(lot.state, "available")
        # Связь одна: второй код не принимается.
        r = self.api_post("/v1/loyalty/referral", {"code": code},
                          token=self.new_user("+79990061204"))
        self.assertEqual(r.status_code, 400)

    def test_returned_first_order_does_not_reward(self):
        enable()
        code = activity.referral_code(self.uid)
        invitee = self.verify("+79990061205", referralCode=code)["user"]["id"]
        LoyaltyLot.objects.create(
            user_id=invitee, amount=300, remaining=200, state="held", source="purchase",
            source_ref="SS-R1", status_amount=200,
            available_at=timezone.now() - timedelta(minutes=1), meta={"revoked": 100})
        v1.release_holds()
        self.assertEqual(LoyaltyReferral.objects.get(user_id=invitee).status, "bound")
        self.assertEqual(v1.wallet(self.uid)["available"], 0)

    def test_self_invite_by_device_and_window(self):
        enable()
        code = activity.referral_code(self.uid)
        self.assertFalse(activity.bind_referral(self.uid, code)[0])
        other = self.verify("+79990061206")["user"]["id"]
        DeviceAccount.note("same-device", self.uid)
        DeviceAccount.note("same-device", other)
        ok, detail = activity.bind_referral(other, code)
        self.assertFalse(ok)
        self.assertIn("устройство", detail)
        late = self.verify("+79990061207")["user"]["id"]
        Account.objects.filter(id=late).update(created_at=timezone.now() - timedelta(days=8))
        ok, detail = activity.bind_referral(late, code)
        self.assertFalse(ok)
        self.assertIn("7 дней", detail)

    def test_referral_monthly_cap(self):
        enable()
        config.set_value("CAP_REFERRALS_MONTH", 1, by="test")
        code = activity.referral_code(self.uid)
        for i, phone in enumerate(("+79990061208", "+79990061209")):
            invitee = self.verify(phone, referralCode=code)["user"]["id"]
            LoyaltyLot.objects.create(
                user_id=invitee, amount=300, remaining=300, state="held", source="purchase",
                source_ref=f"SS-C{i}", status_amount=300,
                available_at=timezone.now() - timedelta(minutes=1), meta={"revoked": 0})
        v1.release_holds()
        self.assertEqual(sorted(LoyaltyReferral.objects.values_list("status", flat=True)),
                         ["capped", "rewarded"])
        self.assertEqual(v1.wallet(self.uid)["available"], 100)

    def test_bad_code_does_not_break_registration(self):
        enable()
        out = self.verify("+79990061210", referralCode="NOPE00")
        self.assertIn("token", out)
        self.assertFalse(out["referral"]["ok"])


class BonusQueueAdmin(ActivityBase):
    def test_page_lists_and_approves(self):
        self.go("fast", at(6), km=5, minutes=12)
        get_user_model().objects.create_superuser("owner_q", "q@t.dev", "OwnerPass!2026")
        login_admin(self.client, "owner_q", "OwnerPass!2026")
        url = reverse("runs_review")
        page = self.client.get(url + "?mode=bonus")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Бонусы на проверке")
        self.assertContains(page, "Темп быстрее 3:00")
        act = Act.objects.get(ref="fast")
        r = self.client.post(url, {"action": "bonus_approve", "act": str(act.pk),
                                   "mode": "bonus"})
        self.assertEqual(r.status_code, 302)
        act.refresh_from_db()
        self.assertEqual(act.status, Act.GRANTED)
        self.assertEqual(act.reviewed_by, "owner_q")
        self.assertEqual(self.available(), 10)

    def test_legacy_registry_untouched_by_bonus(self):
        self.go("x", at(5))
        self.assertFalse(LoyaltyTransaction.objects.filter(user_id=self.uid).exists())
