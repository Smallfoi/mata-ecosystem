from django.contrib import admin

from core.models import AppConfig


@admin.register(AppConfig)
class AppConfigAdmin(admin.ModelAdmin):
    """Флаги приложения (D-89): одна строка, галочки — что показывать в «Квартале».
    Меняется без пересборки; приложение подхватывает через GET /v1/config."""

    list_display = (
        "__str__",
        "show_trails",
        "show_watch",
        "show_races",
        "show_league_full",
        "show_sleeping_medals",
        "updated_at",
    )
    readonly_fields = ("updated_at",)

    def has_add_permission(self, request):
        # Singleton: если строка уже есть — новую не добавляем.
        return not AppConfig.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
