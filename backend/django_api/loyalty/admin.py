from django.contrib import admin
from unfold.admin import ModelAdmin

from common.adminutils import ExportCsvMixin, UserRefMixin

from .models import LoyaltyPartner, LoyaltyTransaction


@admin.register(LoyaltyTransaction)
class LoyaltyTransactionAdmin(ExportCsvMixin, UserRefMixin, ModelAdmin):
    list_display = (
        "user_ref",
        "amount",
        "source",
        "description",
        "order_id",
        "created_at",
    )
    list_display_links = ("user_ref",)
    list_filter = ("source",)
    search_fields = ("id", "user_id", "description", "order_id", "run_id")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    readonly_fields = ("id",)
    actions = ("export_as_csv",)
    csv_filename = "loyalty_transactions"
    export_fields = ("id", "user_id", "amount", "source", "description",
                     "order_id", "run_id", "created_at")

    # Финансовый реестр: баланс/уровень пользователя = сумма транзакций
    # (loyalty.models.balance_of). Ручная правка/удаление молча исказит баланс,
    # поэтому существующие записи — только просмотр. Корректировка — новой записью
    # (add остаётся доступным), а не редактированием/удалением истории.
    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(LoyaltyPartner)
class LoyaltyPartnerAdmin(ModelAdmin):
    list_display = ("name", "category", "city", "points_percent", "is_active", "created_at")
    list_filter = ("category", "is_active", "city")
    list_editable = ("is_active",)
    search_fields = ("name", "address", "description", "city")
    ordering = ("name",)
    fieldsets = (
        ("Партнёр", {"fields": ("name", "category", "emoji", "logo", "description")}),
        ("Где", {"fields": ("city", "address", "lat", "lng")}),
        ("Баллы и показ", {"fields": ("points_percent", "is_active")}),
    )


# ── Программа лояльности v1 ──────────────────────────────────────────────────
import json  # noqa: E402

from django import forms  # noqa: E402
from django.utils.html import format_html, format_html_join  # noqa: E402

from . import config as loyalty_config  # noqa: E402
from .models import (  # noqa: E402
    LoyaltyEvent,
    LoyaltyLot,
    LoyaltyRedemption,
    LoyaltySetting,
    LoyaltySettingChange,
    LoyaltyStatus,
)


class _ReadOnlyAdmin(ModelAdmin):
    """Финансовые записи v1 — только просмотр: правятся только операциями кода."""

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


def _show(value) -> str:
    if value is None:
        return "—"
    return json.dumps(value, ensure_ascii=False)


class LoyaltySettingForm(forms.ModelForm):
    comment = forms.CharField(
        label="Комментарий к изменению", required=False, max_length=300,
        help_text="Попадёт в историю вместе со старым и новым значением.")

    class Meta:
        model = LoyaltySetting
        fields = ("value",)

    def clean_value(self):
        value = self.cleaned_data.get("value")
        if value is None:
            return None  # «как в ТЗ»
        try:
            return loyalty_config.validate(self.instance.key, value)
        except loyalty_config.ConfigError as e:
            raise forms.ValidationError(str(e)) from e


@admin.register(LoyaltySetting)
class LoyaltySettingAdmin(ModelAdmin):
    """Настройки программы: каждое изменение — в историю (кто, когда, было → стало)."""

    form = LoyaltySettingForm
    list_display = ("key", "title", "effective", "is_default", "updated_at", "updated_by")
    search_fields = ("key",)
    ordering = ("key",)
    readonly_fields = ("key", "title", "help_text", "who", "default_value", "effective",
                       "history")
    fieldsets = (
        (None, {"fields": ("key", "title", "help_text", "who", "default_value", "effective")}),
        ("Изменить", {"fields": ("value", "comment")}),
        ("История", {"fields": ("history",)}),
    )

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        loyalty_config.ensure_rows()
        return super().changelist_view(request, extra_context)

    def _spec(self, obj):
        return loyalty_config.SPECS.get(obj.key)

    @admin.display(description="Параметр (описание)")
    def title(self, obj):
        spec = self._spec(obj)
        return spec.title if spec else "— (неизвестный ключ)"

    @admin.display(description="Пояснение")
    def help_text(self, obj):
        spec = self._spec(obj)
        return spec.help if spec else ""

    @admin.display(description="Кто меняет")
    def who(self, obj):
        spec = self._spec(obj)
        return spec.who if spec else ""

    @admin.display(description="Значение по ТЗ v1")
    def default_value(self, obj):
        spec = self._spec(obj)
        return _show(spec.default) if spec else "—"

    @admin.display(description="Действует")
    def effective(self, obj):
        return _show(loyalty_config.get(obj.key)) if self._spec(obj) else "—"

    @admin.display(description="По ТЗ", boolean=True)
    def is_default(self, obj):
        return obj.value is None

    @admin.display(description="История изменений")
    def history(self, obj):
        rows = LoyaltySettingChange.objects.filter(key=obj.key)[:50]
        if not rows:
            return "Не менялось."
        return format_html("<ul>{}</ul>", format_html_join(
            "", "<li>{} · {}: {} → {}{}</li>",
            ((r.changed_at.strftime("%d.%m.%Y %H:%M"), r.changed_by or "—",
              _show(r.old_value), _show(r.new_value),
              f" ({r.comment})" if r.comment else "") for r in rows)))

    def save_model(self, request, obj, form, change):
        old = LoyaltySetting.objects.filter(pk=obj.pk).values_list("value", flat=True).first()
        obj.updated_by = request.user.get_username()[:150]
        super().save_model(request, obj, form, change)
        if old != obj.value:
            LoyaltySettingChange.objects.create(
                key=obj.key, old_value=old, new_value=obj.value,
                changed_by=obj.updated_by, comment=form.cleaned_data.get("comment") or "")
        loyalty_config.invalidate()


@admin.register(LoyaltySettingChange)
class LoyaltySettingChangeAdmin(_ReadOnlyAdmin):
    list_display = ("changed_at", "key", "old_value", "new_value", "changed_by", "comment")
    list_filter = ("key",)
    search_fields = ("key", "changed_by", "comment")
    date_hierarchy = "changed_at"


@admin.register(LoyaltyEvent)
class LoyaltyEventAdmin(_ReadOnlyAdmin):
    """Журнал loyalty_events — только добавление: ни правки, ни удаления."""

    list_display = ("created_at", "type", "amount", "balance_after", "status_points_after",
                    "level_after", "source_ref", "user_pseudonym", "rule_version")
    list_filter = ("type",)
    search_fields = ("user_pseudonym", "source_ref")
    date_hierarchy = "created_at"
    actions = None


@admin.register(LoyaltyLot)
class LoyaltyLotAdmin(UserRefMixin, _ReadOnlyAdmin):
    list_display = ("user_ref", "amount", "remaining", "state", "source", "source_ref",
                    "accrued_at", "available_at", "expires_at")
    list_filter = ("state", "source")
    search_fields = ("user_id", "source_ref")
    date_hierarchy = "accrued_at"


@admin.register(LoyaltyStatus)
class LoyaltyStatusAdmin(UserRefMixin, _ReadOnlyAdmin):
    list_display = ("user_ref", "level_title", "level_until", "level_since", "migrated_at",
                    "legacy_balance")
    list_filter = ("level",)
    search_fields = ("user_id",)

    @admin.display(description="Уровень")
    def level_title(self, obj):
        return loyalty_config.LEVEL_TITLES[obj.level]


@admin.register(LoyaltyRedemption)
class LoyaltyRedemptionAdmin(UserRefMixin, _ReadOnlyAdmin):
    list_display = ("user_ref", "order_id", "amount", "returned", "state", "eligible_kop",
                    "ceiling", "created_at")
    list_filter = ("state",)
    search_fields = ("user_id", "order_id")
