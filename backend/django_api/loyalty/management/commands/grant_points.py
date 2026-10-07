"""Ручное начисление баллов клиенту по телефону — в реестр, по которому Store считает баланс.

Зачем отдельная команда. Пока программа лояльности v1 выключена (LOYALTY_V1_ENABLED),
баланс в Store = сумма `LoyaltyTransaction` (loyalty.models.wallet_summary). Кнопка
«Ручное начисление» в админке «Программа лояльности → Участники» пишет ЛОТ v1 — при
выключенной программе Store его не видит (грабли 07.10.2026, docs/PITFALLS.md). Команда
пишет через `loyalty.models.add_txn`: свой id, замок кошелька, тратить можно сразу; при
включённой программе запись зеркалится в лоты сигналом (loyalty.signals).

    manage.py grant_points 89991234567 10000 --comment "Тестовые баллы для проверки обмена с 1С"
    manage.py grant_points +79991234567 -500 --comment "Корректировка"   # списание, не ниже нуля

Телефон — в любом написании (8…, +7…, 7…, с пробелами и дефисами). Аккаунт должен уже
существовать: баллы начисляются человеку, а не номеру — если его нет, человек сначала
входит в Store или Квартал. Источник записи — «manual»: Квартал показывает его как
«Начисление МАТА», Store (старый клиент) — общей подписью с нашим комментарием.
"""
from django.core.management.base import BaseCommand, CommandError

from accounts.models import Account, contact_phone_hash
from common.security import normalize_phone
from loyalty.models import add_txn, balance_of, wallet_summary

SOURCE = "manual"
DEFAULT_COMMENT = "Начисление МАТА вручную"


class Command(BaseCommand):
    help = "Начислить (или списать) баллы клиенту по телефону — в реестр, который видит Store"

    def add_arguments(self, parser):
        parser.add_argument("phone", help="телефон клиента в любом написании")
        parser.add_argument("amount", type=int, help="сумма: плюс — начисление, минус — списание")
        parser.add_argument("--comment", default=DEFAULT_COMMENT,
                            help="за что — видно клиенту в истории баллов")

    def handle(self, *args, **opts):
        amount = opts["amount"]
        if amount == 0:
            raise CommandError("Сумма не может быть нулём")
        comment = (opts["comment"] or "").strip()[:300] or DEFAULT_COMMENT
        phone = normalize_phone(opts["phone"])
        account = (
            Account.objects.filter(phone=phone).first()
            or Account.objects.filter(phone_hash=contact_phone_hash(phone)).first()
        )
        if account is None:
            raise CommandError(
                f"Аккаунта с телефоном {phone} нет. Баллы начисляются аккаунту, а не номеру: "
                "человек должен сначала войти в Store или Квартал."
            )
        before = balance_of(account.id)
        if amount < 0 and before + amount < 0:
            raise CommandError(
                f"Нельзя списать {-amount}: на счету {before}, в минус ручная правка не уводит."
            )
        txn = add_txn(account.id, amount, SOURCE, comment)
        w = wallet_summary(account.id)
        sign = "+" if amount > 0 else "−"
        self.stdout.write(
            f"{sign}{abs(amount)} баллов → {account.name or 'без имени'} ({account.id}), "
            f"телефон {phone}. Запись {txn.id}. Было {before}, стало {w['total']}, "
            f"можно потратить {w['spendable']}."
        )
