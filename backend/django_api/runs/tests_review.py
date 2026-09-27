"""Разбор помеченных забегов (S-04, фаза 2).

Проверяем не «нажимается ли кнопка», а денежную часть: баллы не должны появиться
дважды при повторном одобрении и не должны остаться на счету, когда забег признали
нарушением. Плюс права: страница разбора — не место, куда попадают по прямой ссылке.
"""
import time

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from accounts.models import Account
from common.testutils import ApiTestCase
from loyalty.models import LoyaltyTransaction, balance_of
from notifications.models import DeviceAccount, Notification
from runs.models import Run
from runs.review import (approve_run, linked_accounts, pending_queryset,
                         recalculate, reject_run, runner_context)
from staff.models import LEVEL_EDIT, LEVEL_FULL, LEVEL_VIEW, StaffProfile, TabPermission

_NOW_MS = int(time.time() * 1000)
# Спид-чит: 5 км за 10 секунд — гарантированный флаг.
_CHEAT = {"distanceMeters": 5000, "elapsedSeconds": 10, "finishedAtMs": _NOW_MS}
_OK = {"distanceMeters": 5000, "elapsedSeconds": 1800, "finishedAtMs": _NOW_MS}


class QueueTests(ApiTestCase):
    """Очередь: забег попадает в неё при пометке и уходит после любого решения."""

    phone = "+79990002101"

    def _flag(self, rid="rq"):
        self.api_post("/v1/runs", {"id": rid, **_CHEAT})
        return Run.objects.get(id=rid)

    def test_flagged_run_waits_for_decision(self):
        run = self._flag()
        self.assertTrue(run.flagged)
        self.assertTrue(run.pending_review)
        self.assertIn(run, pending_queryset())

    def test_approve_removes_from_queue_and_stamps_who(self):
        run = self._flag()
        self.assertEqual(approve_run(run, by="moderator"), 50)
        run.refresh_from_db()
        self.assertFalse(run.flagged)
        self.assertFalse(run.pending_review)
        self.assertEqual(run.reviewed_by, "moderator")
        self.assertIsNotNone(run.reviewed_at)
        self.assertEqual(pending_queryset().count(), 0)

    def test_reject_removes_from_queue_but_keeps_the_flag(self):
        """Решение «нарушение» не стирает улику: забег остаётся помеченным."""
        run = self._flag()
        reject_run(run, by="moderator")
        run.refresh_from_db()
        self.assertTrue(run.flagged)          # улика на месте
        self.assertFalse(run.pending_review)  # но разобран
        self.assertEqual(run.flag_reason, "Скорость выше 40 км/ч (спуфинг/телепорт)")
        self.assertEqual(pending_queryset().count(), 0)


class PointsTests(ApiTestCase):
    """Баллы: одобрение платит один раз, нарушение возвращает выданное."""

    phone = "+79990002102"

    def test_double_approve_pays_once(self):
        self.api_post("/v1/runs", {"id": "rp1", **_CHEAT})
        run = Run.objects.get(id="rp1")
        self.assertEqual(approve_run(run), 50)
        self.assertEqual(approve_run(run), 50)   # повторное нажатие
        self.assertEqual(self.balance(), 50)

    def test_reject_takes_back_points_awarded_by_mistake(self):
        """Одобрили, потом разобрались — баланс обязан сойтись обратно."""
        self.api_post("/v1/runs", {"id": "rp2", **_CHEAT})
        run = Run.objects.get(id="rp2")
        approve_run(run)
        self.assertEqual(self.balance(), 50)

        self.assertEqual(reject_run(run), 50)
        self.assertEqual(self.balance(), 0)
        run.refresh_from_db()
        self.assertEqual(run.points_awarded, 0)
        # Историю не переписываем: обе записи на месте, гашение отдельной строкой.
        sources = list(LoyaltyTransaction.objects.filter(
            user_id=self.uid, run_id="rp2").values_list("source", "amount"))
        self.assertIn(("runnerRun", 50), sources)
        self.assertIn(("runnerRunRevoked", -50), sources)

    def test_reject_of_never_paid_run_takes_nothing(self):
        self.api_post("/v1/runs", {"id": "rp3", **_CHEAT})
        run = Run.objects.get(id="rp3")
        self.assertEqual(reject_run(run), 0)
        self.assertEqual(self.balance(), 0)


class RecalculateTests(ApiTestCase):
    """Пересчёт: чинит расхождение между забегами и начислениями, не задваивая."""

    phone = "+79990002103"

    def test_clean_account_has_nothing_to_fix(self):
        self.api_post("/v1/runs", {"id": "rr1", **_OK})
        self.assertEqual(recalculate(self.uid), {"runs": 0, "delta": 0})
        self.assertEqual(self.balance(), 50)

    def test_lost_award_is_restored(self):
        """Начисление не дошло (обрыв в фоне) — пересчёт доначисляет ровно недостающее."""
        self.api_post("/v1/runs", {"id": "rr2", **_OK})
        LoyaltyTransaction.objects.filter(user_id=self.uid, run_id="rr2").delete()
        self.assertEqual(self.balance(), 0)

        res = recalculate(self.uid)
        self.assertEqual(res, {"runs": 1, "delta": 50})
        self.assertEqual(self.balance(), 50)
        # Второй прогон уже ничего не меняет.
        self.assertEqual(recalculate(self.uid), {"runs": 0, "delta": 0})
        self.assertEqual(self.balance(), 50)

    def test_recalculate_ignores_flagged_runs(self):
        """Помеченный забег баллов не стоит — пересчёт не должен его оплачивать."""
        self.api_post("/v1/runs", {"id": "rr3", **_CHEAT})
        self.assertEqual(recalculate(self.uid), {"runs": 0, "delta": 0})
        self.assertEqual(self.balance(), 0)


class RunnerNoticeTests(ApiTestCase):
    """Бегун узнаёт, что происходит с его забегом: тишина читается как поломка."""

    phone = "+79990002104"

    def test_hold_notice_sent_once_per_day(self):
        self.api_post("/v1/runs", {"id": "rn1", **_CHEAT})
        self.api_post("/v1/runs", {"id": "rn2", **_CHEAT})
        held = Notification.objects.filter(user_id=self.uid, title="Забег на проверке")
        self.assertEqual(held.count(), 1)   # второй забег не шлёт второе письмо

    def test_decision_is_announced(self):
        self.api_post("/v1/runs", {"id": "rn3", **_CHEAT})
        approve_run(Run.objects.get(id="rn3"))
        self.assertTrue(
            Notification.objects.filter(user_id=self.uid, title="Забег подтверждён").exists()
        )

    def test_rejection_says_points_were_taken_back(self):
        self.api_post("/v1/runs", {"id": "rn4", **_CHEAT})
        run = Run.objects.get(id="rn4")
        approve_run(run)
        reject_run(run)
        note = Notification.objects.filter(user_id=self.uid, title="Забег не засчитан").first()
        self.assertIsNotNone(note)
        self.assertIn("50", note.body)


class MultiAccountTests(TestCase):
    """Мульти-аккаунт: показываем факт связи, а не выносим приговор."""

    def setUp(self):
        cache.clear()
        self.a = Account.objects.create(id="u_a", email="a@t.dev", name="Первый",
                                        phone="+79990002105")
        self.b = Account.objects.create(id="u_b", email="b@t.dev", name="Второй",
                                        phone="+79990002106")

    def test_shared_device_links_accounts(self):
        DeviceAccount.note("same-phone-token", "u_a")
        DeviceAccount.note("same-phone-token", "u_b")
        linked = linked_accounts("u_a")
        self.assertEqual([r["id"] for r in linked], ["u_b"])
        self.assertEqual(linked[0]["why"], "общее устройство")

    def test_shared_phone_links_accounts(self):
        # Новых дублей номера не бывает (уникальный индекс, аудит A03), но старые,
        # появившиеся до него, на проде могут быть — их связь и проверяем.
        from django.db import connection

        with connection.cursor() as cur:
            cur.execute("DROP INDEX IF EXISTS accounts_phone_uniq_nonempty")
        Account.objects.filter(id="u_b").update(phone=self.a.phone)
        self.assertEqual([r["id"] for r in linked_accounts("u_a")], ["u_b"])

    def test_unrelated_accounts_are_not_linked(self):
        DeviceAccount.note("token-a", "u_a")
        DeviceAccount.note("token-b", "u_b")
        self.assertEqual(linked_accounts("u_a"), [])

    def test_context_survives_deleted_account(self):
        """Забеги переживают удаление аккаунта — страница не должна падать."""
        ctx = runner_context("u_gone")
        self.assertFalse(ctx["exists"])
        self.assertEqual(ctx["name"], "u_gone")


def _device(user):
    from django_otp.plugins.otp_totp.models import TOTPDevice
    return TOTPDevice.objects.create(user=user, name="test", confirmed=True)


class ConsoleTests(TestCase):
    """Страница разбора: кто её видит и кому позволено нажимать кнопки."""

    url = "/admin/runs-review/"

    def setUp(self):
        cache.clear()
        self.owner = User.objects.create_superuser("owner", "o@t.dev", "OwnerPass!2026")
        self.staff = User.objects.create_user("mod@t.dev", "mod@t.dev",
                                              "ModPass!2026", is_staff=True)
        StaffProfile.objects.create(user=self.staff, full_name="Модератор")
        self.owner_device, self.staff_device = _device(self.owner), _device(self.staff)

        Account.objects.create(id="u_run", email="r@t.dev", name="Бегун",
                               phone="+79990002107")
        self.run = Run.objects.create(
            id="rc1", user_id="u_run", distance_m=5000, duration_s=10,
            finished_at=timezone.now(), flagged=True,
            flag_reason="Скорость выше 40 км/ч (спуфинг/телепорт)",
        )

    def _login(self, user, device):
        from django_otp import DEVICE_ID_SESSION_KEY

        self.client.force_login(user)
        session = self.client.session
        session[DEVICE_ID_SESSION_KEY] = device.persistent_id
        session.save()

    def grant(self, level):
        TabPermission.objects.update_or_create(user=self.staff, tab="runs",
                                               defaults={"level": level})

    def test_page_closed_without_the_tab(self):
        self._login(self.staff, self.staff_device)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_queue_shows_the_flagged_run(self):
        self._login(self.owner, self.owner_device)
        html = self.client.get(self.url).content.decode()
        self.assertIn("Бегун", html)
        self.assertIn("Скорость выше 40 км/ч", html)

    def test_view_level_sees_but_cannot_decide(self):
        """«Смотреть» — значит смотреть: кнопок нет и прямой POST не проходит."""
        self.grant(LEVEL_VIEW)
        self._login(self.staff, self.staff_device)
        html = self.client.get(self.url).content.decode()
        self.assertIn("Скорость выше 40 км/ч", html)
        self.assertNotIn('value="approve"', html)

        r = self.client.post(self.url, {"action": "approve", "run": "rc1"})
        self.assertEqual(r.status_code, 403)
        self.run.refresh_from_db()
        self.assertTrue(self.run.flagged)

    def test_edit_level_decides_but_cannot_block(self):
        self.grant(LEVEL_EDIT)
        self._login(self.staff, self.staff_device)

        r = self.client.post(self.url, {"action": "approve", "run": "rc1"})
        self.assertEqual(r.status_code, 302)          # POST → redirect, F5 не повторит
        self.run.refresh_from_db()
        self.assertFalse(self.run.flagged)
        self.assertEqual(balance_of("u_run"), 50)

        r = self.client.post(self.url, {"action": "block", "uid": "u_run"})
        self.assertEqual(r.status_code, 403)
        self.assertFalse(Account.objects.get(id="u_run").is_blocked)

    def test_blocking_needs_the_accounts_tab_too(self):
        """Блокировка отрезает вход — это власть над учётной записью.

        Полные права на «Забеги» её не дают: иначе модератор бега управлял бы
        людьми в обход выданных вкладок (D-63).
        """
        self.grant(LEVEL_FULL)
        self._login(self.staff, self.staff_device)

        html = self.client.get(self.url).content.decode()
        self.assertNotIn('value="block"', html)

        r = self.client.post(self.url, {"action": "block", "uid": "u_run"})
        self.assertEqual(r.status_code, 403)
        self.assertFalse(Account.objects.get(id="u_run").is_blocked)

    def test_block_and_unblock_with_both_tabs(self):
        self.grant(LEVEL_FULL)
        TabPermission.objects.update_or_create(user=self.staff, tab="accounts",
                                               defaults={"level": LEVEL_EDIT})
        self._login(self.staff, self.staff_device)

        self.client.post(self.url, {"action": "block", "uid": "u_run"})
        acc = Account.objects.get(id="u_run")
        self.assertTrue(acc.is_blocked)
        self.assertTrue(acc.block_reason)

        self.client.post(self.url, {"action": "unblock", "uid": "u_run"})
        self.assertFalse(Account.objects.get(id="u_run").is_blocked)

    def test_owner_may_block(self):
        """У владельца все вкладки — кнопка на месте."""
        self._login(self.owner, self.owner_device)
        self.client.post(self.url, {"action": "block", "uid": "u_run"})
        self.assertTrue(Account.objects.get(id="u_run").is_blocked)

    def test_decisions_are_written_to_the_access_journal(self):
        from staff.models import StaffAudit

        self.grant(LEVEL_EDIT)
        self._login(self.staff, self.staff_device)
        self.client.post(self.url, {"action": "approve", "run": "rc1"})
        self.assertTrue(StaffAudit.objects.filter(action__contains="rc1").exists())

    def test_clear_review_mark(self):
        Account.objects.filter(id="u_run").update(needs_review=True)
        self.grant(LEVEL_EDIT)
        self._login(self.staff, self.staff_device)
        self.client.post(self.url, {"action": "clear_review", "uid": "u_run"})
        self.assertFalse(Account.objects.get(id="u_run").needs_review)
