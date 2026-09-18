from django.contrib import admin

from core.models import FeatureFlag


@admin.register(FeatureFlag)
class FeatureFlagAdmin(admin.ModelAdmin):
    """Флаги приложения (D-89): список направлений, в каждое можно провалиться и
    увидеть детально — что это, на каком этапе, что сделано и что осталось —
    плюс переключатель «Показывать в приложении». Приложение читает только
    `enabled` через GET /v1/config (без пересборки). Набор направлений фиксирован
    (заводится миграцией вместе с поддержкой в клиенте), поэтому add/delete закрыты.
    """

    list_display = ("title", "enabled", "stage", "updated_at")
    list_editable = ("enabled",)  # быстрый тумблер прямо в списке
    list_display_links = ("title",)  # клик по названию → детальная карточка
    ordering = ("order", "title")

    readonly_fields = ("key", "updated_at")
    fields = ("title", "key", "stage", "enabled", "summary", "done", "todo", "updated_at")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
