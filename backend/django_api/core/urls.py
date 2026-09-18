from django.urls import path

from . import views

urlpatterns = [
    path("health", views.health, name="health"),
    path("health/ready", views.readiness, name="readiness"),  # readiness-проба (db+cache)
    path("config", views.app_config, name="app_config"),  # серверные флаги (D-87)
]
