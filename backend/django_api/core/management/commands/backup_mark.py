"""Отметить удачную резервную копию: `manage.py backup_mark dump:1 [pgbr:2 ...]`.

Зовут deploy/backup.sh и deploy/pgbr.sh после успешной выгрузки в хранилище;
/v1/health по этим отметкам видит, что копия устарела (core/backups.py)."""
from django.core.management.base import BaseCommand, CommandError

from core.backups import mark


class Command(BaseCommand):
    help = "Отметить удачную резервную копию (dump:1|dump:2|pgbr:1|pgbr:2)"

    def add_arguments(self, parser):
        parser.add_argument("names", nargs="+")

    def handle(self, *args, names, **opts):
        for name in names:
            try:
                mark(name)
            except ValueError as e:
                raise CommandError(str(e)) from e
            self.stdout.write(f"Отмечено: {name}")
