"""Уникальные ключи операций кошелька (аудит B03) — БЕЗОПАСНО для прода.

Частичные уникальные индексы:
- один `purchase` и один `redeem` на (пользователь, заказ);
- один `registration` (бонус за первый заказ) на пользователя.

main выкатывается на прод автоматически, миграции гоняются при старте web. Если
в реальных данных уже есть дубли (гонки до этой правки), `CREATE UNIQUE INDEX`
упал бы — и прод остался бы без web ночью. Поэтому миграция НИКОГДА не падает:
сначала ищет дубли; есть — индекс не создаёт и пишет предупреждение в лог
(данные не трогаем: это деньги, решает человек); нет — создаёт. Даже если дубль
проскочит между проверкой и созданием, ошибка ловится в savepoint.

От гонок в коде защищает в первую очередь замок кошелька (loyalty.wallet), индекс —
вторая линия. Чтобы создать пропущенный индекс после ручной чистки дублей —
`python manage.py migrate loyalty 0003 && python manage.py migrate loyalty`
(обратная миграция только удаляет индексы).
"""
import logging

from django.db import DatabaseError, migrations, transaction

log = logging.getLogger(__name__)

TABLE = "loyalty_transactions"

INDEXES = [
    (
        "loyalty_txn_uniq_order_op",
        "(user_id, order_id, source) "
        "WHERE source IN ('purchase', 'redeem') AND order_id IS NOT NULL",
        "SELECT user_id, order_id, source FROM loyalty_transactions "
        "WHERE source IN ('purchase', 'redeem') AND order_id IS NOT NULL "
        "GROUP BY user_id, order_id, source HAVING COUNT(*) > 1 LIMIT 20",
    ),
    (
        "loyalty_txn_uniq_registration",
        "(user_id) WHERE source = 'registration'",
        "SELECT user_id FROM loyalty_transactions WHERE source = 'registration' "
        "GROUP BY user_id HAVING COUNT(*) > 1 LIMIT 20",
    ),
]


def _warn(msg):
    log.warning(msg)
    print(f"\n  ВНИМАНИЕ (loyalty 0004): {msg}")


def create_indexes(apps, schema_editor):
    conn = schema_editor.connection
    if conn.vendor != "postgresql":
        return
    for name, definition, dup_sql in INDEXES:
        with conn.cursor() as cur:
            cur.execute(dup_sql)
            dups = cur.fetchall()
        if dups:
            _warn(
                f"индекс {name} НЕ создан — в {TABLE} есть дубли операций "
                f"(первые: {dups}). Защиту держит замок кошелька; дубли разобрать "
                f"вручную и перезапустить миграцию."
            )
            continue
        try:
            with transaction.atomic(using=conn.alias):
                with conn.cursor() as cur:
                    cur.execute(
                        f"CREATE UNIQUE INDEX IF NOT EXISTS {name} ON {TABLE} {definition}"
                    )
        except DatabaseError as e:
            _warn(f"индекс {name} НЕ создан: {e}")


def drop_indexes(apps, schema_editor):
    conn = schema_editor.connection
    if conn.vendor != "postgresql":
        return
    with conn.cursor() as cur:
        for name, _definition, _dup in INDEXES:
            cur.execute(f"DROP INDEX IF EXISTS {name}")


class Migration(migrations.Migration):
    dependencies = [
        ("loyalty", "0003_loyaltypartner"),
    ]

    operations = [
        migrations.RunPython(create_indexes, drop_indexes),
    ]
