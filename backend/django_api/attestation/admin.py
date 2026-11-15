from django.contrib import admin
from unfold.admin import ModelAdmin

from common.adminutils import UserRefMixin

from .models import IntegrityCheck


@admin.register(IntegrityCheck)
class IntegrityCheckAdmin(UserRefMixin, ModelAdmin):
    """Только просмотр: записи — сигнал модератору (D-129), правок не требуют."""

    list_display = ("user_ref", "subject_id", "platform", "status", "reasons",
                    "device", "app", "created_at")
    list_filter = ("status", "platform")
    search_fields = ("=user_id", "=subject_id")
    exclude = ("token",)
    readonly_fields = ("subject_type", "subject_id", "user_id", "platform", "status",
                       "reasons", "expected_hash", "device", "app", "licensing",
                       "verdict", "created_at", "checked_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
