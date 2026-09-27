"""Отозвать выданные токены входа (аудит A01/A02).

Поднимает версию сессий аккаунта — все выданные раньше токены перестают
действовать, человек входит заново (по коду или паролю). Без --apply только
показывает, кого коснётся.

    python manage.py revoke_sessions --user <id>            # один аккаунт
    python manage.py revoke_sessions --without-password     # все без пароля
    ... --apply                                             # выполнить

--without-password — аккаунты, созданные входом по коду: до исправления A01 у них
был пароль «phone:<номер>», и если его кто-то использовал, токен ещё жив.
Это разлогинит всех, кто входит только по коду, — решение владельца.
"""
from django.core.management.base import BaseCommand, CommandError
from django.db.models import F, Q

from accounts.models import Account
from common.security import forget_account


class Command(BaseCommand):
    help = "Отозвать токены входа (поднять версию сессий)."

    def add_arguments(self, parser):
        parser.add_argument("--user", action="append", default=[], help="id аккаунта")
        parser.add_argument("--without-password", action="store_true",
                            help="все аккаунты без пароля (вход только по коду)")
        parser.add_argument("--apply", action="store_true", help="выполнить, а не показать")

    def handle(self, *args, **opts):
        if not opts["user"] and not opts["without_password"]:
            raise CommandError("укажите --user <id> или --without-password")
        qs = Account.objects.none()
        if opts["user"]:
            qs = Account.objects.filter(id__in=opts["user"])
        if opts["without_password"]:
            qs = qs | Account.objects.filter(Q(password_hash__isnull=True) | Q(password_hash=""))
        ids = list(qs.values_list("id", flat=True).distinct())
        self.stdout.write(f"Коснётся аккаунтов: {len(ids)}")
        if not opts["apply"]:
            self.stdout.write("Это просмотр. Чтобы выполнить — добавьте --apply.")
            return
        Account.objects.filter(id__in=ids).update(token_version=F("token_version") + 1)
        for uid in ids:
            forget_account(uid)
        self.stdout.write(self.style.SUCCESS(f"Сессии отозваны: {len(ids)}"))
