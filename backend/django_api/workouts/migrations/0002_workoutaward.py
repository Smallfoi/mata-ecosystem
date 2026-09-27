import django.utils.timezone
from django.db import migrations, models


def backfill(apps, schema_editor):
    """Реестр заполняем из уже импортированных тренировок: иначе всё, что пришло
    до этой миграции, после отключения/подключения источника оплатилось бы снова.
    Ничего не удаляет и не падает на дублях (ключ = id тренировки, он уникален)."""
    ExternalWorkout = apps.get_model("workouts", "ExternalWorkout")
    WorkoutAward = apps.get_model("workouts", "WorkoutAward")
    have = set(WorkoutAward.objects.values_list("id", flat=True))
    batch = []
    for w in ExternalWorkout.objects.all().only(
        "id", "user_id", "source", "points_awarded", "imported_at"
    ).iterator():
        if w.id in have:
            continue
        batch.append(WorkoutAward(
            id=w.id, user_id=w.user_id, source=w.source,
            points=w.points_awarded or 0, created_at=w.imported_at,
        ))
        if len(batch) >= 500:
            WorkoutAward.objects.bulk_create(batch, ignore_conflicts=True)
            batch = []
    if batch:
        WorkoutAward.objects.bulk_create(batch, ignore_conflicts=True)


class Migration(migrations.Migration):

    dependencies = [
        ("workouts", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="WorkoutAward",
            fields=[
                ("id", models.CharField(max_length=80, primary_key=True, serialize=False, verbose_name="Ключ тренировки")),
                ("user_id", models.CharField(db_index=True, max_length=40, verbose_name="Пользователь (ID)")),
                ("source", models.CharField(max_length=20, verbose_name="Источник")),
                ("points", models.IntegerField(default=0, verbose_name="Начислено баллов")),
                ("txn_id", models.CharField(blank=True, default="", max_length=40, verbose_name="Транзакция баллов")),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now, verbose_name="Учтена")),
            ],
            options={
                "verbose_name": "Учтённая тренировка",
                "verbose_name_plural": "Учтённые тренировки (реестр начислений)",
                "db_table": "workout_awards",
            },
        ),
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
