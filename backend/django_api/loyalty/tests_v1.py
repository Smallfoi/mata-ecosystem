"""Программа лояльности v1 (ТЗ 30.09.2026), этап 1 — ядро на сервере.

Приёмка ТЗ §6 (числа из ТЗ): №1, 2, 3, 6, 7, 8, 9; плюс выключатель, журнал
только на добавление, потолок 0,30 кодом, идемпотентный перенос.
"""
import os
from datetime import datetime, timedelta
from io import StringIO
from unittest import mock
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.db import connection, transaction
from django.test import TestCase
from django.utils import timezone

from catalog.models import Category, Product
from common.testutils import ApiTestCase, login_admin
from loyalty import config, v1
from loyalty.models import (
    LoyaltyEvent,
    LoyaltyLot,
    LoyaltyRedemption,
    LoyaltySetting,
    LoyaltySettingChange,
    LoyaltyStatus,
    LoyaltyTransaction,
    add_txn,
)
from orders.lifecycle import mark_canceled, mark_paid
from orders.models import Order
from orders.returns import make_return

YKT = ZoneInfo("Asia/Yakutsk")
_YK = {"YOOKASSA_SHOP_ID": "654321", "YOOKASSA_SECRET_KEY": "test_secret_key"}


def _refund_ok(method, url, payload=None, headers=None):
    return {"id": "rf_" + headers["Idempotence-Key"][:8], "status": "succeeded"}


def enable():
    config.set_value("LOYALTY_V1_ENABLED", True, by="test")


class V1Case(ApiTestCase):
    phone = "+79990077001"

    def setUp(self):
        super().setUp()
        enable()
        Category.objects.create(id="wear", name="Обувь")
        Category.objects.create(id="sis", name="SIS — спортивное питание")
        Category.objects.create(id="sis-gel", name="Гели", parent_id="sis")
        config.set_value("EXCLUDED_CATEGORIES_1C", ["sis"], by="test")
        self.now = timezone.now()

    # — помощники —
    def product(self, pid, price, category="wear", **kw):
        return Product.objects.create(id=pid, name=pid, category_id=category, price=price, **kw)

    def set_level(self, level):
        st = v1.get_status(self.uid)
        st.level, st.level_until = level, timezone.now() + timedelta(days=365)
        st.save()

    def give(self, amount, status=False, now=None, source=v1.MANUAL):
        return v1.accrue(self.uid, amount, source, event_type="accrue_manual", status=status,
                         now=now)

    def order(self, oid, items, total, points=0, delivery=0):
        body = {"id": oid, "total": total, "pointsRedeemed": points, "items": items,
                "deliveryCost": delivery,
                "checkoutData": {"email": "b@example.test", "phone": "+79990000000"}}
        return self.api_post("/v1/orders", body)

    def pay(self, oid):
        o = Order.objects.get(user_id=self.uid, order_id=oid)
        o.payment_id = f"pay_{oid}"
        o.save(update_fields=["payment_id"])
        mark_paid(o)
        o.refresh_from_db()
        return o

    def deliver(self, oid, at):
        Order.objects.filter(user_id=self.uid, order_id=oid).update(
            status="delivered", onec_status="delivered", onec_status_at=at)

    def ret(self, order, lines):
        with mock.patch.dict(os.environ, _YK), \
                mock.patch("orders.payment._http", side_effect=_refund_ok):
            return make_return(order.pk, lines, by="tester")

    def wallet(self):
        return v1.wallet(self.uid)


class Acceptance(V1Case):
    def test_1_basic_purchase_held_then_available(self):
        """№1: Базовый, 7 500 ₽ без списания → лот 375 held, через 14 дней available,
        статусные 375."""
        self.product("shoe", 7500)
        r = self.order("SS-1", [{"productId": "shoe", "quantity": 1}], 7500)
        self.assertEqual(r.status_code, 200, r.content)
        self.pay("SS-1")
        lot = LoyaltyLot.objects.get(user_id=self.uid, source="purchase")
        self.assertEqual((lot.amount, lot.state), (375, "held"))
        w = self.wallet()
        self.assertEqual((w["available"], w["held"], w["status_points"]), (0, 375, 375))

        self.deliver("SS-1", self.now + timedelta(days=2))
        v1.release_holds(self.now + timedelta(days=13, hours=23))
        lot.refresh_from_db()
        self.assertEqual(lot.state, "held", "раньше 14 дней не выходит")
        v1.release_holds(self.now + timedelta(days=14, minutes=1))
        lot.refresh_from_db()
        self.assertEqual(lot.state, "available")
        self.assertEqual(self.wallet()["available"], 375)
        self.assertTrue(LoyaltyEvent.objects.filter(type="hold_release", amount=375).exists())

    def test_1b_not_delivered_stays_held(self):
        """Решение координатора: не получен — держится; получен поздно — +7 дней."""
        self.product("shoe", 7500)
        self.order("SS-1B", [{"productId": "shoe"}], 7500)
        self.pay("SS-1B")
        v1.release_holds(self.now + timedelta(days=30))
        self.assertEqual(LoyaltyLot.objects.get(source="purchase").state, "held")
        self.deliver("SS-1B", self.now + timedelta(days=12))
        v1.release_holds(self.now + timedelta(days=18))
        self.assertEqual(LoyaltyLot.objects.get(source="purchase").state, "held")
        v1.release_holds(self.now + timedelta(days=19, minutes=1))
        self.assertEqual(LoyaltyLot.objects.get(source="purchase").state, "available")

    def test_2_platinum_with_excluded_category(self):
        """№2: Платина, баланс 5 000, заказ 7 500 ₽ с питанием на 500 ₽ → eligible 7 000,
        redeem_max 2 100; начисление на cash_part 5 400 × 0,09 = 486."""
        self.product("shoe", 7000)
        self.product("gel", 500, category="sis-gel")  # подгруппа исключённой группы
        self.set_level(v1.PLATINUM)
        self.give(5000)
        items = [{"productId": "shoe", "quantity": 1}, {"productId": "gel", "quantity": 1}]

        p = self.api_post("/v1/loyalty/redeem-preview", {"items": items}).json()
        self.assertTrue(p["programV1"])
        self.assertEqual((p["eligibleTotal"], p["redeemMax"], p["canRedeem"]), (7000.0, 2100, True))
        self.assertEqual([ln["eligible"] for ln in p["lines"]], [True, False])
        self.assertEqual(p["lines"][1]["reason"], "excluded_category")

        too_much = self.order("SS-2X", items, 5399, points=2101)
        self.assertEqual(too_much.status_code, 400)
        self.assertIn("2100", too_much.json()["detail"])

        r = self.order("SS-2", items, 5400, points=2100)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self.wallet()["available"], 2900)
        red = LoyaltyRedemption.objects.get(order_id="SS-2")
        self.assertEqual((red.state, red.eligible_kop), ("blocked", 700000))
        self.pay("SS-2")
        red.refresh_from_db()
        self.assertEqual(red.state, "spent")
        lot = LoyaltyLot.objects.get(source="purchase", source_ref="SS-2")
        self.assertEqual(lot.amount, 486)
        ev = LoyaltyEvent.objects.get(type="accrue_purchase")
        self.assertEqual((float(ev.cash_part), float(ev.eligible_total), float(ev.order_total)),
                         (5400.0, 7000.0, 7500.0))

    def test_2b_markdown_not_eligible_and_delivery_ignored(self):
        self.product("old", 1000, old_price=1500)
        self.product("shoe", 4000)
        self.give(1000)
        q = v1.quote(self.uid, [{"productId": "old"}, {"productId": "shoe"}])
        self.assertEqual(q["eligible_kop"], 400000)
        self.assertEqual(q["redeemMax"], 600)  # 0,15 × 4 000, уценка не в счёт
        self.assertEqual(q["lines"][0]["reason"], "markdown")
        # Доставка: cash_part без неё.
        r = self.order("SS-D", [{"productId": "shoe"}], 4300, delivery=300)
        self.assertEqual(r.status_code, 200, r.content)
        self.pay("SS-D")
        self.assertEqual(LoyaltyLot.objects.get(source="purchase").amount, 200)  # 4000×0,05

    def test_3_silver_250_cannot_redeem(self):
        """№3: Серебро, баланс 250 → списание недоступно (< 300)."""
        self.product("shoe", 5000)
        self.set_level(v1.SILVER)
        self.give(250)
        p = self.api_post("/v1/loyalty/redeem-preview",
                          {"items": [{"productId": "shoe"}]}).json()
        self.assertFalse(p["canRedeem"])
        self.assertIn("300", p["reason"])
        r = self.order("SS-3", [{"productId": "shoe"}], 4750, points=250)
        self.assertEqual(r.status_code, 400)
        self.assertIn("300", r.json()["detail"])
        self.assertEqual(self.wallet()["available"], 250)
        self.assertFalse(LoyaltyRedemption.objects.exists())

    def test_6a_return_on_day_10(self):
        """№6: возврат на день 10 → лот покупки cancelled, списанные вернулись в
        исходные лоты (с их датами)."""
        self.product("shoe", 3000)
        source = self.give(1000)
        expires = source.expires_at
        r = self.order("SS-6", [{"productId": "shoe"}], 2700, points=300)
        self.assertEqual(r.status_code, 200, r.content)
        order = self.pay("SS-6")
        purchase = LoyaltyLot.objects.get(source="purchase")
        self.assertEqual((purchase.amount, purchase.state), (135, "held"))
        self.assertEqual(self.wallet()["available"], 700)

        ret = self.ret(order, [0])
        self.assertEqual(ret.status, "done")
        self.assertEqual((ret.points_returned, ret.points_revoked), (300, 135))
        purchase.refresh_from_db()
        source.refresh_from_db()
        self.assertEqual(purchase.state, "cancelled")
        self.assertEqual(purchase.status_amount, 0, "статусные за покупку аннулированы")
        self.assertEqual((source.remaining, source.expires_at), (1000, expires))
        w = self.wallet()
        self.assertEqual((w["available"], w["held"], w["status_points"]), (1000, 0, 0))

    def test_6b_return_on_day_20_goes_negative(self):
        """№6: возврат на день 20 → списание с баланса, при нехватке — минус,
        который гасится следующими начислениями."""
        self.product("shoe", 3000)
        self.product("coat", 6000)
        self.give(750)
        self.order("SS-61", [{"productId": "shoe"}], 3000)
        first = self.pay("SS-61")
        self.deliver("SS-61", self.now + timedelta(days=1))
        v1.release_holds(self.now + timedelta(days=14, minutes=1))
        self.assertEqual(self.wallet()["available"], 900)
        r = self.order("SS-62", [{"productId": "coat"}], 5100, points=900)
        self.assertEqual(r.status_code, 200, r.content)
        self.pay("SS-62")
        self.assertEqual(self.wallet()["available"], 0)

        ret = self.ret(first, [0])
        self.assertEqual(ret.points_revoked, 150)
        self.assertEqual(self.wallet()["available"], -150)
        self.assertEqual(self.wallet()["redeemable"], 0)
        self.give(200)
        self.assertEqual(self.wallet()["available"], 50)
        debt = LoyaltyLot.objects.get(source="debt")
        self.assertEqual((debt.remaining, debt.state), (0, "spent"))

    def test_6c_partial_return_shares_by_eligible_total(self):
        """Возврат позиции: списанные делятся по доле в eligible_total — исключённой
        категории бонусы не возвращаются."""
        self.product("shoe", 3000)
        self.product("gel", 500, category="sis")
        self.give(1000)
        r = self.order("SS-63", [{"productId": "shoe"}, {"productId": "gel"}], 3050,
                       points=450)
        self.assertEqual(r.status_code, 200, r.content)
        order = self.pay("SS-63")
        gel = self.ret(order, [1])
        self.assertEqual(gel.points_returned, 0)
        shoe = self.ret(order, [0])
        self.assertEqual(shoe.points_returned, 450)
        self.assertEqual(self.wallet()["available"], 1000)

    def test_7_levels_by_status_points_and_purchases(self):
        """№7: 2 000 статусных без покупок → Золото; 5 000 без покупок → Золото;
        5 000 и покупки 60 000 → Платина."""
        self.give(2000, status=True)
        self.assertEqual(v1.get_status(self.uid).level, v1.GOLD)
        self.give(3000, status=True)
        self.assertEqual(v1.get_status(self.uid).level, v1.GOLD)
        Order.objects.create(user_id=self.uid, order_id="SS-BIG", total=60000,
                             payment_status="paid", status="delivered", payload={})
        self.give(10, status=True)
        st = v1.get_status(self.uid)
        self.assertEqual(st.level, v1.PLATINUM)
        self.assertTrue(LoyaltyEvent.objects.filter(type="level_up", level_after=3).exists())

    def test_8_platinum_decays_one_level(self):
        """№8: через 365 дней после Платины без активности → Золото, не Базовый."""
        Order.objects.create(user_id=self.uid, order_id="SS-BIG", total=60000,
                             payment_status="paid", status="delivered", payload={})
        self.give(5000, status=True)
        self.assertEqual(v1.get_status(self.uid).level, v1.PLATINUM)
        v1.recheck_levels(self.now + timedelta(days=364))
        self.assertEqual(v1.get_status(self.uid).level, v1.PLATINUM)
        later = self.now + timedelta(days=366)
        v1.recheck_levels(later)
        self.assertEqual(v1.get_status(self.uid).level, v1.GOLD)
        v1.recheck_levels(later + timedelta(days=1))
        self.assertEqual(v1.get_status(self.uid).level, v1.GOLD, "минус один уровень, не больше")
        self.assertEqual(LoyaltyEvent.objects.filter(type="level_down").count(), 1)

    def test_9_expiry_follows_level(self):
        """№9: лот Базового от 1 марта → сгорает 1 сентября; повышение до Серебра
        1 июня → сгорает 1 марта следующего года."""
        march = datetime(2027, 3, 1, 12, 0, tzinfo=YKT)
        lot = self.give(100, status=True, now=march)
        self.assertEqual(timezone.localtime(lot.expires_at).date().isoformat(), "2027-09-01")
        self.give(400, status=True, now=datetime(2027, 6, 1, 12, 0, tzinfo=YKT))
        self.assertEqual(v1.get_status(self.uid).level, v1.SILVER)
        lot.refresh_from_db()
        self.assertEqual(timezone.localtime(lot.expires_at).date().isoformat(), "2028-03-01")

    def test_expire_and_warn(self):
        lot = self.give(400, now=self.now - timedelta(days=170))
        with mock.patch("notifications.models.create_notification") as note:
            v1.warn_expiring(self.now)
            v1.warn_expiring(self.now + timedelta(days=1))  # не чаще раза в неделю
        self.assertEqual(note.call_count, 1)
        v1.expire_lots(lot.expires_at + timedelta(minutes=1))
        lot.refresh_from_db()
        self.assertEqual((lot.state, lot.remaining), ("expired", 0))
        self.assertTrue(LoyaltyEvent.objects.filter(type="expire", amount=-400).exists())

    def test_unpaid_order_unblocks_bonuses(self):
        self.product("shoe", 3000)
        source = self.give(1000)
        self.order("SS-U", [{"productId": "shoe"}], 2700, points=300)
        self.assertEqual(self.wallet()["available"], 700)
        mark_canceled(Order.objects.get(order_id="SS-U"))
        source.refresh_from_db()
        self.assertEqual(source.remaining, 1000)
        self.assertEqual(LoyaltyRedemption.objects.get(order_id="SS-U").state, "released")
        # Прежний /loyalty/redeem второй раз не спишет и не сломается.
        r = self.api_post("/v1/loyalty/redeem", {"amount": 300, "orderId": "SS-U"})
        self.assertEqual(r.status_code, 400)

    def test_legacy_redeem_endpoint_dedupes_v1(self):
        self.product("shoe", 3000)
        self.give(1000)
        self.order("SS-L", [{"productId": "shoe"}], 2700, points=300)
        r = self.api_post("/v1/loyalty/redeem", {"amount": 300, "orderId": "SS-L"}).json()
        self.assertTrue(r["deduped"])
        self.assertEqual(self.wallet()["available"], 700)

    def test_account_payload_shows_v1(self):
        self.give(500, status=True)
        d = self.api_get("/v1/loyalty/account").json()
        self.assertTrue(d["programV1"])
        self.assertEqual((d["balance"], d["level"]), (500, "silver"))
        self.assertEqual(d["v1"]["statusPoints"], 500)
        self.assertEqual(d["v1"]["lots"][0]["remaining"], 500)
        # Уровни с привилегиями — из настроек, без процентных скидок (этап 3, клиенты).
        levels = d["v1"]["levels"]
        self.assertEqual([lv["key"] for lv in levels], ["basic", "silver", "gold", "platinum"])
        self.assertEqual([lv["threshold"] for lv in levels], [0, 500, 2000, 5000])
        self.assertEqual(levels[3]["minSpend"], 60000)
        self.assertEqual(levels[0]["minSpend"], 0)
        self.assertEqual([lv["purchaseRate"] for lv in levels], [0.05, 0.06, 0.07, 0.09])
        self.assertEqual([lv["redeemCeiling"] for lv in levels], [0.15, 0.20, 0.25, 0.30])
        self.assertEqual([lv["expiryMonths"] for lv in levels], [6, 12, 12, 18])
        # Выше 30% сохранить нельзя (#853); значение в таблице в обход — код срезает.
        LoyaltySetting.objects.update_or_create(
            key="REDEEM_CEILING", defaults={"value": [0.15, 0.2, 0.25, 0.5]})
        config.invalidate()
        from django.core.cache import cache

        cache.clear()  # карточка лояльности кэшируется по пользователю
        d = self.api_get("/v1/loyalty/account").json()
        self.assertEqual(d["v1"]["levels"][3]["redeemCeiling"], 0.30)  # потолок кодом

    def test_reserve_counter(self):
        self.give(1000)
        self.assertEqual(float(v1.reserve_rub()), 310.0)


class Switch(ApiTestCase):
    """Выключатель: пока LOYALTY_V1_ENABLED выключен — поведение прежнее."""

    phone = "+79990077002"

    def test_disabled_by_default(self):
        self.assertFalse(config.enabled())

    def test_flag_off_keeps_old_rules(self):
        Product.objects.create(id="shoe", name="shoe", category_id="c", price=1000)
        add_txn(self.uid, 200, "runnerRun", "бег", available_at=None)
        body = {"id": "SS-OFF", "total": 950, "pointsRedeemed": 50,
                "items": [{"productId": "shoe", "quantity": 1}],
                "checkoutData": {"email": "b@example.test"}}
        r = self.api_post("/v1/orders", body)
        self.assertEqual(r.status_code, 200, r.content)  # 50 < 300, но правила старые
        o = Order.objects.get(order_id="SS-OFF")
        o.payment_id = "p"
        o.save()
        mark_paid(o)
        self.assertTrue(LoyaltyTransaction.objects.filter(source="purchase").exists())
        self.assertTrue(LoyaltyTransaction.objects.filter(source="registration").exists())
        self.assertFalse(LoyaltyLot.objects.exists())
        self.assertFalse(LoyaltyStatus.objects.exists())
        self.assertFalse(self.api_get("/v1/loyalty/account").json()["programV1"])
        p = self.api_post("/v1/loyalty/redeem-preview", {"items": []}).json()
        self.assertFalse(p["programV1"])

    def test_flag_on_stops_first_order_bonus(self):
        enable()
        Product.objects.create(id="shoe", name="shoe", category_id="c", price=1000)
        self.api_post("/v1/orders", {"id": "SS-ON", "total": 1000,
                                     "items": [{"productId": "shoe"}],
                                     "checkoutData": {"email": "b@example.test"}})
        o = Order.objects.get(order_id="SS-ON")
        mark_paid(o)
        self.assertFalse(LoyaltyTransaction.objects.filter(user_id=self.uid).exists())
        self.assertEqual(LoyaltyLot.objects.get(source="purchase").amount, 50)
        self.assertFalse(v1.legacy_award_allowed("runnerDivision"))
        self.assertTrue(v1.legacy_award_allowed("runnerRun"))


class Rules(TestCase):
    def test_hard_ceiling_cannot_be_raised(self):
        # Сохранить выше потолка нельзя (админка и set_value отклоняют) ...
        with self.assertRaises(config.ConfigError):
            config.set_value("REDEEM_CEILING", [0.5, 0.6, 0.7, 0.9], by="test")
        # ... а если такое значение оказалось в таблице в обход — код его срезает.
        LoyaltySetting.objects.update_or_create(key="REDEEM_CEILING",
                                                defaults={"value": [0.5, 0.6, 0.7, 0.9]})
        config.invalidate()
        self.assertEqual(config.redeem_ceiling(3), 0.30)
        self.assertEqual(config.redeem_ceiling(0), 0.30)
        Product.objects.create(id="p", name="p", category_id="c", price=1000)
        v1.accrue("u_ceil", 5000, v1.MANUAL, event_type="accrue_manual", status=False)
        self.assertEqual(v1.quote("u_ceil", [{"productId": "p"}])["redeemMax"], 300)

    def test_settings_validated_and_versioned(self):
        with self.assertRaises(config.ConfigError):
            config.set_value("REDEEM_CEILING", [0.1, 2, 0.3, 0.3])
        with self.assertRaises(config.ConfigError):
            config.set_value("LEVEL_THRESHOLD", [5000, 2000, 500])
        config.set_value("REDEEM_MIN", 200, by="owner", comment="акция")
        config.set_value("REDEEM_MIN", 250, by="owner")
        self.assertEqual(config.get("REDEEM_MIN"), 250)
        changes = list(LoyaltySettingChange.objects.filter(key="REDEEM_MIN").order_by("id"))
        self.assertEqual([(c.old_value, c.new_value) for c in changes], [(None, 200), (200, 250)])
        self.assertEqual(changes[0].changed_by, "owner")

    def test_journal_is_append_only(self):
        v1.accrue("u_j", 100, v1.MANUAL, event_type="accrue_manual", status=False)
        ev = LoyaltyEvent.objects.get()
        self.assertTrue(ev.rule_version.startswith("tz-v1:"))
        self.assertTrue(ev.user_pseudonym)
        ev.amount = 999
        with self.assertRaises(PermissionDenied):
            ev.save()
        with self.assertRaises(PermissionDenied):
            ev.delete()
        with self.assertRaises(PermissionDenied):
            LoyaltyEvent.objects.filter(pk=ev.pk).update(amount=1)
        with self.assertRaises(PermissionDenied):
            LoyaltyEvent.objects.all().delete()
        if connection.vendor == "postgresql":
            with self.assertRaises(Exception), transaction.atomic():
                with connection.cursor() as cur:
                    cur.execute("UPDATE loyalty_events SET amount = 1")
        self.assertEqual(LoyaltyEvent.objects.get().amount, 100)

    def test_add_months_clamps_day(self):
        jan31 = datetime(2027, 1, 31, 10, 0, tzinfo=YKT)
        self.assertEqual(timezone.localtime(v1.add_months(jan31, 1)).date().isoformat(),
                         "2027-02-28")


class Migration(TestCase):
    """Перенос: сухой прогон ничего не пишет; --apply идемпотентен; дальше старый
    реестр зеркалится в лоты без двойного счёта."""

    uid = "u_mig"

    def setUp(self):
        from accounts.models import Account

        # Настройки кэшируются на минуту, откат транзакции теста кэш не сбрасывает:
        # «программа включена» из соседнего теста не должна сюда протечь (с этапа 2
        # от выключателя зависит и зеркало бега/захвата).
        config.invalidate()
        Account.objects.create(id=self.uid, email="m@t.dev", phone="+79990077003")
        add_txn(self.uid, 300, "purchase", "Покупка", "SS-OLD", available_at=None)
        add_txn(self.uid, 250, "runnerRun", "бег", None, "run-1")  # созревает 3 дня
        add_txn(self.uid, 20, "registration", "бонус первого заказа", "SS-OLD", available_at=None)
        add_txn(self.uid, -100, "redeem", "оплата", "SS-OLD2", available_at=None)

    def _run(self, *args):
        out = StringIO()
        call_command("loyalty_migrate_v1", *args, stdout=out)
        return out.getvalue()

    def test_dry_run_then_apply_is_idempotent(self):
        out = self._run()
        self.assertIn("СУХОЙ ПРОГОН", out)
        self.assertFalse(LoyaltyStatus.objects.exists())
        self._run("--apply")
        lots = LoyaltyLot.objects.filter(user_id=self.uid).count()
        w = v1.wallet(self.uid)
        self.assertEqual((w["available"], w["held"]), (220, 250))
        self.assertEqual(w["status_points"], 550)  # покупка + бег; бонус — не статусные
        self.assertEqual(w["level"], v1.SILVER)
        migration = LoyaltyLot.objects.get(user_id=self.uid, source="migration")
        self.assertEqual(migration.expires_at, v1.add_months(migration.accrued_at, 12))
        self.assertIn("уже перенесены: 1", self._run("--apply"))
        self.assertEqual(LoyaltyLot.objects.filter(user_id=self.uid).count(), lots)
        self.assertEqual(v1.wallet(self.uid)["available"], 220)
        from accounts.models import Account

        self.assertTrue(Account.objects.get(id=self.uid).loyalty_pseudonym)

    def test_legacy_writes_after_migration_are_mirrored_once(self):
        self._run("--apply")
        add_txn(self.uid, 40, "runnerTerritory", "захват", None, "cap-1")
        add_txn(self.uid, -250, "runnerRunRevoked", "отзыв", None, "run-1")
        w = v1.wallet(self.uid)
        self.assertEqual(w["held"], 40)  # захват созревает; отозванный бег снят
        self.assertEqual(w["available"], 220)
        legacy_total = sum(LoyaltyTransaction.objects.filter(user_id=self.uid)
                           .values_list("amount", flat=True))
        self.assertEqual(w["available"] + w["held"], legacy_total)

    def test_lazy_migration_on_first_touch(self):
        enable()
        self.assertEqual(v1.wallet(self.uid)["available"], 220)
        self.assertEqual(LoyaltyStatus.objects.filter(user_id=self.uid).count(), 1)


class AdminPages(TestCase):
    def setUp(self):
        get_user_model().objects.create_superuser("owner_loy", "o@t.dev", "OwnerPass!2026")
        login_admin(self.client, "owner_loy", "OwnerPass!2026")
        v1.accrue("u_adm", 100, v1.MANUAL, event_type="accrue_manual", status=False)

    def test_pages_open_and_setting_change_is_logged(self):
        for url in ("/admin/loyalty/loyaltysetting/", "/admin/loyalty/loyaltyevent/",
                    "/admin/loyalty/loyaltylot/", "/admin/loyalty/loyaltystatus/",
                    "/admin/loyalty/loyaltyredemption/", "/admin/loyalty/loyaltysettingchange/",
                    "/admin/loyalty/loyaltysetting/REDEEM_MIN/change/"):
            r = self.client.get(url)
            self.assertEqual(r.status_code, 200, url)
        self.assertTrue(LoyaltySetting.objects.filter(key="LOYALTY_V1_ENABLED").exists())
        r = self.client.post("/admin/loyalty/loyaltysetting/REDEEM_MIN/change/",
                             {"value": "350", "comment": "проверка"})
        self.assertEqual(r.status_code, 302, r.content[:500])
        self.assertEqual(config.get("REDEEM_MIN"), 350)
        change = LoyaltySettingChange.objects.get(key="REDEEM_MIN")
        self.assertEqual((change.new_value, change.changed_by, change.comment),
                         (350, "owner_loy", "проверка"))
        bad = self.client.post("/admin/loyalty/loyaltysetting/REDEEM_CEILING/change/",
                               {"value": "[1, 2]"})
        self.assertEqual(bad.status_code, 200)  # форма с ошибкой, не сохранено
        self.assertEqual(config.get("REDEEM_CEILING"), [0.15, 0.20, 0.25, 0.30])
        ev = LoyaltyEvent.objects.first()
        r = self.client.post(f"/admin/loyalty/loyaltyevent/{ev.pk}/delete/", {"post": "yes"})
        self.assertEqual(r.status_code, 403)
        self.assertTrue(LoyaltyEvent.objects.filter(pk=ev.pk).exists())
