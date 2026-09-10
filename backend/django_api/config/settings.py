"""
Django-настройки бэкенда экосистемы МАТА (этап перехода с FastAPI).
Конфиг через переменные окружения (см. docker-compose.yml / .env.example).
БД — PostgreSQL (+ PostGIS включим для модуля территорий, D-09).
"""
import os
from pathlib import Path

from celery.schedules import crontab  # расписание beat (D-07)

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-secret-change-in-prod")
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"

# Прод: DJANGO_ALLOWED_HOSTS="api.mata-club.ru,mata-club.ru". Dev (по умолчанию) — "*".
ALLOWED_HOSTS = [
    h.strip() for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",") if h.strip()
]

INSTALLED_APPS = [
    # Unfold — современная тема админки. ДОЛЖНО идти ДО django.contrib.admin.
    "unfold",
    "unfold.contrib.filters",
    "unfold.contrib.forms",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "corsheaders",
    # Двухфакторный вход в админку (D-49): устройство TOTP + запасные коды.
    "django_otp",
    "django_otp.plugins.otp_totp",
    "django_otp.plugins.otp_static",
    "core",
    "accounts",
    "loyalty",
    "clubs",
    "leaderboard",
    "territories",
    "catalog",
    "orders",
    "shoes",
    "notifications",
    "legal",
    "runs",
    "analytics",
    "races",
    # Лига: профиль бегуна и зачёты (docs/LEAGUE_PLAN.md, Э1).
    "league",
    # Награды «Штамп МАТА» (D-64): 44 медали, ленивая выдача с гравировкой.
    "medals",
    # Тропы: отрезки маршрутов, попытки, доски (Э3, D-60).
    "trails",
    # Подключение часов (COROS и далее): точки входа для партнёрских интеграций.
    "integrations",
    # Тренировки извне: Health Connect, файлы, партнёрские API (Э2 плана лиги).
    "workouts",
    # Сотрудники админки и их доступ к вкладкам (S-12).
    "staff",
]

# Закреплённый владелец (S-13): если задан, спорить не с чем. Пусто — берётся
# строка OwnerPin в базе (ставится сама по первому суперпользователю).
MATA_OWNER_ID = os.environ.get("MATA_OWNER_ID", "")

# Права сотрудников считаются по вкладкам (S-12). Штатный ModelBackend оставляем:
# им живут суперпользователь, вход по паролю и старые группы.
AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "staff.backends.TabPermissionBackend",
]


def _tab(key):
    """Показывать пункт меню, только если вкладка открыта этому сотруднику.
    Импорт внутри — на момент чтения настроек приложения ещё не загружены."""
    def allowed(request):
        from staff.access import can
        return can(getattr(request, "user", None), key)
    return allowed


def _owner_only(request):
    """Пункт меню владельца. Проверяем закреплённую запись, а не флаг (S-13)."""
    from staff.owner import is_owner

    user = getattr(request, "user", None)
    return bool(getattr(user, "is_authenticated", False) and user.is_active
                and user.is_staff and is_owner(user))

# Так админка подписана в приложении-аутентификаторе (D-49).
OTP_TOTP_ISSUER = "МАТА"
# Пауза между попытками кода растёт экспоненциально: 1, 2, 4, 8… секунд (D-68).
# Без неё шестизначный код перебирается за вечер: миллион вариантов, а окно
# TOTP держит код 30 секунд и допускает соседние.
OTP_TOTP_THROTTLE_FACTOR = 1
OTP_STATIC_THROTTLE_FACTOR = 1

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # Должен идти сразу после аутентификации: добавляет user.is_verified().
    "django_otp.middleware.OTPMiddleware",
    # Сотрудник без второго фактора и без прав дальше админки не идёт (S-12).
    "staff.middleware.StaffOnboardingMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # Анти-брутфорс формы входа в админку: лимиты DRF её не покрывают (D-39).
    "common.adminsec.AdminLoginRateLimitMiddleware",
    # Второй шаг входа: код из приложения (D-49).
    "common.admin2fa.AdminOtpRequiredMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "kvartal"),
        "USER": os.environ.get("POSTGRES_USER", "kvartal"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "kvartal"),
        "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
    }
}

# CORS. Прод: DJANGO_CORS_ORIGINS="https://mata-club.ru,https://www.mata-club.ru" — тогда
# разрешаем только их. Dev (переменная пуста) — разрешаем всё (приложения и сайт
# ходят с устройства/localhost).
_cors_origins = [
    o.strip() for o in os.environ.get("DJANGO_CORS_ORIGINS", "").split(",") if o.strip()
]
if _cors_origins:
    CORS_ALLOW_ALL_ORIGINS = False
    CORS_ALLOWED_ORIGINS = _cors_origins
    # CSRF для Django-admin за HTTPS (нужны со схемой).
    CSRF_TRUSTED_ORIGINS = _cors_origins
else:
    CORS_ALLOW_ALL_ORIGINS = True

# За HTTPS-прокси (nginx/traefik): доверяем заголовку схемы. Безопасно и в dev.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Прод-харднинг (только при DJANGO_DEBUG=0) — в dev/на устройстве НЕ включается,
# чтобы не ломать http-доступ при локальном тесте. Требует HTTPS-прода (P0 #5).
if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SECURE_HSTS_SECONDS = 31_536_000  # 1 год
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    # Сессия админки живёт рабочий день, а не две недели (дефолт Django): за админкой
    # деньги и ПДн, а сессия на чужом/забытом устройстве — самый дешёвый способ туда
    # попасть. Закрыл браузер — сессия недействительна (D-39).
    SESSION_COOKIE_AGE = 8 * 60 * 60
    SESSION_EXPIRE_AT_BROWSER_CLOSE = True
    # Куки не уезжают на чужие сайты вместе с переходом: защита от CSRF на
    # уровне браузера, до того как проверка токена вообще начнётся.
    SESSION_COOKIE_SAMESITE = "Lax"
    CSRF_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_HTTPONLY = True
    # Referrer наружу не утекает: адрес админки с параметрами — сам по себе улика.
    SECURE_REFERRER_POLICY = "same-origin"

# P0-страховка: НЕ стартуем прод (DEBUG=0) с дефолтными секретами/ALLOWED_HOSTS=*.
# Защита от катастрофы №1 — выкатить прод с публичным dev-секретом.
from common.prodcheck import insecure_prod_settings  # noqa: E402

_insecure = insecure_prod_settings(
    debug=DEBUG,
    secret_key=SECRET_KEY,
    jwt_secret=os.environ.get("JWT_SECRET", "dev-secret-change-in-prod"),
    db_password=DATABASES["default"]["PASSWORD"],
    allowed_hosts=ALLOWED_HOSTS,
)
if _insecure:
    from django.core.exceptions import ImproperlyConfigured

    raise ImproperlyConfigured(
        "Небезопасная прод-конфигурация (DJANGO_DEBUG=0): задайте "
        + ", ".join(_insecure)
        + ". Запуск прода с дефолтами запрещён."
    )

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    # Аутентификация — свой JWT (common.security), session-auth/CSRF DRF не используем.
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    # Rate-limiting (P0 безопасность): на пользователя (по JWT) + по IP для анонимных.
    # Лимиты щедрые — активное приложение (карта обновляет территории каждые ~12с,
    # синки) не упирается, но брутфорс/накрутка/DoS отсекаются. /auth — отдельно жёстко.
    "DEFAULT_THROTTLE_CLASSES": [
        "common.throttling.UserJWTRateThrottle",
        "common.throttling.AnonIPRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "user": "300/min",
        # Анонимные: подняли со 120 — за одним IP оператора сидят сотни абонентов (CGNAT).
        "anon": "300/min",
        "auth": "20/min",       # вход/регистрация — НЕ ослаблять, это анти-брутфорс
        # Витринное чтение (D-36): дешёвые кэшируемые GET каталога/баннеров/контента —
        # 1 запрос к БД и ~14 мс каждый. Арифметика потолка: активный гость делает
        # 30–60 запросов/мин, значит 3000/мин ≈ 50–100 одновременных гостей за одним
        # IP оператора (CGNAT). При этом 50 rps — вдесятеро ниже измеренной пропускной
        # способности (581 rps), то есть как защита от перегруза лимит сохраняет смысл.
        # Упрёмся и в это — ответ кэш и CDN (D-31), а не дальнейшее повышение.
        "public": "3000/min",
    },
}

LANGUAGE_CODE = "ru-ru"
# Якутское время для отображения в админке (хранение в БД остаётся UTC, USE_TZ=True).
TIME_ZONE = "Asia/Yakutsk"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
# Прод: `collectstatic` собирает статику админки сюда, nginx раздаёт (см. docker-compose.prod).
STATIC_ROOT = os.environ.get("DJANGO_STATIC_ROOT", "/app/staticfiles")

# Медиа: фото товаров для экосистемы (Квартал тянет мини-фото кроссовок по сети).
# В dev файлы примонтированы из mata_store/assets (см. docker-compose: web → /srv/media).
# Прод — отдаёт реальный веб-сервер/CDN.
MEDIA_URL = "/media/"
MEDIA_ROOT = os.environ.get("DJANGO_MEDIA_ROOT", "/srv/media")

# Хранилище медиа (D-31): S3/Object Storage при заданных MEDIA_S3_* (прод), иначе
# локальный диск (dev/CI). Загрузки строят URL через default_storage.url() → работают
# в обоих режимах. django-storages/boto3 нужны только при активном S3.
from common.media import media_storages  # noqa: E402

STORAGES = media_storages(os.environ)

# URL сайта для админ-превью (iframe). Dev — локальный http.server сайта;
# прод — реальный домен витрины (задаётся env). Сайт читает ?preview=1.
SITE_PREVIEW_URL = os.environ.get("SITE_PREVIEW_URL", "http://localhost:5581")

# URL web-сборки приложения (SportStore) для пиксель-точного превью.
# ВАЖНО: локальная сборка идёт в ОТДЕЛЬНУЮ папку build/web-local. В build/web
# лежит прод-сборка для S3 (собирается с --base-href /mata-app-preview/ и с
# боевым API) — раньше они затирали друг друга, и превью в Конструкторе гасло:
# белый экран (файлы 404 мимо base href) либо пустые экраны (боевой API режет
# CORS с localhost).
# Сборка (ВСЕ флаги важны):
#   cd mata_store && flutter build web --release --pwa-strategy=none
#     --no-web-resources-cdn --dart-define=CONSOLE_EDIT=1 --dart-define=PREVIEW=1
#     --dart-define=SPORT_STORE_API_BASE_URL=http://localhost:8000/v1
#     --no-tree-shake-icons --output=build/web-local
#   • CONSOLE_EDIT=1 — включает мост правки (без него «править нельзя»);
#   • PREVIEW=1 — показывает черновики каталога;
#   • --no-web-resources-cdn — CanvasKit локально (CDN gstatic недоступен → белый экран);
#   • --output=build/web-local — не трогать прод-сборку в build/web.
# затем: python tools/preview_server.py "<repo>/mata_store/build/web-local" 5579
APP_PREVIEW_URL = os.environ.get("APP_PREVIEW_URL", "http://localhost:5579")

# Куда ведёт кнопка «Открыть сайт» в меню админки. По умолчанию Django считает,
# что сайт лежит в корне того же хоста — у нас там только API, и кнопка вела в 404.
# Обычно совпадает с адресом превью, поэтому отдельная переменная нужна лишь если
# публичный домен витрины отличается от того, что показывается в конструкторе.
SITE_PUBLIC_URL = os.environ.get("SITE_PUBLIC_URL") or SITE_PREVIEW_URL

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ── Unfold (тема + структура админки) ───────────────────────────────────────
from django.urls import reverse_lazy  # noqa: E402

UNFOLD = {
    "SITE_TITLE": "МАТА Админ",
    "SITE_HEADER": "МАТА — администрирование",
    "SITE_SUBHEADER": "Экосистема: Квартал · Store · Сайт",
    # Куда ведёт «Открыть сайт» в меню внизу слева. Задавать нужно ИМЕННО здесь:
    # Unfold подставляет свой site_url и `admin.site.site_url` не смотрит.
    "SITE_URL": SITE_PUBLIC_URL,
    "SHOW_HISTORY": True,
    "SHOW_VIEW_ON_SITE": False,
    "DASHBOARD_CALLBACK": "config.dashboard.dashboard_callback",
    # Нижнее меню пользователя (кнопка «admin» внизу слева, рядом с выбором темы):
    # «Настройки» → свой аккаунт (почта, имя, смена пароля). Профиль/пароль — тут, не отдельно.
    "ACCOUNT": {
        "navigation": [
            {"title": "Настройки",
             "link": lambda request: (
                 reverse_lazy("admin:auth_user_change", args=[request.user.pk])
                 if getattr(request.user, "pk", None) else reverse_lazy("admin:index")
             )},
            # Смена пароля — не отдельным пунктом, а кнопкой ВНУТРИ «Настроек» (карточка аккаунта).
        ],
    },
    "COLORS": {
        # Брендовый electric blue (#0A84FF) как акцент — оттенки tailwind.
        "primary": {
            "50": "239 246 255",
            "100": "219 234 254",
            "200": "191 219 254",
            "300": "147 197 253",
            "400": "96 165 250",
            "500": "10 132 255",
            "600": "37 99 235",
            "700": "29 78 216",
            "800": "30 64 175",
            "900": "30 58 138",
            "950": "23 37 84",
        },
    },
    "SIDEBAR": {
        "show_search": True,
        "show_all_applications": False,
        "navigation": [
            {
                "title": "Обзор",
                "separator": True,
                "items": [
                    # Дашборд — сводка по экосистеме (заказы, пользователи, баллы, античит…).
                    {"title": "Дашборд", "icon": "space_dashboard",
                     "link": reverse_lazy("admin:index"),
                     "permission": _tab("dashboard")},
                ],
            },
            {
                "title": "Каталог",
                "separator": True,
                "items": [
                    {"title": "Товары", "icon": "inventory_2",
                     "link": reverse_lazy("admin:catalog_product_changelist"),
                     "permission": _tab("catalog.products")},
                    {"title": "Категории", "icon": "category",
                     "link": reverse_lazy("admin:catalog_category_changelist"),
                     "permission": _tab("catalog.categories")},
                    {"title": "Баннеры", "icon": "image",
                     "link": reverse_lazy("admin:catalog_banner_changelist"),
                     "permission": _tab("catalog.banners")},
                    {"title": "Отзывы", "icon": "reviews",
                     "link": reverse_lazy("admin:catalog_review_changelist"),
                     "permission": _tab("catalog.reviews")},
                ],
            },
            {
                "title": "Магазин",
                "separator": True,
                "items": [
                    {"title": "Заказы", "icon": "shopping_cart",
                     "link": reverse_lazy("admin:orders_order_changelist"),
                     "permission": _tab("orders")},
                    {"title": "Баллы", "icon": "loyalty",
                     "link": reverse_lazy("admin:loyalty_loyaltytransaction_changelist"),
                     "permission": _tab("loyalty")},
                    {"title": "Кроссовки", "icon": "directions_run",
                     "link": reverse_lazy("admin:shoes_shoeasset_changelist"),
                     "permission": _tab("shoes")},
                ],
            },
            {
                "title": "Сообщество",
                "separator": True,
                "items": [
                    {"title": "Клубы", "icon": "groups",
                     "link": reverse_lazy("admin:clubs_club_changelist"),
                     "permission": _tab("clubs")},
                    {"title": "Заявки в клуб", "icon": "how_to_reg",
                     "link": reverse_lazy("admin:clubs_clubjoinrequest_changelist"),
                     "permission": _tab("clubs")},
                    {"title": "Участники клубов", "icon": "badge",
                     "link": reverse_lazy("admin:clubs_clubmember_changelist"),
                     "permission": _tab("clubs")},
                    {"title": "Челленджи клубов", "icon": "emoji_events",
                     "link": reverse_lazy("admin:clubs_clubchallenge_changelist"),
                     "permission": _tab("clubs")},
                    {"title": "Пользователи", "icon": "person",
                     "link": reverse_lazy("admin:accounts_account_changelist"),
                     "permission": _tab("accounts")},
                    {"title": "Уведомления", "icon": "notifications",
                     "link": reverse_lazy("admin:notifications_notification_changelist"),
                     "permission": _tab("notifications")},
                ],
            },
            {
                "title": "Бег и модерация",
                "separator": True,
                "items": [
                    # Разбор помеченных забегов — отдельной страницей: список забегов
                    # это архив, а решение принимают, глядя на бегуна целиком.
                    {"title": "Проверка забегов", "icon": "gavel",
                     "link": reverse_lazy("runs_review"),
                     "permission": _tab("runs")},
                    {"title": "Забеги (анти-чит)", "icon": "sports_score",
                     "link": reverse_lazy("admin:runs_run_changelist"),
                     "permission": _tab("runs")},
                ],
            },
            {
                "title": "Право и согласия",
                "items": [
                    {"title": "Документы", "icon": "gavel",
                     "link": reverse_lazy("admin:legal_legaldocument_changelist"),
                     "permission": _tab("legal")},
                    {"title": "Согласия", "icon": "fact_check",
                     "link": reverse_lazy("admin:legal_userconsent_changelist"),
                     "permission": _tab("legal")},
                ],
            },
            {
                "title": "Витрина",
                "separator": True,
                "items": [
                    # Конструктор = live-превью + правка + публикация (отдельные
                    # страницы «Превью» убраны — конструктор их заменяет).
                    {"title": "Конструктор", "icon": "dashboard_customize",
                     "link": reverse_lazy("merch_console"),
                     "permission": _tab("merch")},
                ],
            },
            {
                "title": "Мониторинг",
                "separator": True,
                "items": [
                    # «Вкладка Ошибки» внутри админки (GlitchTip по API, D-32).
                    {"title": "Ошибки", "icon": "bug_report",
                     "link": reverse_lazy("errors_console"),
                     "permission": _tab("errors")},
                    # Свободное место на дисках/в БД — наглядно (D-?).
                    {"title": "Диски", "icon": "storage",
                     "link": reverse_lazy("admin_storage"),
                     "permission": _tab("storage")},
                    # История выгрузок из 1С: что и когда пришло (D-62).
                    {"title": "Журнал обмена", "icon": "sync_alt",
                     "link": reverse_lazy("onec_log"),
                     "permission": _tab("onec_log")},
                ],
            },
            {
                "title": "Доступ",
                "separator": True,
                "items": [
                    # Сотрудники и их права (S-12). Пункт виден ТОЛЬКО владельцу:
                    # правом раздавать права поделиться нельзя.
                    {"title": "Сотрудники", "icon": "manage_accounts",
                     "link": reverse_lazy("staff_list"),
                     "permission": _owner_only},
                ],
            },
        ],
    },
}

# ── Кэш (D-07/D-28) ─────────────────────────────────────────────────────────
# Общий кэш для rate-limit, SMS-OTP, мгновенного бана, баланса/лейдерборда.
# Прод (несколько воркеров gunicorn) ОБЯЗАН использовать общий Redis, иначе данные
# одного воркера не видны другим (OTP/лимиты ломаются). Без REDIS_URL — LocMem (dev).
_redis_url = os.environ.get("REDIS_URL", "")
if _redis_url:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": _redis_url,
        }
    }
else:
    CACHES = {
        "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}
    }

# ── Celery: фоновые задачи/очереди/beat (D-07) ──────────────────────────────
# Брокер — Redis (тот же REDIS_URL, что и кэш; отдельный CELERY_BROKER_URL перекрывает).
# БЕЗ брокера — EAGER: задачи выполняются синхронно inline (dev/CI/тесты не требуют
# Redis и работают как раньше). В проде поднимаем `celery worker` + `celery beat`.
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "") or _redis_url
CELERY_RESULT_BACKEND = (
    os.environ.get("CELERY_RESULT_BACKEND", "") or CELERY_BROKER_URL or None
)
CELERY_TASK_ALWAYS_EAGER = not CELERY_BROKER_URL  # нет брокера → синхронно inline
CELERY_TASK_EAGER_PROPAGATES = True  # в eager-режиме исключения задач всплывают (тесты видят падения)
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TIMEZONE = TIME_ZONE
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
# Периодические задачи (beat): статическое расписание — без django-celery-beat (меньше
# движущихся частей). Чистка протухших зон/защит раз в сутки в 03:30 (Asia/Yakutsk).
# Сроки хранения данных (152-ФЗ §2: авто-удаление данных «без цели»). 0 = не удалять.
# События аналитики и ПРОЧИТАННЫЕ уведомления живут ограниченно; лояльность/заказы/забеги —
# не трогаем (это история/финансы, нужны). Сырой GPS на бэке не хранится (приватность §2).
ANALYTICS_EVENT_RETENTION_DAYS = int(os.environ.get("ANALYTICS_EVENT_RETENTION_DAYS", "365"))
READ_NOTIFICATION_RETENTION_DAYS = int(os.environ.get("READ_NOTIFICATION_RETENTION_DAYS", "90"))

CELERY_BEAT_SCHEDULE = {
    "cleanup-territories-daily": {
        "task": "territories.cleanup_expired_territories",
        "schedule": crontab(hour=3, minute=30),
    },
    "cleanup-old-data-daily": {
        "task": "core.cleanup_old_data",
        "schedule": crontab(hour=4, minute=0),
    },
    # Неоплаченные заказы (D-72): не оплатили за 30 минут — отмена и возврат баллов.
    "expire-unpaid-orders": {
        "task": "orders.expire_unpaid_orders",
        "schedule": crontab(minute="*/5"),
    },
    # Авто-парсер афиши «Стартов»: раз в сутки в 05:00 (Asia/Yakutsk). Идемпотентно
    # (upsert по source+external_id). Источники — races/importers/.
    # Треки живут 14 дней и удаляются (D-60) — это условие всей затеи с тропами.
    "cleanup-tracks-daily": {
        "task": "trails.cleanup_tracks",
        "schedule": crontab(hour=3, minute=50),
    },
    "import-races-daily": {
        "task": "races.import_races",
        "schedule": crontab(hour=5, minute=0),
    },
}

# Авто-парсер «Стартов»: URL нормализованного JSON-фида забегов (races/importers/jsonfeed).
# Пусто → JSON-фид-импортёр молчит (работает только демо-источник и ручные записи).
RACES_IMPORT_FEED_URL = os.environ.get("RACES_IMPORT_FEED_URL", "")

# Обмен с 1С (D-62). Токен выдаётся стороне 1С и живёт в секретах (Lockbox), не в коде.
# Пусто — приём выключен: лучше отказать, чем принимать номенклатуру без проверки.
INTEGRATION_1C_TOKEN = os.environ.get("INTEGRATION_1C_TOKEN", "")

# ── Sentry / GlitchTip (видимость ошибок, D-25/D-32: self-host РФ) ───────────
# Каркас: подключается ТОЛЬКО при заданном SENTRY_DSN. Без ключа — no-op, без
# накладных расходов. DSN даёт наш self-host GlitchTip (Sentry-совместимый) —
# см. docs/OBSERVABILITY.md. `release` привязывает ошибки к версии (регрессии,
# release-health). `send_default_pii=False` — 152-ФЗ, не шлём ПДн в события.
SENTRY_DSN = os.environ.get("SENTRY_DSN", "")
if SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration

    from common import sentry_scrub

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[DjangoIntegration()],
        environment=os.environ.get(
            "SENTRY_ENVIRONMENT", "dev" if DEBUG else "production"
        ),
        release=os.environ.get("SENTRY_RELEASE") or None,  # git sha/версия → трекинг регрессий
        traces_sample_rate=float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0")),
        send_default_pii=False,  # 152-ФЗ: не отправляем ПДн в события по умолчанию
        # `send_default_pii=False` убирает только то, что SDK добавляет САМ (тело
        # запроса, cookies, IP). Телефон в тексте исключения или токен в локальной
        # переменной он не тронет — их вычищаем сами (common/sentry_scrub.py).
        before_send=sentry_scrub.before_send,
        before_breadcrumb=sentry_scrub.before_breadcrumb,
    )
