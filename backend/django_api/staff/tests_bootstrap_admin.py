"""Учётка владельца при развёртывании: заводим только на пустой системе.

Реальный случай: владелец сменил логин, имя «admin» освободилось — и прежний
`createsuperuser --noinput` при следующем полном развёртывании завёл бы вторую
учётную запись с паролем из окружения. Лишний вход в админку.
"""
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings

from staff.models import OwnerPin

ENV = {
    "DJANGO_SUPERUSER_USERNAME": "admin",
    "DJANGO_SUPERUSER_PASSWORD": "DeployPass!2026",
    "DJANGO_SUPERUSER_EMAIL": "admin@mata-club.ru",
}


def run(**env):
    out = StringIO()
    import os
    saved = {k: os.environ.get(k) for k in ENV}
    os.environ.update({k: v for k, v in {**ENV, **env}.items() if v is not None})
    for k, v in env.items():
        if v is None:
            os.environ.pop(k, None)
    try:
        call_command("bootstrap_admin", stdout=out)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    return out.getvalue()


@override_settings(MATA_OWNER_ID=None)
class BootstrapAdminTests(TestCase):
    def test_creates_owner_on_empty_system(self):
        text = run()
        User = get_user_model()
        user = User.objects.get(username="admin")
        self.assertTrue(user.is_superuser)
        self.assertEqual(OwnerPin.objects.filter(user=user).count(), 1)
        self.assertIn("заведён", text)

    def test_does_nothing_when_owner_exists(self):
        User = get_user_model()
        User.objects.create_superuser("hozyain", "h@t.dev", "OwnerPass!2026")
        text = run()
        self.assertEqual(User.objects.filter(is_superuser=True).count(), 1)
        self.assertFalse(User.objects.filter(username="admin").exists())
        self.assertIn("уже есть", text)

    def test_renamed_owner_does_not_get_a_second_account(self):
        """Владелец сменил логин — имя «admin» свободно, но заводить его нельзя."""
        User = get_user_model()
        owner = User.objects.create_superuser("admin", "o@t.dev", "OwnerPass!2026")
        owner.username = "hozyain"
        owner.save(update_fields=["username"])

        run()
        self.assertFalse(User.objects.filter(username="admin").exists(),
                         "развёртывание снова завело служебную учётку admin")
        self.assertEqual(User.objects.count(), 1)

    def test_without_env_nothing_happens(self):
        text = run(DJANGO_SUPERUSER_PASSWORD=None)
        self.assertEqual(get_user_model().objects.count(), 0)
        self.assertIn("создавать некого", text)
