# База прода: тот же PostGIS 16-3.4 + pgBackRest — непрерывная копия БД в два хранилища (D-117).
FROM postgis/postgis:16-3.4

# Debian 11 (bullseye) снят с поддержки (LTS до 08.2026): пакеты безопасности и обновлений
# переехали в архив Debian — со старых адресов apt получает 404 (ca-certificates и пр.).
# Репозиторий PGDG для bullseye тоже в архиве; в штатном Debian лежит pgBackRest 2.33.
RUN sed -i -e "s#http://deb.debian.org/debian-security#http://archive.debian.org/debian-security#" \
           -e "s#http://deb.debian.org/debian bullseye-updates#http://archive.debian.org/debian bullseye-updates#" \
           /etc/apt/sources.list \
 && echo "deb [ signed-by=/usr/local/share/keyrings/postgres.gpg.asc ] http://apt-archive.postgresql.org/pub/repos/apt bullseye-pgdg main" \
      > /etc/apt/sources.list.d/pgdg.list \
 && apt-get -o Acquire::Check-Valid-Until=false update \
 && apt-get install -y --no-install-recommends pgbackrest ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && install -d -o postgres -g postgres -m 0750 /var/spool/pgbackrest /var/log/pgbackrest /tmp/pgbackrest

COPY mata-pgbackrest-archive.sh /usr/local/bin/mata-pgbackrest-archive
RUN chmod 0755 /usr/local/bin/mata-pgbackrest-archive
