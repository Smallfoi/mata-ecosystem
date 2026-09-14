from django.db import migrations


class Migration(migrations.Migration):
    """Домашний квартал (D-74, Ф3): несгораемый квартал бегуна.

    Один дом на пользователя (PK owner_id) и один хозяин на квартал (UNIQUE block_id).
    Домашний квартал не перехватывается чужими и не сбрасывается в конце сезона;
    для чужих он показывается анонимно (privacy — не раскрываем, где ты живёшь).
    """

    dependencies = [("blocks", "0002_block_ownership")]

    operations = [
        migrations.RunSQL(
            sql=[
                """
                CREATE TABLE IF NOT EXISTS home_block (
                    owner_id TEXT PRIMARY KEY,
                    block_id TEXT NOT NULL UNIQUE REFERENCES city_blocks(block_id) ON DELETE CASCADE,
                    set_at timestamptz DEFAULT now()
                );
                """,
                "CREATE INDEX IF NOT EXISTS home_block_block_ix ON home_block (block_id);",
            ],
            reverse_sql=["DROP TABLE IF EXISTS home_block;"],
        ),
    ]
