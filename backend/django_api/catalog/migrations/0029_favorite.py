from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0028_site_content_image_variants"),
    ]

    operations = [
        migrations.CreateModel(
            name="Favorite",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("user_id", models.CharField(db_index=True, max_length=40, verbose_name="Пользователь (ID)")),
                ("model_key", models.CharField(max_length=80, verbose_name="Модель (ключ витрины)")),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now, verbose_name="Добавлено")),
            ],
            options={
                "verbose_name": "Избранное",
                "verbose_name_plural": "Избранное",
                "db_table": "catalog_favorites",
                "ordering": ["-created_at"],
                "unique_together": {("user_id", "model_key")},
            },
        ),
    ]
