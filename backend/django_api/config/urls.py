from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin

from common import admin2fa
from django.urls import include, path

admin.site.site_header = "МАТА — администрирование экосистемы"
admin.site.site_title = "МАТА Admin"
admin.site.index_title = "Управление: каталог, заказы, клубы, баллы"
# «Открыть сайт» настраивается в UNFOLD["SITE_URL"] (settings), а не здесь:
# тема подставляет свой site_url и это поле игнорирует.

from accounts import views as account_views
from catalog import views as catalog_views
from config.admin_views import (
    admin_storage,
    merch_banner,
    merch_banner_create,
    merch_banner_delete,
    merch_banner_reorder,
    merch_banners,
    merch_console,
    merch_product,
    merch_products,
    merch_reorder,
    merch_site_content,
    merch_site_image,
    merch_site_video,
)
from notifications import views as notif_views
from league import views as league_views
from medals import views as medals_views
from trails import views as trails_views
from legal import views as legal_views
from runs import views as runs_views
from clubs import views as clubs_views
from orders import views as orders_views
from races import views as races_views
from shoes import views as shoes_views
from territories import views as territories_views
from analytics import views as analytics_views
from config.errors_view import error_detail, errors_console
from config.onec_log_view import onec_log
from config.runs_review_view import runs_review
from config.order_return_view import order_return
from staff import views as staff_views

urlpatterns = [
    # Конструктор (live-превью + правка + публикация). Отдельные «Превью» убраны.
    path("admin/merch/", merch_console, name="merch_console"),
    path("admin/merch/products", merch_products, name="merch_products"),
    path("admin/merch/reorder", merch_reorder, name="merch_reorder"),
    path("admin/merch/product/<str:pid>", merch_product, name="merch_product"),
    path("admin/merch/site-content", merch_site_content, name="merch_site_content"),
    path("admin/merch/site-image", merch_site_image, name="merch_site_image"),
    path("admin/merch/site-video", merch_site_video, name="merch_site_video"),
    # Баннеры (промо) — CRUD в конструкторе.
    path("admin/merch/banners", merch_banners, name="merch_banners"),
    path("admin/merch/banner-create", merch_banner_create, name="merch_banner_create"),
    path("admin/merch/banner-reorder", merch_banner_reorder, name="merch_banner_reorder"),
    path("admin/merch/banner/<int:bid>", merch_banner, name="merch_banner"),
    path("admin/merch/banner/<int:bid>/delete", merch_banner_delete, name="merch_banner_delete"),
    # «Ошибки» — GlitchTip внутри нашей админки (D-32). ДО admin/ catch-all.
    path("admin/errors/", errors_console, name="errors_console"),
    path("admin/storage/", admin_storage, name="admin_storage"),
    path("admin/1c-log/", onec_log, name="onec_log"),
    # «Проверка забегов» — разбор помеченных анти-читом (S-04 ф.2). ДО admin/.
    path("admin/runs-review/", runs_review, name="runs_review"),
    path("admin/order-return/<int:pk>/", order_return, name="order_return"),
    path("admin/errors/<str:issue_id>/", error_detail, name="error_detail"),
    # Сотрудники и права (S-12). Тоже ДО admin/ — иначе перехватит catch-all.
    # Свой второй фактор. НЕ под /admin/2fa/ — тот префикс пропускает мимо
    # проверки кода, а управлять фактором вправе лишь прошедший его (D-69).
    path("admin/account/security/", staff_views.account_security,
         name="account_security"),
    path("admin/staff/", staff_views.staff_list, name="staff_list"),
    path("admin/staff/create", staff_views.staff_create, name="staff_create"),
    path("admin/staff/<int:pk>/", staff_views.staff_member, name="staff_member"),
    path("admin/staff/<int:pk>/rights", staff_views.staff_rights, name="staff_rights"),
    path("admin/staff/<int:pk>/action", staff_views.staff_action, name="staff_action"),
    # Приём приглашения — единственная публичная страница раздела.
    path("admin/invite/<str:token>/", staff_views.staff_invite, name="staff_invite"),
    path("admin/no-access/", staff_views.staff_no_access, name="staff_no_access"),
    # Привязка второго фактора СЕБЕ. Выше admin/2fa/ — иначе путь съест ввод кода.
    path("admin/2fa/setup/", staff_views.otp_setup, name="staff_otp_setup"),
    # Второй шаг входа должен стоять выше админки, иначе путь перехватит она.
    path("admin/2fa/", admin2fa.verify_view, name="admin-2fa"),
    path("admin/", admin.site.urls),
    path("v1/", include("core.urls")),
    path("v1/auth/", include("accounts.urls")),
    path("v1/profile", account_views.update_profile),
    path("v1/profile/avatar", account_views.profile_avatar),
    # Аккаунт: приватность (§2) и удаление аккаунта/данных (§13 LAUNCH_READINESS).
    path("v1/account/privacy", account_views.account_privacy),
    path("v1/account/export", account_views.account_export),  # выгрузка ПДн (152-ФЗ §2)
    path("v1/account/delete", account_views.delete_account),
    path("v1/me/stats", account_views.me_stats),
    path("v1/me/digest", account_views.me_digest),
    # Награды «Штамп МАТА» (D-64): состояние 44 медалей + ленивая выдача.
    path("v1/me/medals", medals_views.me_medals),
    # Продуктовая аналитика (D-30): приём клиентских событий.
    path("v1/events", analytics_views.events),
    path("v1/loyalty/", include("loyalty.urls")),
    # Клубы — порядок важен: 'me' и 'requests/...' раньше generic '<club_id>'.
    path("v1/clubs", clubs_views.clubs_root),
    path("v1/clubs/war", clubs_views.war),
    path("v1/clubs/me", clubs_views.my_club),
    path("v1/clubs/requests/<str:req_id>/approve", clubs_views.approve_request),
    path("v1/clubs/requests/<str:req_id>/reject", clubs_views.reject_request),
    path("v1/clubs/<str:club_id>", clubs_views.club_detail_or_update),
    path("v1/clubs/<str:club_id>/join", clubs_views.join_club),
    path("v1/clubs/<str:club_id>/leave", clubs_views.leave_club),
    path("v1/clubs/<str:club_id>/logo", clubs_views.club_logo),
    path("v1/clubs/<str:club_id>/cover", clubs_views.club_cover),
    path("v1/clubs/<str:club_id>/challenge", clubs_views.club_challenge),
    path("v1/clubs/<str:club_id>/requests", clubs_views.club_requests),
    path("v1/leaderboard/", include("leaderboard.urls")),
    # Лига: зачёты и профиль бегуна (docs/LEAGUE_PLAN.md).
    path("v1/league/", include("league.urls")),
    path("v1/runner/profile", league_views.profile),
    # Тропы: приём трека, список, доски (D-60).
    path("v1/runs/track", trails_views.submit_track),
    path("v1/trails/", include("trails.urls")),
    # Подключение часов: адреса нужны в заявке к COROS до выдачи ключей.
    path("v1/integrations/", include("integrations.urls")),
    # Тренировки из внешних источников (часы, файлы).
    path("v1/workouts/", include("workouts.urls")),
    # Территории (PostGIS, D-09)
    path("v1/territories/capture", territories_views.capture),
    path("v1/territories", territories_views.list_territories),
    # Вечный личный след (для профиля «исследовано км²»)
    path("v1/footprint", territories_views.footprint),
    # Каталог Store (D-13) — контракт как у ApiProductRepository в SportStore.
    # Порядок важен: 'search' и 'price-range' раньше generic '<pid>'.
    path("v1/categories", catalog_views.categories),
    path("v1/products/search", catalog_views.product_search),
    path("v1/products/price-range", catalog_views.product_price_range),
    path("v1/products", catalog_views.products),
    path("v1/products/<str:pid>", catalog_views.product_detail),
    path("v1/products/<str:pid>/reviews", catalog_views.product_reviews),
    path("v1/reviews/photo", catalog_views.review_photo),
    path("v1/brands", catalog_views.brands),
    path("v1/sizes", catalog_views.sizes),
    path("v1/banners", catalog_views.banners),
    # Редактируемый контент сайта (мини-CMS для конструктора).
    path("v1/site/content", catalog_views.site_content),
    # Заказы Store (D-13)
    path("v1/orders", orders_views.orders),
    path("v1/orders/<str:order_id>/pay", orders_views.pay_order),  # инициировать оплату
    # Статус оплаты с перепроверкой у провайдера: страховка от потерянного вебхука.
    path("v1/orders/<str:order_id>/payment", orders_views.payment_state),
    # Вебхук ЮKassa: адрес прописывается в личном кабинете магазина. Без токена —
    # тело не подписано, подтверждение статуса идёт перезапросом к API (см. views).
    path("v1/payments/webhook", orders_views.payment_webhook),
    # Уведомления (лента экосистемы)
    path("v1/notifications", notif_views.notifications),
    path("v1/notifications/read", notif_views.notifications_read),
    path("v1/devices/register", notif_views.register_device),  # токен устройства для пушей
    # История пробежек (синхронизация с устройства, сводки — без сырого GPS).
    path("v1/runs", runs_views.runs),
    # Документы и согласия (единые для всех продуктов, §3 LAUNCH_READINESS).
    # Порядок: 'consent/revoke' раньше generic 'consent'.
    path("v1/legal/documents", legal_views.documents),
    path("v1/legal/consent/revoke", legal_views.revoke),
    path("v1/legal/consent", legal_views.accept),
    path("v1/legal/consents", legal_views.my_consents),
    # Кроссовки — трекер износа (связка Store ↔ Квартал, ECOSYSTEM_API §2.5).
    # Порядок: 'pending' раньше generic '<id>/...'.
    path("v1/races", races_views.races),
    # 'regions' раньше generic '<race_id>', иначе перехватится как id забега.
    path("v1/races/regions", races_views.race_regions),
    path("v1/races/<str:race_id>", races_views.race_detail),
    path("v1/shoes", shoes_views.shoes),
    path("v1/shoes/pending", shoes_views.shoes_pending),
    path("v1/shoes/<str:shoe_id>/confirm", shoes_views.shoe_confirm),
    path("v1/shoes/<str:shoe_id>/distance", shoes_views.shoe_distance),
    path("v1/shoes/<str:shoe_id>", shoes_views.shoe_delete),  # DELETE
]

# Фото товаров по сети (dev: из примонтированной папки mata_store; прод — CDN).
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
