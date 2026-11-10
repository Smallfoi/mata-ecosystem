from django.contrib import admin, messages
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.html import format_html, format_html_join
from unfold.admin import ModelAdmin, TabularInline

from common.adminutils import ExportCsvMixin, UserRefMixin
from staff.models import StaffAudit

from .models import Order, OrderReturn, ReturnRequest, ShippingOption
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


class CancelRequestedFilter(admin.SimpleListFilter):
    title = "Просит отменить"
    parameter_name = "cancel_requested"

    def lookups(self, request, model_admin):
        return (("yes", "Да"),)

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.filter(cancel_requested_at__isnull=False)
        return queryset


@admin.register(Order)
class OrderAdmin(ExportCsvMixin, UserRefMixin, ModelAdmin):
    list_display = (
        "order_id",
        "user_ref",
        "total",
        "status",
        "payment_status",
        "test_mark",
        "points_redeemed",
        "created_at",
        # Обмен с 1С: сразу видно, ушёл ли заказ на склад и что там с ним.
        "onec_state",
        "cancel_mark",
        "courier_note",
    )
    list_display_links = ("order_id",)
    list_editable = ("status",)
    list_filter = ("status", "payment_status", "onec_status", "is_test", CancelRequestedFilter)
    search_fields = ("order_id", "client_ref", "user_id")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    # Номер выдаёт сервер (D-120) — руками его не меняют: на него ссылаются
    # платёж, баллы и 1С.
    readonly_fields = ("order_id", "client_ref", "return_link", "payload", "created_at", "onec_taken_at",
                       "onec_number", "onec_status", "onec_status_at")
    inlines = (OrderReturnInline,)

    @admin.display(description="Возврат")
    def return_link(self, obj):
        if not obj or not obj.pk:
            return "—"
        return format_html('<a href="{}">Оформить возврат — целиком или частями</a>',
                           reverse("order_return", args=[obj.pk]))

    @admin.display(description="Тест", boolean=False, ordering="is_test")
    def test_mark(self, obj):
        """Оплачен симуляцией (D-97): денег не было, продажей не считается."""
        if not obj.is_test:
            return ""
        return format_html('<span class="m-tag warn">тест</span>')

    @admin.display(description="Отмена")
    def cancel_mark(self, obj):
        """Покупатель просит отменить заказ, уже забранный 1С (orders/cancel.py)."""
        if not obj.cancel_requested_at:
            return ""
        return format_html('<span class="m-tag bad">просит отменить</span>')

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
               "mark_cancelled", "refund_payment", "confirm_cancel", "decline_cancel",
               "export_as_csv")

    def _cancel_run(self, request, queryset, fn, done):
        from .cancel import CancelError

        ok = 0
        for order in queryset:
            try:
                fn(order, request.user.get_username())
            except CancelError as e:
                self.message_user(request, f"{order.order_id}: {e.detail}", messages.ERROR)
            else:
                ok += 1
                StaffAudit.write(request, f"заказ {order.order_id}: {done}")
        if ok:
            self.message_user(request, f"{done}: {ok}", messages.SUCCESS)

    @admin.action(description="Подтвердить отмену (заказ не у курьера) и вернуть деньги",
                  permissions=["change"])
    def confirm_cancel(self, request, queryset):
        from .cancel import confirm_cancel

        self._cancel_run(request, queryset, confirm_cancel, "отмена подтверждена")

    @admin.action(description="Отклонить отмену: заказ уже передан курьеру",
                  permissions=["change"])
    def decline_cancel(self, request, queryset):
        from .cancel import decline_cancel

        self._cancel_run(request, queryset, decline_cancel, "отмена отклонена")

    @admin.action(description="Вернуть деньги покупателю целиком (ЮKassa)")
    def refund_payment(self, request, queryset):
        """Полный возврат: всё, что ещё не вернули, вместе с доставкой (D-73).

        Идёт через ту же логику, что и возврат частями: деньги по чеку, списанные
        баллы — назад, начисленные — снять. Частями — на странице заказа.
        Заказы без платежа ЮKassa (разработка, неоплаченные) пропускаем.
        """
        done, waiting, skipped, failed = 0, 0, 0, []
        for order in queryset:
            if order.payment_status not in RETURNABLE or not order.payment_id:
                skipped += 1
                continue
            try:
                left = [row["index"] for row in return_plan(order)
                        if row["subject"] == "commodity" and not row["returned"]]
                ret = make_return(order.pk, left, by=request.user.get_username())
            except ReturnError as e:
                failed.append(f"{order.order_id}: {e}")
                continue
            if ret.status == "done":
                done += 1
            else:
                waiting += 1
        if done:
            self.message_user(request, f"Возвращено заказов: {done}", messages.SUCCESS)
        if waiting:
            # Деньги ещё не подтверждены — не говорим «возвращено» (аудит B04).
            self.message_user(
                request,
                f"Возврат отправлен, ждём подтверждения ЮKassa: {waiting}. Баллы и "
                "статус заказа изменятся после подтверждения.",
                messages.WARNING,
            )
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


@admin.register(ShippingOption)
class ShippingOptionAdmin(ModelAdmin):
    """Способы получения заказа (D-110): цену доставки считает сервер по этой таблице."""

    list_display = ("name", "code", "kind", "zone", "price", "free_from", "is_active",
                    "sort_order")
    list_editable = ("price", "free_from", "is_active", "sort_order")
    list_filter = ("kind", "is_active")

    def has_delete_permission(self, request, obj=None):
        # Удалённый код ломает старые сборки и разбор прошлых заказов — выключайте.
        return False


@admin.register(ReturnRequest)
class ReturnRequestAdmin(UserRefMixin, ModelAdmin):
    """Заявки покупателей на возврат (D-112, D-122).

    Каждый день: «Открыть заявку» → когда вещи пришли — «Товар получен» → осмотр →
    решение по каждой вещи на странице заявки. Заявлен брак — отказать можно только
    по итогам проверки качества.
    """

    list_display = ("number_label", "open_link", "order_link", "user_ref", "status",
                    "method", "track_number", "defect_claimed", "bring_until", "created_at")
    list_filter = ("status", "method", "defect_claimed", "goods_back_done")
    search_fields = ("order__order_id", "user_id", "track_number")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    actions = ("act_received", "act_goods_back_done")
    fields = ("open_link", "order_link", "user_id", "status", "method", "items_view",
              "bring_until", "track_number", "sent_at", "defect_claimed", "defect_confirmed",
              "customer_shipping_kop", "shipping_paid", "decision_note", "goods_back",
              "goods_back_done", "order_return", "created_at", "received_at", "decided_at",
              "decided_by")
    readonly_fields = ("open_link", "order_link", "user_id", "status", "method", "items_view",
                       "bring_until", "track_number", "sent_at", "defect_claimed",
                       "decision_note", "goods_back", "goods_back_done", "order_return",
                       "created_at", "received_at", "decided_at", "decided_by")

    def has_add_permission(self, request):
        return False  # заявку оформляет покупатель

    def has_delete_permission(self, request, obj=None):
        return False  # история возвратов — документ

    @admin.display(description="Заявка", ordering="pk")
    def number_label(self, obj):
        return obj.number

    @admin.display(description="Решение")
    def open_link(self, obj):
        if not obj or not obj.pk:
            return "—"
        return format_html('<a class="m-btn" href="{}">Открыть заявку</a>',
                           reverse("return_request_page", args=[obj.pk]))

    @admin.display(description="Заказ")
    def order_link(self, obj):
        return format_html('<a href="{}">{}</a>',
                           reverse("admin:orders_order_change", args=[obj.order_id]),
                           obj.order.order_id)

    @admin.display(description="Вещи и причины")
    def items_view(self, obj):
        from .return_requests import REASONS, REJECT_REASONS

        try:
            names = {row["index"]: row["name"] for row in return_plan(obj.order)}
        except ReturnError:
            names = {}

        def verdict(line):
            if line.get("decision") == "accept":
                return " → принята"
            if line.get("decision") == "reject":
                return " → отказ: " + "; ".join(REJECT_REASONS.get(r, r)
                                                 for r in line.get("rejectReasons") or [])
            return ""

        rows = format_html_join(
            "", "<li><b>{}</b> — {}{}{}</li>",
            ((names.get(line["index"], f"позиция {line['index']}"),
              REASONS.get(line["reason"], line["reason"]),
              f": {line['comment']}" if line.get("comment") else "",
              verdict(line))
             for line in obj.lines))
        return format_html("<ul>{}</ul>", rows)

    def _run(self, request, queryset, fn, done):
        from .return_requests import RequestError

        ok = 0
        for req in queryset:
            try:
                fn(req)
            except RequestError as e:
                self.message_user(request, f"{req.number}: {e.detail}", messages.ERROR)
            else:
                ok += 1
                StaffAudit.write(request, f"заявка на возврат {req.number}: {done}")
        if ok:
            self.message_user(request, f"{done}: {ok}", messages.SUCCESS)

    @admin.action(description="Товар получен — на осмотр", permissions=["change"])
    def act_received(self, request, queryset):
        from .return_requests import mark_received

        self._run(request, queryset, lambda r: mark_received(r, request.user.get_username()),
                  "товар получен")

    @admin.action(description="Вещи после отказа отданы / отправлены", permissions=["change"])
    def act_goods_back_done(self, request, queryset):
        from .return_requests import mark_goods_back_done

        self._run(request, queryset,
                  lambda r: mark_goods_back_done(r, request.user.get_username()),
                  "вещи отданы покупателю")
