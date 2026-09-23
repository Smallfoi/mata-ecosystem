from django.contrib import admin, messages
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.html import format_html
from unfold.admin import ModelAdmin, TabularInline

from common.adminutils import ExportCsvMixin, UserRefMixin
from staff.models import StaffAudit

from .models import Order, OrderReturn
from .returns import RETURNABLE, ReturnError, make_return, return_plan


class OrderReturnInline(TabularInline):
    """История возвратов на карточке заказа. Оформляется на отдельной странице."""

    model = OrderReturn
    extra = 0
    can_delete = False
    fields = ("created_at", "amount_rub", "points_returned", "points_revoked",
              "status", "refund_id", "created_by", "error")
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False

    @admin.display(description="Сумма, ₽")
    def amount_rub(self, obj):
        return f"{obj.amount_kop / 100:.2f}"


@admin.register(Order)
class OrderAdmin(ExportCsvMixin, UserRefMixin, ModelAdmin):
    list_display = (
        "order_id",
        "user_ref",
        "total",
        "status",
        "payment_status",
        "points_redeemed",
        "created_at",
        # Обмен с 1С: сразу видно, ушёл ли заказ на склад и что там с ним.
        "onec_state",
        "courier_note",
    )
    list_display_links = ("order_id",)
    list_editable = ("status",)
    list_filter = ("status", "payment_status", "onec_status")
    search_fields = ("order_id", "user_id")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    readonly_fields = ("return_link", "payload", "created_at", "onec_taken_at",
                       "onec_number", "onec_status", "onec_status_at")
    inlines = (OrderReturnInline,)

    @admin.display(description="Возврат")
    def return_link(self, obj):
        if not obj or not obj.pk:
            return "—"
        return format_html('<a href="{}">Оформить возврат — целиком или частями</a>',
                           reverse("order_return", args=[obj.pk]))

    @admin.display(description="1С")
    def onec_state(self, obj):
        """Одна колонка вместо четырёх: главное — забран заказ или ещё в очереди."""
        if not obj.onec_taken_at:
            return "в очереди"
        label = obj.get_onec_status_display() if obj.onec_status else "забран"
        return f"{label}{f' · {obj.onec_number}' if obj.onec_number else ''}"
    csv_filename = "orders"
    export_fields = ("order_id", "user_id", "total", "status", "payment_status",
                     "points_redeemed", "created_at")
    actions = ("hand_to_courier", "mark_paid", "mark_shipped", "mark_delivered",
               "mark_cancelled", "refund_payment", "export_as_csv")

    @admin.action(description="Вернуть деньги покупателю целиком (ЮKassa)")
    def refund_payment(self, request, queryset):
        """Полный возврат: всё, что ещё не вернули, вместе с доставкой (D-73).

        Идёт через ту же логику, что и возврат частями: деньги по чеку, списанные
        баллы — назад, начисленные — снять. Частями — на странице заказа.
        Заказы без платежа ЮKassa (разработка, неоплаченные) пропускаем.
        """
        done, skipped, failed = 0, 0, []
        for order in queryset:
            if order.payment_status not in RETURNABLE or not order.payment_id:
                skipped += 1
                continue
            try:
                left = [row["index"] for row in return_plan(order)
                        if row["subject"] == "commodity" and not row["returned"]]
                make_return(order.pk, left, by=request.user.get_username())
            except ReturnError as e:
                failed.append(f"{order.order_id}: {e}")
                continue
            done += 1
        if done:
            self.message_user(request, f"Возвращено заказов: {done}", messages.SUCCESS)
        if skipped:
            self.message_user(
                request, f"Пропущено (нет оплаты): {skipped}", messages.WARNING
            )
        for err in failed:
            self.message_user(request, f"Ошибка возврата — {err}", messages.ERROR)

    def _set_status(self, request, queryset, status, label):
        """Смена статуса по одной записи — намеренно.

        `queryset.update()` идёт мимо сигналов Django, а на них висит уведомление
        покупателю (orders/signals.py). Из админки статус менялся молча: в базе
        «Отправлен», а человек об этом не знал.
        """
        n = 0
        for order in queryset:
            if order.status == status:
                continue
            order.status = status
            order.save(update_fields=["status"])
            n += 1
        self.message_user(request, f"Отмечено «{label}»: {n}. Покупателям ушло уведомление.")

    @admin.action(description="Отметить: Оплачен")
    def mark_paid(self, request, queryset):
        self._set_status(request, queryset, "paid", "Оплачен")

    @admin.action(description="Отметить: Отправлен")
    def mark_shipped(self, request, queryset):
        self._set_status(request, queryset, "shipped", "Отправлен")

    @admin.action(description="Отметить: Доставлен")
    def mark_delivered(self, request, queryset):
        self._set_status(request, queryset, "delivered", "Доставлен")

    @admin.action(description="Отметить: Отменён")
    def mark_cancelled(self, request, queryset):
        self._set_status(request, queryset, "cancelled", "Отменён")

    @admin.action(description="🚚 Передан курьеру — написать покупателю")
    def hand_to_courier(self, request, queryset):
        """Доставка по городу своими силами (D-92): курьера заказывают вручную
        (Яндекс, inDrive) или везёт свой. Здесь одним действием: записали, кто
        везёт и когда, — покупатель получил уведомление, заказ стал «Отправлен».
        """
        if "apply" in request.POST:
            note = (request.POST.get("note") or "").strip()
            if not note:
                self.message_user(request, "Напишите, кто везёт и когда — "
                                  "это и увидит покупатель.", level=messages.ERROR)
                return None
            n = 0
            for order in queryset:
                order.courier_note = note[:200]
                order.status = "shipped"
                order.save(update_fields=["courier_note", "status"])
                n += 1
            StaffAudit.write(request, f"передано курьеру заказов: {n} ({note[:80]})")
            self.message_user(request, f"Передано курьеру: {n}. Покупатели уведомлены.",
                              messages.SUCCESS)
            return None

        return TemplateResponse(request, "admin/orders/hand_to_courier.html", {
            **self.admin_site.each_context(request),
            "title": "Передать курьеру",
            "opts": self.model._meta,
            "count": queryset.count(),
            "orders": list(queryset.values_list("order_id", flat=True)[:10]),
            "action_checkbox_name": ACTION_CHECKBOX_NAME,
            "selected": request.POST.getlist(ACTION_CHECKBOX_NAME),
            "select_across": request.POST.get("select_across", "0"),
        })
