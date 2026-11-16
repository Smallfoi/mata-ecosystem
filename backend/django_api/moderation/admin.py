"""Разбор жалоб и чёрный список в админке.

Жалоба без видимого решения бесполезна: человек не узнает, что с ней стало,
а модератор через неделю не вспомнит, почему отклонил. Поэтому в списке сразу
видно причину, цель, статус и дату, а в карточке — поле решения.
"""
from django.contrib import admin
from django.utils import timezone

from accounts.models import Account
from clubs.models import Club

from .models import Block, Report


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ("created_at", "reason", "target_type", "target_label",
                    "reporter_label", "status")
    list_filter = ("status", "reason", "target_type")
    search_fields = ("target_id", "reporter_id", "comment")
    readonly_fields = ("reporter_id", "target_type", "target_id", "reason",
                       "comment", "created_at", "resolved_at")
    fields = ("created_at", "reporter_id", "target_type", "target_id", "reason",
              "comment", "status", "resolution", "resolved_at")
    actions = ["mark_accepted", "mark_rejected"]

    @admin.display(description="Цель")
    def target_label(self, obj):
        if obj.target_type == Report.TARGET_CLUB:
            club = Club.objects.filter(id=obj.target_id).first()
            return club.name if club else obj.target_id
        acc = Account.objects.filter(id=obj.target_id).first()
        return (acc.name or acc.id) if acc else obj.target_id

    @admin.display(description="Заявитель")
    def reporter_label(self, obj):
        acc = Account.objects.filter(id=obj.reporter_id).first()
        return (acc.name or acc.id) if acc else obj.reporter_id

    def _resolve(self, queryset, status):
        return queryset.update(status=status, resolved_at=timezone.now())

    @admin.action(description="Приняты меры")
    def mark_accepted(self, request, queryset):
        self._resolve(queryset, Report.ACCEPTED)

    @admin.action(description="Отклонить")
    def mark_rejected(self, request, queryset):
        self._resolve(queryset, Report.REJECTED)

    def save_model(self, request, obj, form, change):
        if obj.status != Report.NEW and not obj.resolved_at:
            obj.resolved_at = timezone.now()
        super().save_model(request, obj, form, change)


@admin.register(Block)
class BlockAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user_id", "blocked_id")
    search_fields = ("user_id", "blocked_id")
    # Чёрный список — выбор пользователя, а не модератора: смотреть можно,
    # править из админки нечего.
    readonly_fields = ("user_id", "blocked_id", "created_at")

    def has_add_permission(self, request):
        return False
