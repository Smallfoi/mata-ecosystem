#!/bin/sh
# (в имени обязательно «pgbackrest»: `pgbackrest check` иначе отвергает archive_command)
# archive_command PostgreSQL: отдать сегмент WAL в pgBackRest (а тот — в оба хранилища).
# Нет конфигурации (dev, или сервер ещё без ключей) — считаем сегмент обработанным и
# ничего не копим: иначе pg_wal рос бы до переполнения диска. Непрерывной копии тогда нет,
# как и раньше, — её отсутствие видно в `pgbr.sh check` и в тревоге мониторинга.
[ -s /etc/pgbackrest/pgbackrest.conf ] || exit 0
exec pgbackrest --stanza=mata archive-push "$1"
