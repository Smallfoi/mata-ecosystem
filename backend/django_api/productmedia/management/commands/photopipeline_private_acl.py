"""Закрыть уже загруженные файлы фотопайплайна: ACL объектов photopipeline/ → private.

Новые исходники/мастера/крупные планы с этого релиза кладутся в приватное хранилище
(common.media: `private`). Но всё, что загрузили раньше, лежит в том же бакете с ACL
public-read — по прямой ссылке доступно всем. Команда меняет ACL этих объектов.

Запуск (владелец, на сервере):
    docker compose -f docker-compose.prod.yml exec web python manage.py photopipeline_private_acl
        — сухой прогон: сколько объектов найдено, ничего не меняет;
    ... photopipeline_private_acl --apply
        — поменять ACL на private.
Повторный запуск безопасен (идемпотентно). Витринные снимки (catalog) не трогает:
они лежат под другими префиксами.
"""
from django.core.management.base import BaseCommand

from common.media import private_storage

PREFIX = "photopipeline/"


class Command(BaseCommand):
    help = "ACL файлов фотопайплайна (photopipeline/) → private. Без --apply — сухой прогон."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true",
                            help="реально поменять ACL (без флага — только подсчёт)")
        parser.add_argument("--prefix", default=PREFIX,
                            help="префикс объектов (по умолчанию photopipeline/)")

    def handle(self, *args, **opts):
        storage = private_storage()
        bucket = getattr(storage, "bucket", None)
        if bucket is None:
            self.stdout.write("Хранилище не S3 (локальный диск) — ACL менять не нужно.")
            return
        prefix = opts["prefix"]
        if not prefix.startswith(PREFIX):
            self.stderr.write("Префикс должен начинаться с %s — другое не трогаем." % PREFIX)
            return
        found = changed = failed = 0
        for obj in bucket.objects.filter(Prefix=prefix):
            found += 1
            if not opts["apply"]:
                continue
            try:
                bucket.Object(obj.key).Acl().put(ACL="private")
                changed += 1
            except Exception as e:               # noqa: BLE001 — отчёт и дальше по списку
                failed += 1
                self.stderr.write("не удалось: %s (%s)" % (obj.key, e))
        if opts["apply"]:
            self.stdout.write("Объектов %d: закрыто %d, ошибок %d." % (found, changed, failed))
        else:
            self.stdout.write("Сухой прогон: объектов под %s — %d. Для смены ACL: --apply."
                              % (prefix, found))
