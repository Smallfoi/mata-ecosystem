# Точный тег базового образа (F05): python:3.12-slim «плавал» — прод-ВМ пересобирает
# образ заново и могла получить другой Python/Debian, чем проверено в dev/CI.
# 3.12.14-slim-trixie = тот же образ, что сейчас python:3.12-slim (сверено по digest 28.09.2026).
FROM python:3.12.14-slim-trixie

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Системные либы под PostGIS/GeoDjango добавим, когда дойдём до территорий
# (gdal-bin libgdal-dev). Пока — обычный Django + DRF + psycopg.
COPY requirements.txt requirements.lock ./
# pip зафиксирован (свежий — закрывает CVE самого установщика; проверен pip-audit).
# Зависимости: requirements.txt — ЧТО нужно, requirements.lock — ТОЧНЫЕ версии
# (constraints). Без lock прод на ВМ ставил «последние» версии на момент сборки (F05).
RUN pip install --no-cache-dir pip==26.2.1 \
    && pip install --no-cache-dir -r requirements.txt -c requirements.lock

COPY . .

EXPOSE 8000
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
