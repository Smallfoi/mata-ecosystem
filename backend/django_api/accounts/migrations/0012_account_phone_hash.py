# Аудит F02: индексируемый хеш телефона для поиска друзей по контактам.
#
# Безопасно для прода: колонка добавляется с пустым значением по умолчанию,
# индекс не уникальный (дубли номеров не валят миграцию), заполнение — обычный
# пересчёт sha256 пачками без обращения к внешним сервисам.
import hashlib
import re

from django.db import migrations, models


def _hash(phone):
    # Копия accounts.models.contact_phone_hash на момент миграции (код приложения
    # в миграции не импортируем — он может поменяться).
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    if not digits:
        return ""
    return hashlib.sha256(("+" + digits).encode()).hexdigest()


def fill(apps, schema_editor):
    Account = apps.get_model("accounts", "Account")
    batch = []
    qs = Account.objects.exclude(phone__isnull=True).exclude(phone="").only("id", "phone")
    for acc in qs.iterator(chunk_size=1000):
        acc.phone_hash = _hash(acc.phone)
        batch.append(acc)
        if len(batch) >= 1000:
            Account.objects.bulk_update(batch, ["phone_hash"])
            batch = []
    if batch:
        Account.objects.bulk_update(batch, ["phone_hash"])


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0011_unique_phone_if_clean'),
    ]

    operations = [
        migrations.AddField(
            model_name='account',
            name='phone_hash',
            field=models.CharField(blank=True, db_index=True, default='', editable=False, max_length=64, verbose_name='Хеш телефона'),
        ),
        migrations.RunPython(fill, migrations.RunPython.noop),
    ]
