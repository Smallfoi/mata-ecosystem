"""Чистка осиротевших данных — строк, чей user_id/owner_id больше не имеет Account.

Появляются, если аккаунт удалили в обход delete_account (например, прямым
`Account.objects.delete()` в shell при чистке тестов) — тогда баллы/забеги
повисают и, например, засоряют лидерборд. Штатное удаление (delete_account)
чистит всё по реестру `accounts.userdata`; эта команда добивает исторический
мусор ТЕМ ЖЕ реестром (аудит A04): личное удаляется, финансовое обезличивается.

  python manage.py clean_orphans          # dry-run: только показать
  python manage.py clean_orphans --apply  # реально удалить/обезличить
"""
from django.core.management.base import BaseCommand
from django.db import connection, transaction


class Command(BaseCommand):
    help = "Удаляет/обезличивает осиротевшие данные (user_id/owner_id без Account)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply", action="store_true",
            help="реально удалить (по умолчанию — только показать, dry-run)",
        )

    def handle(self, *args, **opts):
        from accounts import userdata
        from accounts.models import Account

        valid = set(Account.objects.values_list("id", flat=True))

        def orphan(uid) -> bool:
            return bool(uid) and uid not in valid and not str(uid).startswith("del_")

        found = {}  # метка → число строк сирот
        uids = set()
        for label, model_label, fields, _policy in userdata.MODELS:
            model = userdata._model(model_label)
            if model is None:
                continue
            for field in fields:
                for uid in model.objects.values_list(field, flat=True).distinct():
                    if orphan(uid):
                        uids.add(uid)
                        found[label] = found.get(label, 0) + model.objects.filter(
                            **{field: uid}).count()
        with connection.cursor() as cur:
            for label, table, cols in userdata.RAW_TABLES:
                if not userdata._table_exists(table):
                    continue
                for col in cols:
                    cur.execute(f"SELECT {col}, COUNT(*) FROM {table} GROUP BY {col}")
                    for uid, n in cur.fetchall():
                        if orphan(uid):
                            uids.add(uid)
                            found[label] = found.get(label, 0) + n

        total = sum(found.values())
        mode = "УДАЛЕНО/ОБЕЗЛИЧЕНО" if opts["apply"] else "НАЙДЕНО (dry-run; для чистки --apply)"
        self.stdout.write(self.style.WARNING(
            f"Осиротевшие данные [{mode}]: строк {total}, бывших аккаунтов {len(uids)}"))
        for k, v in found.items():
            self.stdout.write(f"  {k}: {v}")
        if opts["apply"]:
            for uid in sorted(uids):
                with transaction.atomic():
                    userdata.erase(uid)
        if total == 0:
            self.stdout.write(self.style.SUCCESS("Мусора нет — всё чисто."))
