"""`manage.py grant_points` — ручное начисление по телефону в реестр, который видит Store.

Появилась 07.10.2026: тестеру 1С нужны были баллы на покупку, а кнопка «Ручное
начисление» в разделе «Участники» пишет лот v1, которого Store при выключенной
программе не видит.
"""
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.test import TestCase

from accounts.models import Account
from common.testutils import login_admin
from loyalty.models import LoyaltyTransaction, balance_of, wallet_summary

UID, PHONE = "u_onec_tester", "+79990005001"


def grant(*args, **opts):
    out = StringIO()
    call_command("grant_points", *args, stdout=out, **opts)
    return out.getvalue()


class GrantPointsCommandTests(TestCase):
    def setUp(self):
        Account.objects.create(id=UID, name="Тестер 1С", email="onec@t.dev", phone=PHONE)

    def test_credits_by_phone_in_any_spelling(self):
        for spelled in ("89990005001", "+7 999 000-50-01", "9990005001", "7 (999) 000 50 01"):
            with self.subTest(spelled=spelled):
                LoyaltyTransaction.objects.filter(user_id=UID).delete()
                out = grant(spelled, "10000", comment="Тест обмена с 1С")
                self.assertEqual(balance_of(UID), 10000)
                self.assertIn(UID, out)
                self.assertIn("можно потратить 10000", out)
        txn = LoyaltyTransaction.objects.get(user_id=UID)
        self.assertEqual((txn.source, txn.description), ("manual", "Тест обмена с 1С"))
        self.assertTrue(txn.id.startswith("tx_"))
        # Ручное начисление — не «за активность», созревания нет: тратить можно сразу.
        self.assertIsNone(txn.available_at)
        self.assertEqual(wallet_summary(UID)["spendable"], 10000)

    def test_default_comment_when_none_given(self):
        grant("89990005001", "100")
        self.assertEqual(LoyaltyTransaction.objects.get(user_id=UID).description,
                         "Начисление МАТА вручную")

    def test_unknown_phone_writes_nothing(self):
        with self.assertRaisesMessage(CommandError, "+79990009999"):
            grant("89990009999", "10000")
        self.assertFalse(LoyaltyTransaction.objects.exists())

    def test_debit_never_below_zero(self):
        grant("89990005001", "100", comment="старт")
        with self.assertRaisesMessage(CommandError, "на счету 100"):
            grant("89990005001", "-500", comment="слишком много")
        self.assertEqual(balance_of(UID), 100)
        grant("89990005001", "-40", comment="корректировка")
        self.assertEqual(balance_of(UID), 60)

    def test_zero_is_refused(self):
        with self.assertRaises(CommandError):
            grant("89990005001", "0")
        self.assertFalse(LoyaltyTransaction.objects.exists())


class AdminAddTransactionTests(TestCase):
    """«Баллы (транзакции) → Добавить» — вторая дорога для той же корректировки.

    Раньше `id` был только для чтения и не генерировался: первая запись сохранялась с
    пустым id, вторая — перезаписывала первую (UPDATE по пустому ключу). Теперь запись
    идёт через add_txn.
    """

    ADD = "/admin/loyalty/loyaltytransaction/add/"

    def setUp(self):
        Account.objects.create(id=UID, name="Тестер 1С", email="onec@t.dev", phone=PHONE)
        get_user_model().objects.create_superuser("owner_g", "g@t.dev", "OwnerPass!2026")
        login_admin(self.client, "owner_g", "OwnerPass!2026")

    def _add(self, amount, description):
        return self.client.post(self.ADD, {
            "user_id": UID, "amount": str(amount), "source": "manual",
            "description": description, "order_id": "", "run_id": "",
            "available_at_0": "", "available_at_1": "",
        })

    def test_add_form_opens(self):
        self.assertEqual(self.client.get(self.ADD).status_code, 200)

    def test_two_records_keep_both_and_get_real_ids(self):
        self.assertEqual(self._add(10000, "Тест обмена с 1С").status_code, 302)
        self.assertEqual(self._add(5, "ещё одна").status_code, 302)
        txns = list(LoyaltyTransaction.objects.filter(user_id=UID).order_by("amount"))
        self.assertEqual([t.amount for t in txns], [5, 10000])
        for t in txns:
            self.assertTrue(t.id.startswith("tx_"), t.id)
        self.assertEqual(balance_of(UID), 10005)
        self.assertEqual(wallet_summary(UID)["spendable"], 10005)
