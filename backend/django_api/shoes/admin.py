from django.contrib import admin
from unfold.admin import ModelAdmin

from common.adminutils import UserRefMixin

from .models import ShoeAsset


@admin.register(ShoeAsset)
class ShoeAssetAdmin(UserRefMixin, ModelAdmin):
    list_display = (
        "user_ref",
        "model",
        "status",
        "total_km",
        "max_km",
        "retired",
        "order_id",
        "created_at",
    )
    list_display_links = ("model",)
    list_filter = ("status", "retired")
    search_fields = ("user_id", "model", "order_id", "product_id")
    date_hierarchy = "created_at"
