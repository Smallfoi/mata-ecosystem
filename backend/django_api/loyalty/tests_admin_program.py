"""Раздел админки «Программа лояльности»: страницы, сохранение настроек с историей,
валидация, товары-исключения (и их действие на списание и начисление), ручные
операции, выключатель, перенос из админки, журнал."""
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from accounts.models import Account
from catalog.models import Category, Product
from common.testutils import ApiTestCase, login_admin, verify_admin
from loyalty import config, program, v1
from loyalty.models import (
    LoyaltyEvent,
    LoyaltyLot,
    LoyaltySettingChange,
    LoyaltyStatus,
    LoyaltyTransaction,
)
from orders.lifecycle import mark_paid
from orders.models import Order
from orders.receipt import allocate
from staff.models import LEVEL_EDIT, LEVEL_VIEW, StaffAudit, StaffProfile, TabPermission

PAGES = ("loyalty_program", "loyalty_levels", "loyalty_accruals", "loyalty_products",
         "loyalty_members", "loyalty_journal", "loyalty_history")


def url(name):
    return reverse(name)


class AdminBase(TestCase):
    def setUp(self):
        cache.clear()
        User = get_user_model()
        User.objects.create_superuser("owner_lp", "o@t.dev", "OwnerPass!2026")
        login_admin(self.client, "owner_lp", "OwnerPass!2026")
        Account.objects.create(id="u_lp", name="Анна", phone="+79990004001")
        Category.objects.create(id="wear", name="Обувь")
        Category.objects.create(id="sis", name="SIS — спортивное питание")
        Category.objects.create(id="sis-gel", name="Гели", parent_id="sis")
        Product.objects.create(id="shoe", name="Кроссовки Pegasus", category_id="wear",
                               price=7000, brand="Nike", article="ART-1")
        Product.objects.create(id="gel", name="Гель SIS", category_id="sis-gel", price=500,
                               brand="SIS")

    def staff(self, level=None):
        """Сотрудник со вторым фактором; level — уровень на вкладке программы."""
        User = get_user_model()
        user = User.objects.create_user("clerk_lp@t.dev", "clerk_lp@t.dev", "ClerkPass!2026",
                                        is_staff=True)
        StaffProfile.objects.create(user=user, full_name="Кассир")
        if level:
            TabPermission.objects.create(user=user, tab="loyalty_settings", level=level)
        self.client.logout()
        self.client.force_login(user)
        verify_admin(self.client, user)
        return user


class PagesTests(AdminBase):
    def test_owner_opens_every_page(self):
        v1.accrue("u_lp", 100, v1.MANUAL, event_type="accrue_manual", status=False,
                  note="тест")
        extra = {"loyalty_members": "?uid=u_lp", "loyalty_products": "?q=Pegasus&check=gel"}
        for name in PAGES:
            r = self.client.get(url(name) + extra.get(name, ""))
            self.assertEqual(r.status_code, 200, name)
            html = r.content.decode()
            self.assertIn('class="m-card', html, name)
            self.assertIn("Программа лояльности", html, name)
        self.assertEqual(self.client.get(url("loyalty_members") + "?q=Анна").status_code, 200)
        r = self.client.get(url("loyalty_products") + "?check=gel")
        self.assertContains(r, "Гель SIS")

    def test_staff_without_tab_gets_403(self):
        self.staff()
        for name in PAGES:
            self.assertEqual(self.client.get(url(name)).status_code, 403, name)
        r = self.client.post(url("loyalty_accruals"), {"BONUS_RUN": "99"})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(config.get("BONUS_RUN"), 10)

    def test_view_level_sees_but_cannot_change(self):
        self.staff(LEVEL_VIEW)
        for name in PAGES:
            self.assertEqual(self.client.get(url(name)).status_code, 200, name)
        self.assertEqual(self.client.post(url("loyalty_accruals"),
                                          {"BONUS_RUN": "99"}).status_code, 403)
        self.assertEqual(self.client.post(url("loyalty_program"),
                                          {"action": "toggle", "value": "on",
                                           "confirm": "yes"}).status_code, 403)
        self.assertEqual(self.client.post(url("loyalty_members"),
                                          {"uid": "u_lp", "action": "accrue", "amount": "50",
                                           "comment": "x"}).status_code, 403)
        self.assertFalse(config.enabled())
        self.assertFalse(LoyaltyLot.objects.filter(user_id="u_lp").exists())

    def test_edit_level_can_change(self):
        self.staff(LEVEL_EDIT)
        r = self.client.post(url("loyalty_accruals"), {"BONUS_RUN": "11"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(config.get("BONUS_RUN"), 11)

    def test_sidebar_has_own_group(self):
        from django.conf import settings

        sections = {s.get("title"): [i["title"] for i in s["items"]]
                    for s in settings.UNFOLD["SIDEBAR"]["navigation"]}
        self.assertEqual(sections["Программа лояльности"],
                         ["Обзор", "Уровни", "Начисления", "Товары в программе", "Участники",
                          "Журнал", "История настроек"])

    def test_new_registry_key_appears_on_its_page(self):
        """Страница строится из реестра: ключ этапа 2 появится без правки шаблона."""
        spec = config.Spec(7, "Новая тестовая настройка", "int", "подсказка",
                           group="Бонусы за действия")
        with mock.patch.dict(config.SPECS, {"TEST_NEW_KEY": spec}):
            r = self.client.get(url("loyalty_accruals"))
            self.assertContains(r, "Новая тестовая настройка")
            self.assertContains(r, "TEST_NEW_KEY")
            r = self.client.post(url("loyalty_accruals"), {"TEST_NEW_KEY": "9"})
            self.assertEqual(r.status_code, 302)
            self.assertEqual(config.get("TEST_NEW_KEY"), 9)


def _levels_form(**over):
    data = {"RATE_PURCHASE__0": "5", "RATE_PURCHASE__1": "6", "RATE_PURCHASE__2": "7",
            "RATE_PURCHASE__3": "9",
            "REDEEM_CEILING__0": "15", "REDEEM_CEILING__1": "20", "REDEEM_CEILING__2": "25",
            "REDEEM_CEILING__3": "30",
            "EXPIRY_MONTHS__0": "6", "EXPIRY_MONTHS__1": "12", "EXPIRY_MONTHS__2": "12",
            "EXPIRY_MONTHS__3": "18",
            "CAP_ACTIVITY_MONTH__0": "260", "CAP_ACTIVITY_MONTH__1": "325",
            "CAP_ACTIVITY_MONTH__2": "390", "CAP_ACTIVITY_MONTH__3": "520",
            "LEVEL_THRESHOLD__0": "500", "LEVEL_THRESHOLD__1": "2000",
            "LEVEL_THRESHOLD__2": "5000", "PLATINUM_MIN_SPEND": "60000"}
    data.update(over)
    return data


class SettingsSaveTests(AdminBase):
    def test_levels_saved_in_one_go_with_history(self):
        r = self.client.post(url("loyalty_levels"), _levels_form(
            RATE_PURCHASE__0="4", LEVEL_THRESHOLD__0="600", PLATINUM_MIN_SPEND="70000",
            comment="акция осени"))
        self.assertEqual(r.status_code, 302)
        # Сразу действует (кэш сброшен).
        self.assertEqual(config.get("RATE_PURCHASE"), [0.04, 0.06, 0.07, 0.09])
        self.assertEqual(config.get("LEVEL_THRESHOLD"), [600, 2000, 5000])
        self.assertEqual(config.get("PLATINUM_MIN_SPEND"), 70000)
        changes = LoyaltySettingChange.objects.all()
        self.assertEqual(sorted(c.key for c in changes),
                         ["LEVEL_THRESHOLD", "PLATINUM_MIN_SPEND", "RATE_PURCHASE"])
        self.assertTrue(all(c.comment == "акция осени" and c.changed_by == "owner_lp"
                            for c in changes))
        self.assertTrue(StaffAudit.objects.filter(action__contains="уровни").exists())
        page = self.client.get(url("loyalty_history")).content.decode()
        self.assertIn("акция осени", page)
        self.assertIn("5% / 6% / 7% / 9%", page)  # было → стало процентами

    def test_levels_validation_saves_nothing(self):
        cases = [
            dict(REDEEM_CEILING__3="35"),                       # выше потолка 30%
            dict(RATE_PURCHASE__1="120"),                        # процент > 100
            dict(LEVEL_THRESHOLD__1="400"),                      # пороги не растут
            dict(LEVEL_THRESHOLD__1="500"),                      # равные — тоже нет
            dict(EXPIRY_MONTHS__0="6.5"),                        # нужно целое
            dict(CAP_ACTIVITY_MONTH__2="много"),                 # не число
            dict(RATE_PURCHASE__0="5", RATE_PURCHASE__2="-1"),   # отрицательное
        ]
        for over in cases:
            r = self.client.post(url("loyalty_levels"),
                                 _levels_form(**{"RATE_PURCHASE__0": "4", **over}))
            self.assertEqual(r.status_code, 200, over)
            self.assertContains(r, "Не сохранено", msg_prefix=str(over))
            self.assertFalse(LoyaltySettingChange.objects.exists(), over)
            self.assertEqual(config.get("RATE_PURCHASE"), [0.05, 0.06, 0.07, 0.09], over)

    def test_ceiling_error_explains_hard_limit(self):
        r = self.client.post(url("loyalty_levels"), _levels_form(REDEEM_CEILING__3="31"))
        self.assertContains(r, "не больше 30%")

    def test_accruals_saved_with_units(self):
        r = self.client.post(url("loyalty_accruals"), {
            "BONUS_RUN": "12", "RUN_PACE_MIN": "3:30", "STOPLOSS_COST_SHARE": "8",
            "RUN_MIN_KM": "2,5", "HOLD_DAYS": "14", "comment": ""})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(config.get("BONUS_RUN"), 12)
        self.assertEqual(config.get("RUN_PACE_MIN"), 210)
        self.assertEqual(config.get("STOPLOSS_COST_SHARE"), 0.08)
        self.assertEqual(config.get("RUN_MIN_KM"), 2.5)
        # HOLD_DAYS не менялся — истории нет.
        self.assertEqual(sorted(LoyaltySettingChange.objects.values_list("key", flat=True)),
                         ["BONUS_RUN", "RUN_MIN_KM", "RUN_PACE_MIN", "STOPLOSS_COST_SHARE"])

    def test_accruals_validation(self):
        r = self.client.post(url("loyalty_accruals"), {"BONUS_RUN": "12", "HOLD_DAYS": "1.5"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "нужно целое число")
        self.assertEqual(config.get("BONUS_RUN"), 10)  # ничего не сохранено
        r = self.client.post(url("loyalty_accruals"), {"RUN_PACE_MIN": "3:75"})
        self.assertContains(r, "мин:сек")
        self.assertFalse(LoyaltySettingChange.objects.exists())

    def test_config_strict_limits(self):
        with self.assertRaises(config.ConfigError):
            config.set_value("REDEEM_CEILING", [0.1, 0.2, 0.3, 0.35])
        # Чтение не срезает старое значение — его срезает код.
        self.assertEqual(config.validate("REDEEM_CEILING", [0.1, 0.2, 0.3, 0.35]),
                         [0.1, 0.2, 0.3, 0.35])
        with self.assertRaises(config.ConfigError):
            config.set_many({"BONUS_RUN": 5, "LEVEL_THRESHOLD": [500, 500, 600]})
        self.assertEqual(config.get("BONUS_RUN"), 10)  # всё или ничего
        self.assertEqual(config.validate("EXCLUDED_BRANDS", [" Nike ", "nike", "SIS"]),
                         ["Nike", "SIS"])


class ProductsPageTests(AdminBase):
    def test_categories_brands_products_saved_with_history(self):
        # Снимаем «можно оплачивать бонусами» у SIS; начисление оставляем везде.
        r = self.client.post(url("loyalty_products"), {
            "action": "categories", "cats": ["wear", "sis", "sis-gel"],
            "redeem_wear": "on", "redeem_sis-gel": "on",
            "accrual_wear": "on", "accrual_sis": "on", "accrual_sis-gel": "on",
            "comment": "спортпитание"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(config.get("EXCLUDED_CATEGORIES_1C"), ["sis"])
        self.assertEqual(config.get("NO_ACCRUAL_CATEGORIES_1C"), [])
        # Бренды: Nike — без начисления.
        self.client.post(url("loyalty_products"), {
            "action": "brands", "brand_0": "Nike", "brand_1": "SIS",
            "redeem_0": "on", "redeem_1": "on", "accrual_1": "on"})
        self.assertEqual(config.get("NO_ACCRUAL_BRANDS"), ["Nike"])
        self.assertEqual(config.get("EXCLUDED_BRANDS"), [])
        # Отдельный товар — в исключения оплаты и обратно.
        self.client.post(url("loyalty_products"), {"action": "product_add", "list": "redeem",
                                                   "pid": "shoe"})
        self.assertEqual(config.get("EXCLUDED_PRODUCTS"), ["shoe"])
        self.client.post(url("loyalty_products"), {"action": "product_remove",
                                                   "list": "redeem", "pid": "shoe"})
        self.assertEqual(config.get("EXCLUDED_PRODUCTS"), [])
        keys = list(LoyaltySettingChange.objects.values_list("key", flat=True))
        for key in ("EXCLUDED_CATEGORIES_1C", "NO_ACCRUAL_BRANDS", "EXCLUDED_PRODUCTS"):
            self.assertIn(key, keys)
        self.assertEqual(LoyaltySettingChange.objects.get(key="EXCLUDED_CATEGORIES_1C").comment,
                         "спортпитание")

    def test_unknown_codes_are_kept(self):
        """Код категории, которой уже нет в каталоге, не теряется при сохранении."""
        config.set_value("EXCLUDED_CATEGORIES_1C", ["gone"])
        self.client.post(url("loyalty_products"), {
            "action": "categories", "cats": ["wear", "sis", "sis-gel"],
            "redeem_wear": "on", "redeem_sis-gel": "on", "accrual_wear": "on",
            "accrual_sis": "on", "accrual_sis-gel": "on"})
        self.assertEqual(config.get("EXCLUDED_CATEGORIES_1C"), ["gone", "sis"])

    def test_explain_and_totals(self):
        config.set_value("EXCLUDED_CATEGORIES_1C", ["sis"])
        config.set_value("NO_ACCRUAL_BRANDS", ["nike"])
        ex = program.explain_product(Product.objects.get(pk="gel"))
        self.assertFalse(ex["redeem_ok"])
        self.assertEqual(ex["redeem_reason"], "excluded_category")
        self.assertIn("SIS — спортивное питание", ex["redeem_detail"])
        self.assertEqual(ex["category_path"], "SIS — спортивное питание / Гели")
        shoe = program.explain_product(Product.objects.get(pk="shoe"))
        self.assertTrue(shoe["redeem_ok"])
        self.assertEqual(shoe["accrual_reason"], "no_accrual_brand")
        totals = program.product_totals()
        self.assertEqual((totals["total"], totals["redeem_ok"], totals["redeem_off"],
                          totals["accrual_off"]), (2, 1, 1, 1))
        r = self.client.get(url("loyalty_products") + "?check=ART-1")
        self.assertContains(r, "за товары этого бренда бонусы не начисляются")

    def test_markdown_shown_as_fixed_rule(self):
        r = self.client.get(url("loyalty_products"))
        self.assertContains(r, "Уценённые товары")
        self.assertContains(r, "Доставка")


class MembersAndJournalTests(AdminBase):
    def test_manual_accrual_writes_event_not_status(self):
        r = self.client.post(url("loyalty_members"), {"uid": "u_lp", "action": "accrue",
                                                      "amount": "150", "comment": "компенсация"})
        self.assertEqual(r.status_code, 302)
        lot = LoyaltyLot.objects.get(user_id="u_lp", source=v1.MANUAL)
        self.assertEqual((lot.amount, lot.state, lot.status_amount), (150, "available", 0))
        ev = LoyaltyEvent.objects.get(type="accrue_manual")
        self.assertEqual((ev.amount, ev.note, ev.status_points_after), (150, "компенсация", 0))
        self.assertEqual(v1.status_points("u_lp"), 0)
        self.assertTrue(StaffAudit.objects.filter(action__contains="ручное начисление").exists())
        page = self.client.get(url("loyalty_members") + "?uid=u_lp")
        self.assertContains(page, "компенсация")

    def test_manual_accrual_requires_comment(self):
        self.client.post(url("loyalty_members"), {"uid": "u_lp", "action": "accrue",
                                                  "amount": "150", "comment": "  "})
        self.assertFalse(LoyaltyEvent.objects.filter(type="accrue_manual").exists())
        self.assertFalse(LoyaltyLot.objects.filter(user_id="u_lp", source=v1.MANUAL).exists())

    def test_manual_debit(self):
        v1.manual_accrue("u_lp", 200, "старт")
        self.client.post(url("loyalty_members"), {"uid": "u_lp", "action": "debit",
                                                  "amount": "500", "comment": "ошибка"})
        self.assertEqual(LoyaltyEvent.objects.filter(type="accrue_manual").count(), 1)  # отказ
        self.client.post(url("loyalty_members"), {"uid": "u_lp", "action": "debit",
                                                  "amount": "80", "comment": "ошибка кассы"})
        ev = LoyaltyEvent.objects.filter(type="accrue_manual").order_by("-created_at").first()
        self.assertEqual((ev.amount, ev.balance_after, ev.note), (-80, 120, "ошибка кассы"))
        self.assertTrue(StaffAudit.objects.filter(action__contains="ручное списание").exists())

    def test_member_card_does_not_migrate(self):
        LoyaltyTransaction.objects.create(id="tx_lp", user_id="u_lp", amount=300,
                                          source="registration")
        r = self.client.get(url("loyalty_members") + "?uid=u_lp")
        self.assertContains(r, "ещё не перенесён")
        self.assertFalse(LoyaltyStatus.objects.filter(user_id="u_lp").exists())

    def test_journal_filters_and_csv(self):
        v1.manual_accrue("u_lp", 100, "раз")
        acc = Account.objects.get(id="u_lp")
        r = self.client.get(url("loyalty_journal") + "?type=accrue_manual")
        self.assertContains(r, acc.loyalty_pseudonym)
        r = self.client.get(url("loyalty_journal") + "?type=redeem")
        self.assertContains(r, "Событий не найдено")
        r = self.client.get(url("loyalty_journal") + "?export=csv&type=accrue_manual")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/csv", r["Content-Type"])
        body = r.content.decode("utf-8-sig")
        self.assertIn("user_pseudonym", body.splitlines()[0])
        self.assertIn(acc.loyalty_pseudonym, body)
        self.assertNotIn(acc.phone, body)  # журнал обезличен
        self.assertNotIn("Анна", body)


class OverviewTests(AdminBase):
    def test_toggle_needs_confirmation_when_warnings(self):
        LoyaltyTransaction.objects.create(id="tx_ov", user_id="u_lp", amount=300,
                                          source="registration")
        self.client.post(url("loyalty_program"), {"action": "toggle", "value": "on"})
        self.assertFalse(config.enabled())  # есть непереносённые и нет исключений
        self.client.post(url("loyalty_program"), {"action": "toggle", "value": "on",
                                                  "confirm": "yes", "comment": "старт"})
        self.assertTrue(config.enabled())
        ch = LoyaltySettingChange.objects.get(key="LOYALTY_V1_ENABLED")
        self.assertEqual((ch.new_value, ch.comment), (True, "старт"))
        self.client.post(url("loyalty_program"), {"action": "toggle", "value": "off"})
        self.assertFalse(config.enabled())
        self.assertEqual(StaffAudit.objects.filter(action__startswith="лояльность: программа")
                         .count(), 2)

    def test_migration_from_admin_is_idempotent(self):
        LoyaltyTransaction.objects.create(id="tx_m1", user_id="u_lp", amount=300,
                                          source="registration")
        self.client.post(url("loyalty_program"), {"action": "migrate_dry"})
        self.assertFalse(LoyaltyStatus.objects.exists())  # сухой прогон
        page = self.client.get(url("loyalty_program")).content.decode()
        self.assertIn("Сухой прогон — ничего не записано", page)
        self.client.post(url("loyalty_program"), {"action": "migrate_apply", "confirm": "yes"})
        self.assertTrue(LoyaltyStatus.objects.filter(user_id="u_lp").exists())
        events = LoyaltyEvent.objects.count()
        lots = LoyaltyLot.objects.count()
        self.client.post(url("loyalty_program"), {"action": "migrate_apply", "confirm": "yes"})
        self.assertEqual((LoyaltyEvent.objects.count(), LoyaltyLot.objects.count()),
                         (events, lots))
        self.assertEqual(program.migration_status()["pending"], 0)
        self.assertEqual(LoyaltyLot.objects.get(user_id="u_lp", source=v1.MIGRATION).amount,
                         300)

    def test_overview_numbers(self):
        v1.manual_accrue("u_lp", 400, "раз")
        stats = program.overview()
        self.assertEqual((stats["participants"], stats["available"], stats["month_accrued"]),
                         (1, 400, 400))
        self.assertEqual(stats["levels"][0]["count"], 1)


class ExclusionServiceTests(ApiTestCase):
    """Исключения владельца реально действуют на списание и начисление."""

    phone = "+79990077101"

    def setUp(self):
        super().setUp()
        config.set_value("LOYALTY_V1_ENABLED", True, by="test")
        Category.objects.create(id="wear", name="Обувь")
        Category.objects.create(id="cert", name="Сертификаты")
        Category.objects.create(id="cert-e", name="Электронные", parent_id="cert")
        Product.objects.create(id="shoe", name="shoe", category_id="wear", price=7000,
                               brand="Nike")
        Product.objects.create(id="hoka", name="hoka", category_id="wear", price=4000,
                               brand="HOKA")
        Product.objects.create(id="sock", name="sock", category_id="wear", price=1000,
                               brand="Nike")
        Product.objects.create(id="card", name="card", category_id="cert-e", price=1000)

    def order(self, oid, items, total, points=0):
        body = {"id": oid, "total": total, "pointsRedeemed": points, "items": items,
                "deliveryCost": 0,
                "checkoutData": {"email": "b@example.test", "phone": "+79990000000"}}
        return self.api_post("/v1/orders", body)

    def pay(self, oid):
        o = Order.objects.get(user_id=self.uid, order_id=oid)
        o.payment_id = f"pay_{oid}"
        o.save(update_fields=["payment_id"])
        mark_paid(o)
        o.refresh_from_db()
        return o

    def test_brand_and_product_exclusions_change_eligible_total(self):
        items = [{"productId": "shoe", "quantity": 1}, {"productId": "hoka", "quantity": 1},
                 {"productId": "sock", "quantity": 2}]
        self.assertEqual(v1.eligibility(items)["eligible_kop"], 1300000)
        config.set_value("EXCLUDED_BRANDS", ["hoka"])        # регистр не важен
        config.set_value("EXCLUDED_PRODUCTS", ["sock"])
        q = v1.eligibility(items)
        self.assertEqual(q["eligible_kop"], 700000)
        self.assertEqual([ln["reason"] for ln in q["lines"]],
                         ["", "excluded_brand", "excluded_product"])
        p = self.api_post("/v1/loyalty/redeem-preview", {"items": items}).json()
        self.assertEqual(p["eligibleTotal"], 7000.0)
        self.assertEqual(p["lines"][1]["reason"], "excluded_brand")
        self.assertEqual(p["lines"][1]["reasonText"], "бренд исключён из оплаты бонусами")
        self.assertEqual(p["lines"][2]["reason"], "excluded_product")
        self.assertTrue(all(ln["accrues"] for ln in p["lines"]))

    def test_category_exclusion_with_subcategories(self):
        config.set_value("EXCLUDED_CATEGORIES_1C", ["cert"])
        q = v1.eligibility([{"productId": "card"}])
        self.assertEqual((q["eligible_kop"], q["lines"][0]["reason"]), (0, "excluded_category"))

    def test_no_accrual_product_gives_no_bonus(self):
        config.set_value("NO_ACCRUAL_PRODUCTS", ["sock"])
        items = [{"productId": "hoka", "quantity": 1}, {"productId": "sock", "quantity": 1}]
        p = self.api_post("/v1/loyalty/redeem-preview", {"items": items}).json()
        self.assertEqual((p["lines"][1]["accrues"], p["lines"][1]["accrualReason"]),
                         (False, "no_accrual_product"))
        self.assertEqual(self.order("SS-NA1", items, 5000).status_code, 200)
        self.pay("SS-NA1")
        lot = LoyaltyLot.objects.get(source="purchase", source_ref="SS-NA1")
        self.assertEqual(lot.amount, 200)  # 4 000 × 0,05; носки (1 000) бонусов не дают
        self.assertEqual(lot.meta["noAccrualKop"], 100000)
        ev = LoyaltyEvent.objects.get(type="accrue_purchase", source_ref="SS-NA1")
        self.assertEqual(float(ev.cash_part), 5000.0)
        self.assertIn("Без начисления", ev.note)

    def test_no_accrual_uses_cash_part_of_the_line(self):
        """Сертификат (без оплаты бонусами и без начисления) + кроссовки, оплаченные
        частично бонусами: исключается вся денежная часть сертификата."""
        config.set_value("EXCLUDED_CATEGORIES_1C", ["cert"])
        config.set_value("NO_ACCRUAL_CATEGORIES_1C", ["cert"])
        v1.accrue(self.uid, 1000, v1.MANUAL, event_type="accrue_manual", status=False)
        items = [{"productId": "shoe", "quantity": 1}, {"productId": "card", "quantity": 1}]
        r = self.order("SS-NA2", items, 7500, points=500)
        self.assertEqual(r.status_code, 200, r.content)
        self.pay("SS-NA2")
        lot = LoyaltyLot.objects.get(source="purchase", source_ref="SS-NA2")
        # cash_part 7 500, из них сертификат 1 000 → база 6 500 × 0,05 = 325.
        self.assertEqual(lot.amount, 325)

    def test_brand_no_accrual_and_return_share(self):
        config.set_value("NO_ACCRUAL_BRANDS", ["NIKE"])
        items = [{"productId": "hoka", "quantity": 1}, {"productId": "sock", "quantity": 1}]
        self.order("SS-NA3", items, 5000)
        order = self.pay("SS-NA3")
        lot = LoyaltyLot.objects.get(source="purchase", source_ref="SS-NA3")
        self.assertEqual(lot.amount, 200)
        rows = allocate(order.payload, 5000)
        # Возврат носков (без начисления) ничего не снимает, возврат HOKA — всё.
        self.assertEqual(v1.earned_share(order, rows, {1}, lot.amount), 0)
        self.assertEqual(v1.earned_share(order, rows, {0}, lot.amount), 200)

    def test_without_rules_accrual_unchanged(self):
        items = [{"productId": "hoka", "quantity": 1}, {"productId": "sock", "quantity": 1}]
        self.order("SS-NA4", items, 5000)
        order = self.pay("SS-NA4")
        lot = LoyaltyLot.objects.get(source="purchase", source_ref="SS-NA4")
        self.assertEqual(lot.amount, 250)
        self.assertIsNone(v1.earned_share(order, allocate(order.payload, 5000), {1}, 250))
