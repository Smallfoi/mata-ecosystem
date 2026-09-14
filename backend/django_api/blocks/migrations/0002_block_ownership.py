from django.db import migrations


class Migration(migrations.Migration):
    """Владение кварталами (D-74, Ф2): кто каким городским кварталом владеет.

    Захват (POST /v1/territories/capture) метит кварталы, чей центр попал в петлю
    забега. Полигонный слой `territories` продолжает жить параллельно (карта/рейтинг/
    клубы зависят от него), пока клиент не перейдёт на кварталы. Защита сезоном и
    несгораемый домашний квартал — Ф3.
    """

    dependencies = [("blocks", "0001_initial")]

    operations = [
        migrations.RunSQL(
            sql=[
                """
                CREATE TABLE IF NOT EXISTS block_ownership (
                    block_id TEXT PRIMARY KEY REFERENCES city_blocks(block_id) ON DELETE CASCADE,
                    owner_id TEXT NOT NULL,
                    club_id TEXT,
                    captured_at timestamptz DEFAULT now()
                );
                """,
                "CREATE INDEX IF NOT EXISTS block_ownership_owner_ix ON block_ownership (owner_id);",
                "CREATE INDEX IF NOT EXISTS block_ownership_club_ix ON block_ownership (club_id);",
            ],
            reverse_sql=["DROP TABLE IF EXISTS block_ownership;"],
        ),
    ]
