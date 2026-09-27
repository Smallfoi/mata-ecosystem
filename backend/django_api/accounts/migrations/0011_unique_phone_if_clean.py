"""Аудит A03: один телефон — один аккаунт, на уровне базы.

Телефон — это логин, а поле исторически не уникально. Уникальный индекс по
непустому номеру закрывает гонку «два запроса одновременно привязали/создали
один номер». Но если на проде уже есть дубли, CREATE UNIQUE INDEX упадёт, а
миграции гоняются при старте web — прод не поднимется. Поэтому: сначала
ищем дубли; есть — индекс не создаём и пишем предупреждение (дубли разбирает
человек, потом миграцию `0011` можно повторить командой
`python manage.py migrate accounts 0010 && python manage.py migrate accounts`).
"""
from django.db import migrations

INDEX = "accounts_phone_uniq_nonempty"


def create(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cur:
        cur.execute(
            "SELECT phone, COUNT(*) FROM accounts "
            "WHERE phone IS NOT NULL AND phone <> '' "
            "GROUP BY phone HAVING COUNT(*) > 1 LIMIT 20"
        )
        dups = cur.fetchall()
        if dups:
            print(f"\n  [accounts.0011] ВНИМАНИЕ: {len(dups)}+ телефонов у нескольких "
                  "аккаунтов — уникальный индекс НЕ создан, разберите дубли.")
            return
        cur.execute(
            f"CREATE UNIQUE INDEX IF NOT EXISTS {INDEX} ON accounts (phone) "
            "WHERE phone IS NOT NULL AND phone <> ''"
        )


def drop(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cur:
        cur.execute(f"DROP INDEX IF EXISTS {INDEX}")


class Migration(migrations.Migration):
    dependencies = [("accounts", "0010_drop_phone_default_password")]
    operations = [migrations.RunPython(create, drop)]
