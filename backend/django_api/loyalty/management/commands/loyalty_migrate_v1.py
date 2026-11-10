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
4) в админке «Программа лояльности → Обзор» включить программу.
(Шаги 2–4 есть и кнопками в админке: «Товары в программе», «Обзор».)
Кого не перенесли командой (новый человек, пропуск) — перенесёт первое же
обращение к программе v1: баланс не потеряется.
"""
from django.core.management.base import BaseCommand

from loyalty import config, program


class Command(BaseCommand):
    help = "Перенос балансов и уровней в программу лояльности v1 (по умолчанию — сухой прогон)"

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="перенести (иначе только показать)")
        parser.add_argument("--user", help="только этот пользователь (id)")
        parser.add_argument("--verbose-users", action="store_true",
                            help="показать строку по каждому человеку")

    def handle(self, *args, **opts):
        apply = opts["apply"]

        def line(uid, plan):
            self.stdout.write(
                f"{uid}: баланс {plan['balance']} (доступно {plan['available']}, "
                f"созревает {plan['held']}), статусные {plan['status_points']}, "
                f"уровень {plan['level_name']}")

        # Та же функция — у кнопок «Сухой прогон» / «Выполнить перенос» в админке.
        res = program.migrate_all(apply=apply, user=opts.get("user"),
                                  on_user=line if opts["verbose_users"] else None)
        mode = "ПЕРЕНЕСЕНО" if apply else "СУХОЙ ПРОГОН (ничего не записано; --apply — перенести)"
        self.stdout.write(self.style.SUCCESS(mode))
        self.stdout.write(f"Людей к переносу: {res['moved']}; уже перенесены: {res['skipped']}")
        self.stdout.write(f"Баллов переносится: {res['total']} (из них созревают: {res['held']}); "
                          f"с отрицательным балансом: {res['negative']}")
        self.stdout.write("Уровни после переноса: " + ", ".join(
            f"{name} — {n}" for name, _title, n in res["levels"]))
        self.stdout.write(f"Программа v1 сейчас: {'ВКЛЮЧЕНА' if config.enabled() else 'выключена'}")
