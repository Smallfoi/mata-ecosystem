from django.contrib import admin, messages
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.contrib.auth.admin import GroupAdmin as DjangoGroupAdmin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.models import Group, User
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.html import format_html
from unfold.admin import ModelAdmin

from common.adminutils import ExportCsvMixin

from .models import Account


@admin.register(Account)
class AccountAdmin(ExportCsvMixin, ModelAdmin):
    # ID — служебный: в списке не показываем (открывается по имени, ищется поиском).
    list_display = ("who", "phone", "email", "city", "provider",
                    "is_blocked", "needs_review", "test_payment", "created_at")
    list_display_links = ("who",)
    list_filter = ("provider", "city", "is_blocked", "needs_review", "test_payment")
    search_fields = ("id", "name", "phone", "email")
    ordering = ("-created_at",)
    date_hierarchy = "created_at"
    readonly_fields = ("id", "created_at")
    actions = ("send_notification", "block_accounts", "unblock_accounts",
               "clear_review", "export_as_csv")
    csv_filename = "accounts"
    export_fields = ("id", "name", "phone", "email", "city", "provider",
                     "is_blocked", "needs_review", "created_at")
    # Карточка пользователя по разделам (хэш пароля не показываем).
    fieldsets = (
        ("Профиль", {
            "fields": ("id", "name", "phone", "email", "city", "provider",
                       "avatar_path", "addresses", "created_at"),
        }),
        ("Приватность", {
            "fields": ("profile_public", "route_public", "realtime_public"),
        }),
        ("Проверка заказов", {
            "fields": ("test_payment",),
            "description": "Тестовая оплата: этот человек «оплачивает» заказы без денег, "
            "чтобы пройти весь путь — заказ, выгрузка в 1С, статусы. Нужно для проверки "
            "обмена со стороны 1С. Такие заказы помечены «тест» и у нас, и в выгрузке; "
            "продажей они не считаются. Выключайте, когда проверка закончена.",
        }),
        ("Модерация и анти-чит", {
            "fields": ("is_blocked", "block_reason", "needs_review"),
            "description": "Блокировка отрезает вход (≤60с). «На проверке» — авто-метка "
            "при накоплении флагнутых забегов (S-04); снимается действием в списке.",
        }),
    )

    @admin.display(description="Клиент", ordering="name")
    def who(self, obj):
        """Имя, а если его нет — телефон или почта: пустая ссылка некликабельна."""
        return obj.name or obj.phone or obj.email or obj.id

    @admin.action(description="✉ Отправить уведомление выбранным")
    def send_notification(self, request, queryset):
        """Массовая рассылка: промежуточная форма (заголовок/текст) → уведомление каждому
        выбранному пользователю. Идёт в общую ленту уведомлений (+ пуш, если настроен)."""
        if "apply" in request.POST:
            title = (request.POST.get("title") or "").strip()
            body = (request.POST.get("body") or "").strip()
            if not title:
                self.message_user(request, "Заголовок обязателен — рассылка отменена.",
                                  level=messages.ERROR)
                return None
            from notifications.models import create_notification

            sent = 0
            for uid in queryset.values_list("id", flat=True):
                if create_notification(uid, title, body, type="system"):
                    sent += 1
            self.message_user(request, f"Отправлено уведомлений: {sent}",
                              level=messages.SUCCESS)
            return None
        # Первый вызов — показать форму (с сохранением выбранных получателей).
        return TemplateResponse(request, "admin/send_notification.html", {
            **self.admin_site.each_context(request),
            "title": "Массовая рассылка уведомления",
            "opts": self.model._meta,
            "count": queryset.count(),
            "selected": list(queryset.values_list("id", flat=True)),
            "action_checkbox_name": ACTION_CHECKBOX_NAME,
        })

    @admin.action(description="Заблокировать (бан входа)")
    def block_accounts(self, request, queryset):
        n = queryset.update(is_blocked=True)
        self.message_user(request, f"Заблокировано аккаунтов: {n}")

    @admin.action(description="Разблокировать")
    def unblock_accounts(self, request, queryset):
        n = queryset.update(is_blocked=False, block_reason="")
        self.message_user(request, f"Разблокировано аккаунтов: {n}")

    @admin.action(description="Снять отметку «на ревью» (S-04)")
    def clear_review(self, request, queryset):
        n = queryset.update(needs_review=False)
        self.message_user(request, f"Снята отметка ревью: {n}")


# Перерегистрируем стандартные User/Group под тему Unfold (иначе рендерятся дефолтно).
admin.site.unregister(User)
admin.site.unregister(Group)


@admin.register(User)
class UserAdmin(DjangoUserAdmin, ModelAdmin):
    # Даты входа/регистрации — только история; «Пароль» — кнопка безопасной смены.
    readonly_fields = ("last_login", "date_joined", "change_password_link",
                       "two_factor_link")

    @admin.display(description="Пароль")
    def change_password_link(self, obj=None):
        # Хэш не показываем — прямо в настройках аккаунта кнопка безопасной смены
        # (форма: текущий → новый → подтвердить, требует текущий пароль).
        if obj is None or not obj.pk:
            return "—"
        url = reverse("admin:password_change")
        return format_html(
            '<a href="{}" style="display:inline-flex;align-items:center;'
            'padding:7px 14px;border-radius:8px;background:#0A84FF;color:#fff;'
            'font-weight:600;text-decoration:none;">Сменить пароль</a>',
            url,
        )

    @admin.display(description="Второй фактор")
    def two_factor_link(self, obj=None):
        """Кнопка управления своим вторым фактором.

        Раньше отсюда можно было сменить почту и пароль, а второй фактор
        не показывался вообще: сменить телефон было негде, и человек не знал,
        подключён ли фактор и сколько запасных кодов у него осталось.
        """
        if obj is None or not obj.pk:
            return "—"
        url = reverse("account_security")
        return format_html(
            '<a href="{}" style="display:inline-flex;align-items:center;'
            'padding:7px 14px;border-radius:8px;background:#20252b;color:#fff;'
            'font-weight:600;text-decoration:none;">Настроить второй фактор</a>'
            '<div style="margin-top:6px;font-size:12px;color:#6f7278;">'
            'Смена устройства и запасные коды. Отключить нельзя — фактор '
            'обязателен для всех.</div>',
            url,
        )

    def get_fieldsets(self, request, obj=None):
        """Блок «Права доступа» убран у ВСЕХ записей (S-13).

        Раньше галочки «суперпользователь», «сотрудник», группы и права прятались
        только на своей карточке. Но именно они и были способом обойти всё
        остальное: поставил галочку — получил полный доступ мимо вкладки
        «Сотрудники». Теперь доступ сотрудников выдаётся только там, а владелец
        закреплён по идентификатору записи и в интерфейсе не переназначается.
        """
        fieldsets = super().get_fieldsets(request, obj)
        out = []
        for name, opts in fieldsets:
            fields = tuple(opts.get("fields", ()))
            if any(f in fields for f in ("is_superuser", "is_staff", "user_permissions", "groups")):
                continue  # блок прав целиком — не показываем и не принимаем
            if "date_joined" in fields:
                fields = tuple(f for f in fields if f != "date_joined")  # только последний вход
            if "password" in fields:
                # Хэш (алгоритм/соль) не показываем. На его месте — кнопка «Сменить пароль»
                # прямо в настройках аккаунта (не отдельным пунктом меню). Рядом —
                # кнопка второго фактора: пароль и фактор это одна тема «как я вхожу»,
                # и искать их в разных местах человек не должен (D-69).
                fields = tuple("change_password_link" if f == "password" else f
                               for f in fields)
                if obj is not None and "two_factor_link" not in fields:
                    i = fields.index("change_password_link")
                    fields = fields[:i + 1] + ("two_factor_link",) + fields[i + 1:]
            out.append((name, {**opts, "fields": fields}))
        return out

    def has_add_permission(self, request):
        """Заводить людей — во вкладке «Сотрудники»: там сразу приглашение и права.
        Здесь создание запрещено, чтобы не появлялись учётные записи в обход неё."""
        return False

    def has_delete_permission(self, request, obj=None):
        from staff.owner import is_owner

        # Владельца и себя удалять нельзя — иначе одним кликом можно остаться
        # снаружи навсегда.
        if obj is not None and (obj.pk == request.user.pk or is_owner(obj)):
            return False
        return super().has_delete_permission(request, obj)


@admin.register(Group)
class GroupAdmin(DjangoGroupAdmin, ModelAdmin):
    pass
