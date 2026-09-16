from django.urls import path

from . import views

urlpatterns = [
    path("account", views.account),
    path("transactions", views.transactions),
    path("redeem", views.redeem),
    path("partners", views.partners),
]
