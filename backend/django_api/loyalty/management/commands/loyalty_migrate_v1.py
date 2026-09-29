"""Перенос участников в программу лояльности v1 (ТЗ 30.09.2026, решения координатора).

По умолчанию — СУХОЙ ПРОГОН: считает и показывает, ничего не пишет.
`--apply` — переносит. Идемпотентно: перенесённого второй раз не трогает.

Что делает с каждым человеком (подробно — loyalty.v1.migrate_user):
- баланс старого реестра (LoyaltyTransaction) → лот available, срок сгорания от даты
  переноса по уровню после переноса; отрицательный — долг;
- статусные = начисления за 365 дней (покупки, бег, захват, вехи, дивизион, сезон
  минус их отмены), уровень — по новым порогам (Платина — ещё покупки за 365 дней);
- псевдоним для журнала.
После переноса новые записи старого реестра по человеку зеркалятся в лоты сами.

Порядок включения программы:
1) выкатить код (программа выключена — всё работает по-старому);
2) manage.py loyalty_find_excluded_categories, проверить, затем --apply;
3) manage.py loyalty_migrate_v1 (сухой прогон), проверить цифры, затем --apply;
4) в админке «Настройки лояльности» → LOYALTY_V1_ENABLED = true.
Кого не перенесли командой (новый человек, пропуск) — перенесёт первое же
обращение к программе v1: баланс не потеряется.
"""
from collections import Counter

from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import Account
from loyalty import config, v1
from loyalty.models import LoyaltyStatus, LoyaltyTransaction


class Command(BaseCommand):
    help = "Перенос балансов и уровней в программу лояльности v1 (по умолчанию — сухой прогон)"

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="перенести (иначе только показать)")
        parser.add_argument("--user", help="только этот пользователь (id)")
        parser.add_argument("--verbose-users", action="store_true",
                            help="показать строку по каждому человеку")

    def handle(self, *args, **opts):
        apply = opts["apply"]
        now = timezone.now()
        if opts.get("user"):
            uids = [opts["user"]]
        else:
            uids = sorted(set(Account.objects.values_list("id", flat=True))
                          | set(LoyaltyTransaction.objects.values_list("user_id", flat=True)
                                .distinct()))
        done = set(LoyaltyStatus.objects.values_list("user_id", flat=True))
        levels, moved, skipped, total, held, negative = Counter(), 0, 0, 0, 0, 0
        for uid in uids:
            if not uid:
                continue
            if uid in done:
                skipped += 1
                continue
            plan = v1.migrate_user(uid, now=now, apply=apply)
            if plan.get("skipped"):
                skipped += 1
                continue
            moved += 1
            levels[plan["level_name"]] += 1
            total += plan["balance"]
            held += plan["held"]
            negative += plan["balance"] < 0
            if opts["verbose_users"]:
                self.stdout.write(
                    f"{uid}: баланс {plan['balance']} (доступно {plan['available']}, "
                    f"созревает {plan['held']}), статусные {plan['status_points']}, "
                    f"уровень {plan['level_name']}")
        if apply:
            # Псевдонимы — всем аккаунтам, даже без баллов (журнал и аналитика).
            for uid in Account.objects.filter(loyalty_pseudonym="").values_list("id", flat=True):
                v1.pseudonym(uid)
        mode = "ПЕРЕНЕСЕНО" if apply else "СУХОЙ ПРОГОН (ничего не записано; --apply — перенести)"
        self.stdout.write(self.style.SUCCESS(mode))
        self.stdout.write(f"Людей к переносу: {moved}; уже перенесены: {skipped}")
        self.stdout.write(f"Баллов переносится: {total} (из них созревают: {held}); "
                          f"с отрицательным балансом: {negative}")
        self.stdout.write("Уровни после переноса: " + ", ".join(
            f"{name} — {levels.get(name, 0)}" for name in config.LEVELS))
        self.stdout.write(f"Программа v1 сейчас: {'ВКЛЮЧЕНА' if config.enabled() else 'выключена'}")
