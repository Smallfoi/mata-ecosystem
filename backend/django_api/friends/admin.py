from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import Friendship


@admin.register(Friendship)
class FriendshipAdmin(ModelAdmin):
    list_display = ("requester_id", "addressee_id", "status", "created_at", "updated_at")
    list_filter = ("status",)
    search_fields = ("requester_id", "addressee_id")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
