import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0025_unpublish_demo_catalog"),
    ]

    operations = [
        migrations.CreateModel(
            name="ShowcaseTab",
            fields=[
                ("id", models.SlugField(max_length=40, primary_key=True, serialize=False,
                                        verbose_name="ID (латиницей)")),
                ("name", models.CharField(max_length=60, verbose_name="Название")),
                ("sort", models.IntegerField(default=0, verbose_name="Порядок")),
            ],
            options={
                "verbose_name": "Вкладка витрины",
                "verbose_name_plural": "Вкладки витрины",
                "db_table": "catalog_showcase_tabs",
                "ordering": ["sort", "name"],
            },
        ),
        migrations.CreateModel(
            name="ShowcaseGroup",
            fields=[
                ("id", models.SlugField(max_length=40, primary_key=True, serialize=False,
                                        verbose_name="ID (латиницей)")),
                ("name", models.CharField(max_length=60, verbose_name="Название")),
                ("sort", models.IntegerField(default=0, verbose_name="Порядок")),
                ("tab", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                          related_name="groups", to="catalog.showcasetab",
                                          verbose_name="Вкладка")),
            ],
            options={
                "verbose_name": "Группа витрины",
                "verbose_name_plural": "Группы витрины",
                "db_table": "catalog_showcase_groups",
                "ordering": ["tab__sort", "sort", "name"],
            },
        ),
        migrations.AddField(
            model_name="category",
            name="showcase_group",
            field=models.ForeignKey(blank=True, null=True,
                                    on_delete=django.db.models.deletion.SET_NULL,
                                    related_name="categories", to="catalog.showcasegroup",
                                    verbose_name="Группа витрины"),
        ),
    ]
