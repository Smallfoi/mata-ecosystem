from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0004_seed_feature_flags"),
    ]

    operations = [
        migrations.CreateModel(
            name="BackupMark",
            fields=[
                ("name", models.CharField(max_length=32, primary_key=True, serialize=False, verbose_name="Копия")),
                ("at", models.DateTimeField(verbose_name="Последняя удачная")),
            ],
            options={
                "verbose_name": "Отметка бэкапа",
                "verbose_name_plural": "Отметки бэкапов",
                "db_table": "backup_marks",
            },
        ),
    ]
