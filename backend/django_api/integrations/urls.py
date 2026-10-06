from django.urls import path

from . import views

urlpatterns = [
    path("coros/callback", views.coros_callback),
    path("coros/push", views.coros_push),
    path("coros/status", views.coros_status),
    path("suunto/account", views.suunto_account),
    path("suunto/connect", views.suunto_connect),
    path("suunto/callback", views.suunto_callback),
    path("suunto/disconnect", views.suunto_disconnect),
    path("suunto/push", views.suunto_push),
    path("suunto/status", views.suunto_status),
    path("1c/categories", views.onec_categories),
    path("1c/catalog", views.onec_catalog),
    path("1c/prices", views.onec_prices),
    path("1c/orders", views.onec_orders),
    path("1c/orders/ack", views.onec_orders_ack),
    path("1c/orders/status", views.onec_order_status),
    path("1c/status", views.onec_status),
]
