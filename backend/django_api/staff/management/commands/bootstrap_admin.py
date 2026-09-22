"""Первая учётная запись владельца — только на пустой системе.

    python manage.py bootstrap_admin

Раньше в сценарии развёртывания стоял `createsuperuser --noinput`. Пока логин был
`admin`, это ничего не делало: запись уже есть, команда молча падала. Но владелец
логин сменил (D-68/S-13 — учётка закреплена по идентификатору, имя можно менять),
и имя `admin` освободилось: следующее полное развёртывание завело бы ЛИШНЮЮ запись
с паролем из окружения. Лишний вход в админку — ровно то, от чего мы защищаемся.

Поэтому правило простое: если суперпользователь в системе уже есть — не трогаем
ничего. Если система пустая — заводим запись из переменных окружения и сразу
закрепляем её владельцем.
"""
import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from staff.models import OwnerPin


class Command(BaseCommand):
    help = "Заводит владельца из переменных окружения, только если суперпользователей нет."

    def handle(self, *args, **options):
        User = get_user_model()

        existing = User.objects.filter(is_superuser=True).order_by("pk").first()
        if existing is not None:
            self.stdout.write(
                f"Владелец уже есть: id={existing.pk} ({existing.get_username()}) — "
                "ничего не создаём."
            )
            return

        username = (os.environ.get("DJANGO_SUPERUSER_USERNAME") or "").strip()
        password = os.environ.get("DJANGO_SUPERUSER_PASSWORD") or ""
        email = (os.environ.get("DJANGO_SUPERUSER_EMAIL") or "").strip()
        if not username or not password:
            self.stdout.write(self.style.WARNING(
                "Суперпользователей нет, но DJANGO_SUPERUSER_USERNAME/PASSWORD не заданы — "
                "создавать некого."
            ))
            return

        user = User.objects.create_superuser(username=username, email=email, password=password)
        OwnerPin.objects.all().delete()
        OwnerPin.objects.create(user=user, note="заведён при развёртывании")
        self.stdout.write(self.style.SUCCESS(
            f"Владелец заведён и закреплён: id={user.pk} ({username})."
        ))
