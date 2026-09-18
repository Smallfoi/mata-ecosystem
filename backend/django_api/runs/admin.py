from django.contrib import admin
from unfold.admin import ModelAdmin

from common.adminutils import UserRefMixin

from .models import Run
from .review import approve_run, reject_run


@admin.action(description="Одобрить забег (снять флаг + начислить очки)")
def approve_runs(modeladmin, request, queryset):
    approved = awarded = 0
    for run in list(queryset.filter(flagged=True)):
        pts = approve_run(run, by=request.user.get_username())
        approved += 1
        if pts > 0:
            awarded += 1
    modeladmin.message_user(
        request, f"Одобрено забегов: {approved} (с начислением очков: {awarded})"
    )


@admin.action(description="Подтвердить нарушение (оставить без очков)")
def reject_runs(modeladmin, request, queryset):
    n = revoked = 0
    for run in list(queryset.filter(flagged=True)):
        revoked += reject_run(run, by=request.user.get_username())
        n += 1
    msg = f"Подтверждено нарушений: {n}"
    if revoked:
        msg += f"; списано ранее начисленных баллов: {revoked}"
    modeladmin.message_user(request, msg)


@admin.register(Run)
class RunAdmin(UserRefMixin, ModelAdmin):
    list_display = (
        "user_ref", "distance_m", "duration_s", "points_awarded",
        "flagged", "review_state", "flag_reason", "captured_territory", "finished_at",
    )
    list_display_links = ("user_ref",)
    list_filter = ("flagged", "captured_territory")
    search_fields = ("id", "user_id", "flag_reason")
    date_hierarchy = "finished_at"
    actions = [approve_runs, reject_runs]

    @admin.display(description="Разбор")
    def review_state(self, obj):
        if not obj.flagged and obj.reviewed_at:
            return "одобрен"
        if obj.flagged and obj.reviewed_at:
            return "нарушение"
        if obj.flagged:
            return "ждёт разбора"
        return "—"

    def get_readonly_fields(self, request, obj=None):
        # Цифры забега не правим вручную (целостность анти-чита S-04): форма
        # read-only. Модерация флага — только через действия approve/reject.
        return [f.name for f in self.model._meta.fields]

    def has_add_permission(self, request):
        return False  # забеги создаёт только приложение
