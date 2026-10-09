# Деплой / прод-конфиг экосистемы МАТА

Чеклист перехода dev → прод. **В dev ничего настраивать не нужно** — везде заданы
рабочие dev-значения по умолчанию (backend `127.0.0.1:8000`, CORS открыт). Прод
включается переменными окружения (backend) и флагами сборки (приложения, сайт) —
код менять не нужно (кроме одного домена в сайте, см. ниже).

Единственное, что нужно завести при деплое, — **домен(ы)**:
- API, напр. `https://api.mata-club.ru` (база API = `https://api.mata-club.ru/v1`);
- сайт, напр. `https://mata-club.ru`.

---

## 1. Backend (Django)

> Пошаговый порядок закупки и подключения сервисов (облако → домен → S3 → TLS → SMS →
> оплата → пуши) с ценами — `docs/YANDEX_CLOUD.md`. Здесь — техническая часть деплоя.

**Готовый прод-стек** — `backend/docker-compose.prod.yml` (Django+gunicorn + PostGIS + Redis +
Celery worker/beat + nginx+TLS).
Шаблоны: `backend/.env.prod.example`, `backend/nginx/mata.conf.example`. Запуск:
```
cd backend && cp .env.prod.example .env   # заполнить секреты!
cp nginx/mata.conf.example nginx/mata.conf # подставить домен; certs/ — TLS
docker compose -f docker-compose.prod.yml --env-file .env up -d --build
```
web сам делает migrate → collectstatic → gunicorn (3 воркера); nginx форсит HTTPS, раздаёт /media, /static.
Сервисы `worker`/`beat` выполняют фоновые задачи (чистка данных с истёкшим сроком хранения —
152-ФЗ, чистка территорий, парсер афиши «Стартов», рассылки). Их падение по API незаметно —
поэтому `make smoke` отдельно проверяет, что оба подняты.
**Обязательно:** бэкапы БД (авто `pg_dump` + выгрузка в Object Storage + проверка восстановления — баллы = деньги!); внешний пинг `/v1/health`+алерты; Redis для общего rate-limit/кэша на нескольких воркерах (D-07); сменить дефолтный пароль/логин админки + ограничить `/admin/` по IP.

Задать переменные окружения (см. `backend/.env.prod.example`):

| Переменная | Прод-значение | Зачем |
|---|---|---|
| `DJANGO_DEBUG` | `0` | выключить отладку |
| `DJANGO_SECRET_KEY` | длинный случайный секрет | подпись Django |
| `JWT_SECRET` | ДРУГОЙ длинный случайный секрет | подпись токенов (иначе любой подделает токен!) |
| `DJANGO_ALLOWED_HOSTS` | `api.mata-club.ru` | какие хосты принимаем |
| `DJANGO_CORS_ORIGINS` | `https://mata-club.ru,https://www.mata-club.ru` | каким источникам сайта можно ходить в API (со схемой) |
| `POSTGRES_*` | прод-БД + сильный пароль | подключение к БД |

- ⚠️ **Fail-fast:** при `DJANGO_DEBUG=0` приложение НЕ стартует, если `JWT_SECRET`/`DJANGO_SECRET_KEY`/пароль БД дефолтные или `ALLOWED_HOSTS=*` (`common/prodcheck.py`) — защита от запуска с публичным dev-секретом.
- Секреты сгенерировать: `python -c "import secrets; print(secrets.token_urlsafe(64))"` (×2).
- `SEED_DEMO_POINTS` НЕ задавать — демо-баллы новичкам выключены (реальный лидерборд).
- Пока `DJANGO_CORS_ORIGINS` пуста → CORS открыт всем (dev). Как задана → только эти источники; они же идут в `CSRF_TRUSTED_ORIGINS` (для Django-admin).
- `SECURE_PROXY_SSL_HEADER` уже учитывает `X-Forwarded-Proto` от прокси (nginx-шаблон его шлёт).
- Миграции + `collectstatic` прод-compose делает сам; засеять каталог: `python manage.py seed_catalog`.

## 2. Приложения (Flutter) — Квартал и SportStore

База API задаётся при сборке через `--dart-define` (дефолт — dev `127.0.0.1:8000/v1`):

```bash
# SportStore
flutter build apk --release --target-platform android-arm64 \
  --dart-define=SPORT_STORE_API_BASE_URL=https://api.mata-club.ru/v1

# Квартал
flutter build apk --release --target-platform android-arm64 \
  --dart-define=KVARTAL_API_BASE_URL=https://api.mata-club.ru/v1
# (опц.) источник полигонов кварталов, если поднят отдельный zones-сервис:
#   --dart-define=KVARTAL_ZONES_URL=https://.../api/zones
```

На HTTPS не нужен cleartext — но `usesCleartextTraffic`/`INTERNET` в манифестах оставлены
(не мешают прод; нужны для dev по HTTP). Связь телефон↔dev-бек по USB: `adb reverse tcp:8000 tcp:8000`.

## 3. Сайт МАТА

Раздавать по HTTPS. База API в `САЙТ МАТА/ecosystem.js`:
- на `localhost`/`127.0.0.1` сам берёт dev (`127.0.0.1:8000/v1`);
- на проде берёт `PROD_API` — **заменить `https://api.mata-club.ru/v1` на реальный домен**
  (или задать `window.STAW_API_BASE = "https://..."` в `<head>` до подключения `ecosystem.js`).

## 4. После

- **ЮKassa:** в личном кабинете (Интеграция → HTTP-уведомления) указать вебхук
  `https://api.mata-club.ru/v1/payments/webhook`, события `payment.succeeded` и
  `payment.canceled`. Без него оплаченные заказы останутся в «ожидает оплаты», а баллы
  за покупку не начислятся (они привязаны к подтверждению платежа, не к оформлению).
  Проверка: тестовый заказ на 1 ₽ → оплата → заказ «Оплачен» + баллы в истории.
- Проверить `GET https://api.mata-club.ru/v1/health` → `{"status":"ok"}`.
- Залогиниться на сайте/в приложениях, убедиться, что баллы общие.
- Секреты (SECRET_KEY, пароль БД) — только в окружении прод-сервера, НЕ в репозитории (он публичный).

---

## 5. Операторские команды (runbook)

На сервере, из каталога `backend/` (есть `Makefile` и `deploy/*.sh`):

| Команда | Что делает |
|---|---|
| `make prod-deploy` | бэкап БД → сборка/миграции/collectstatic → smoke-тест (основной деплой/обновление) |
| `make backup` | бэкап БД → `backups/mata_<дата>.sql.gz` + выгрузка в Object Storage (ротация 14 дней) |
| `make tls-issue` | выпустить TLS-сертификат Let's Encrypt (первый раз, nginx встанет на ~минуту) |
| `make tls-renew` | обновить сертификат без простоя (в cron раз в неделю) |
| `make restore FILE=backups/mata_….sql.gz` | восстановить БД из бэкапа: контрольный бэкап (обязателен) → загрузка в отдельную БД `<db>_restore_<ts>` с `ON_ERROR_STOP` → проверки → второе подтверждение → атомарная подмена; прежняя БД остаётся `<db>_pre_restore_<ts>`, команды отката скрипт печатает в конце |
| `make smoke` | проверить health + каталог/баннеры изнутри web-контейнера |
| `make prod-logs` | логи прод-web | 
| `make prod-up` / `make prod-down` | поднять / остановить прод-стек |

`make` без аргументов — список всех команд.

**Первый деплой:** `cp .env.prod.example .env` → заполнить секреты → `cp nginx/mata.conf.example nginx/mata.conf` (домен+TLS) → `make prod-deploy`.

**Обновление:** `git pull && make prod-deploy` (бэкап делается автоматически перед сборкой).

**Откат:** `git checkout <tag-или-commit> && make prod-deploy`. Если откатить нужно и БД (после плохой миграции) — `make restore FILE=<последний-хороший-бэкап>`.

**Расписание на сервере (cron):**
```cron
0 4 * * *  cd /path/to/backend && ./deploy/backup.sh >> backups/cron.log 2>&1
0 3 * * 1  cd /path/to/backend && ./deploy/tls.sh renew >> logs/tls.log 2>&1
```
Без `BACKUP_S3_BUCKET` дамп остаётся только на диске сервера — это не бэкап: диск умрёт
вместе с БД и дампами. Бакет задаётся в `.env` (см. `.env.prod.example`).
Раз в месяц — **проверка восстановления** на staging (`make restore` из свежего бэкапа): бэкап без проверенного restore не считается рабочим.

**Troubleshooting:**
- `/v1/health` не отвечает → `make prod-logs` (ищем traceback); частые причины: незаполненный `.env` (fail-fast по секретам), недоступная БД, занятый порт.
- Падает на старте с `ImproperlyConfigured` → дефолтные секреты при `DJANGO_DEBUG=0` (см. п.1).
- Нет статики/стилей админки → `collectstatic` не отработал; смотреть логи web на шаге деплоя.

**Staging:** тот же `docker-compose.prod.yml` с отдельным `.env` (другие домен/БД/секреты) на отдельной машине/проекте — прогонять деплой и проверку восстановления здесь до прода.

## 6. Авария зоны Yandex Cloud — подъём прода в другой зоне

Прод (ВМ, диск БД, статический IP) живёт в **одной** зоне. Если зона недоступна (8.10.2026 —
пожар в ЦОД ru-central1-b после атаки БПЛА), ждать её восстановления не нужно: поднимаем прод
в другой зоне из последнего бэкапа. Решение — D-114.

1. **Cloud Shell** (консоль Yandex Cloud):
   ```bash
   curl -fsSL https://raw.githubusercontent.com/Smallfoi/mata-ecosystem/main/backend/deploy/yc-failover.sh | bash
   # другая зона: ZONE=ru-central1-d перед bash
   ```
   Скрипт создаёт в зоне (по умолчанию ru-central1-a) статический IP, пустой диск под БД и ВМ
   `mata-prod-<зона>` с меткой `mata-restore-latest=1`. Прежние ресурсы не трогает. Повторный
   запуск безопасен.
2. **Ждать «=== ГОТОВО»** (10–15 мин) — команду просмотра лога скрипт печатает. Сервер сам:
   разворачивает стек → скачивает последний дамп из бакета бэкапов (`fetch-latest-backup.sh`)
   → восстанавливает базу (`restore.sh`) → только потом заканчивает деплой. Не удалось
   восстановить — `FATAL`, деплой стоит, **домен не переводить**: сервер с пустой базой
   приняет заказы и регистрации, которые потеряются.
3. **DNS у Beget:** A-записи `mata-club.ru`, `www`, `api` → новый IP.
4. **TLS** выпустится сам: крон `tls-when-dns.sh` раз в 5 мин сверяет DNS с `PUBLIC_IP` из
   `.env` и только тогда зовёт `tls.sh issue` (неудачные проверки Let's Encrypt — в лимит).

**Что теряется:** всё после последнего ночного бэкапа (07:00 МСК) — оно на диске в недоступной
зоне. **Когда зона вернётся**, прежняя ВМ `mata-prod` поднимется со своими кронами (beat, опрос
часов, бэкап в тот же бакет) — **сразу остановить её** (`yc compute instance stop --name
mata-prod`), а данные с её диска переносить вручную, сверив с новой базой.
