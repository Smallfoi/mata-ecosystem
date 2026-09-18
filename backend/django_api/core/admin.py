from django.contrib import admin
from django.shortcuts import redirect
from django.urls import reverse

from core.models import AppConfig


@admin.register(AppConfig)
class AppConfigAdmin(admin.ModelAdmin):
    """Флаги приложения (D-89): один экран с галочками — что показывать в «Квартале».
    Меняется без пересборки; приложение подхватывает через GET /v1/config.

    Это синглтон-настройка, а не список записей: пункт меню ведёт сразу на форму
    с галочками (Тропы / Часы / Старты / …), без промежуточной таблицы из одной
    строки. Добавлять/удалять нечего.
    """

    readonly_fields = ("updated_at",)

    fields = (
        "show_trails",
        "show_watch",
        "show_races",
        "show_league_full",
        "show_sleeping_medals",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        # Синглтон: не показываем таблицу-список, сразу открываем единственную
        # запись на редактирование (создаём, если её ещё нет).
        obj = AppConfig.load()
        return redirect(reverse("admin:core_appconfig_change", args=[obj.pk]))
