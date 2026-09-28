"""Аудит A01: снять пароль «phone:<номер>» у аккаунтов, созданных входом по коду.

До исправления вход по коду создавал аккаунт с паролем «phone:<номер>» — войти
в такой аккаунт по паролю мог любой, кто знает номер. Здесь проверяем хэш
каждого аккаунта с телефоном: совпал с «phone:<номер>» — пароль снимается
(вход остаётся по коду; свой пароль человек задаёт через сброс по SMS).
Настоящие пароли не трогаем: для них проверка не совпадёт.

Сессии не отзываем автоматически — это разлогинит всех, кто входил по коду.
Решение за владельцем: `python manage.py revoke_sessions --without-password`.
"""
from django.db import migrations


def drop(apps, schema_editor):
    from common.security import verify_password

    Account = apps.get_model("accounts", "Account")
    rows = (Account.objects.exclude(phone__isnull=True).exclude(phone="")
            .exclude(password_hash__isnull=True).exclude(password_hash="")
            .only("id", "phone", "password_hash"))
    for acc in rows.iterator():
        if verify_password(f"phone:{acc.phone}", acc.password_hash):
            Account.objects.filter(pk=acc.pk).update(password_hash=None)


class Migration(migrations.Migration):
    dependencies = [("accounts", "0009_account_token_version")]
    operations = [migrations.RunPython(drop, migrations.RunPython.noop)]
