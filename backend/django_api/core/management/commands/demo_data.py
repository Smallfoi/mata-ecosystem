"""Данные, оставшиеся от тестового периода: показать и, по команде, убрать.

Пока продукт готовили, мы сами оформляли заказы, бегали, копили баллы и заливали
пробные фото. Всё это лежит в тех же таблицах, что и настоящее, и после запуска
выглядит как реальная история: в личном кабинете видны заказы, которых не было,
а баланс баллов взялся из ниоткуда.

    python manage.py demo_data                      # отчёт: что и сколько лежит
    python manage.py demo_data --user +79148278470  # только по одному человеку
    python manage.py demo_data --before 2026-09-01  # только старее даты
    python manage.py demo_data --purge --yes        # удалить (без --yes только отчёт)
    python manage.py demo_data --purge --yes --catalog   # ещё и демо-каталог

**Каталог отдельным флагом не случайно.** `--catalog` удаляет только товары без
идентификатора 1С и артикула — демо из `seed_catalog`. Настоящий каталог из 1С,
категории и баннеры не трогаются. С витрины демо-товары и так сняты (catalog 0025).

Аккаунты не трогаем вообще: удалять человека вместе с его историей — не наше
решение, для этого есть отдельный сценарий удаления аккаунта (152-ФЗ).
"""
from django.core.management.base import BaseCommand
from django.db import connection
from django.utils.dateparse import parse_date


class Command(BaseCommand):
    help = "Показать (и по команде удалить) данные, оставшиеся от тестового периода."

    def add_arguments(self, parser):
        parser.add_argument("--user", default="", help="телефон: только этот аккаунт")
        parser.add_argument("--before", default="", help="YYYY-MM-DD: только старее даты")
        parser.add_argument("--purge", action="store_true", help="удалять, а не только показывать")
        parser.add_argument("--yes", action="store_true", help="подтверждение удаления")
        parser.add_argument("--catalog", action="store_true",
                            help="включить демо-каталог (витрина останется пустой!)")

    def handle(self, *args, **o):
        from accounts.models import Account
        from analytics.models import Event
        from catalog.models import Banner, Category, Product
        from clubs.models import Club
        from loyalty.models import LoyaltyTransaction
        from notifications.models import Notification
        from orders.models import Order
        from runs.models import Run
        from shoes.models import ShoeAsset

        before = parse_date(o["before"]) if o["before"] else None
        if o["before"] and not before:
            self.stderr.write("Дата должна быть в формате YYYY-MM-DD.")
            return

        user_ids = None
        if o["user"]:
            user_ids = list(
                Account.objects.filter(phone=o["user"]).values_list("id", flat=True)
            )
            if not user_ids:
                self.stderr.write(f"Аккаунт с телефоном {o['user']} не найден.")
                return

        def scope(qs, date_field=None):
            if user_ids is not None:
                qs = qs.filter(user_id__in=user_ids)
            if before and date_field:
                qs = qs.filter(**{f"{date_field}__lt": before})
            return qs

        groups = [
            ("Заказы", scope(Order.objects.all(), "created_at")),
            ("Баллы (операции)", scope(LoyaltyTransaction.objects.all(), "created_at")),
            ("Пробежки", scope(Run.objects.all(), "created_at")),
            ("Уведомления", scope(Notification.objects.all(), "created_at")),
            ("Износ кроссовок", scope(ShoeAsset.objects.all())),
            ("События аналитики", scope(Event.objects.all(), "created_at")),
        ]
        if user_ids is None:
            groups.append(("Клубы", Club.objects.all()))

        self.stdout.write("=== Данные тестового периода ===")
        if o["user"]:
            self.stdout.write(f"    только аккаунт {o['user']}")
        if before:
            self.stdout.write(f"    только созданное до {before}")

        total = 0
        for name, qs in groups:
            n = qs.count()
            total += n
            self.stdout.write(f"  {name}: {n}")

        # Территории живут в PostGIS-таблице и ORM-модели не имеют.
        terr = self._territories_count(user_ids)
        total += terr
        self.stdout.write(f"  Захваченные территории: {terr}")

        self.stdout.write("")
        self.stdout.write("=== Демо-каталог (показывается на витрине) ===")
        self.stdout.write(
            f"  Товары: {Product.objects.count()} · Категории: {Category.objects.count()}"
            f" · Баннеры: {Banner.objects.count()}"
        )
        self.stdout.write("  Удалять только когда заведены настоящие товары (--catalog).")

        if not o["purge"]:
            self.stdout.write("")
            self.stdout.write(f"Всего записей к удалению: {total}")
            self.stdout.write("Это отчёт. Чтобы удалить: --purge --yes")
            return

        if not o["yes"]:
            self.stderr.write("Удаление требует явного --yes. Ничего не тронуто.")
            return

        self.stdout.write("")
        self.stdout.write("=== Удаление ===")
        for name, qs in groups:
            n = qs.delete()[0]
            self.stdout.write(f"  {name}: удалено {n}")
        self.stdout.write(f"  Территории: удалено {self._territories_delete(user_ids)}")

        if o["catalog"]:
            # Раньше здесь удалялся ВЕСЬ каталог — с приходом 1С это стёрло бы
            # настоящие товары. Теперь только товары без идентификатора 1С и артикула.
            p = Product.objects.filter(external_id__isnull=True, article="").delete()[0]
            self.stdout.write(f"  Каталог: удалено записей товаров без 1С и артикула — {p}")
            self.stdout.write("  Товары из 1С, категории и баннеры не тронуты.")

        self.stdout.write("")
        self.stdout.write("Готово. Аккаунты и юр-документы не тронуты.")

    def _territories_count(self, user_ids) -> int:
        with connection.cursor() as cur:
            if user_ids is None:
                cur.execute("SELECT count(*) FROM territories")
            else:
                cur.execute(
                    "SELECT count(*) FROM territories WHERE owner_id = ANY(%s)", [user_ids]
                )
            return cur.fetchone()[0]

    def _territories_delete(self, user_ids) -> int:
        with connection.cursor() as cur:
            if user_ids is None:
                cur.execute("DELETE FROM territories")
            else:
                cur.execute("DELETE FROM territories WHERE owner_id = ANY(%s)", [user_ids])
            return cur.rowcount
