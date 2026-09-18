"""Утилиты для админки: читаемая колонка пользователя вместо сырого user_id.

user_id в моделях — обычный CharField (не ForeignKey, контракт с FastAPI), поэтому
Django не покажет имя автоматически. Миксин подтягивает Account и выводит
«Имя · телефон». Запрос на строку — для админ-списка (≤100 строк) это норма."""
import contextvars
import csv

from django.contrib import admin
from django.contrib.admin.utils import label_for_field
from django.http import HttpResponse, HttpResponseRedirect
from django.urls import path, reverse
from django.utils.http import url_has_allowed_host_and_scheme


class ExportCsvMixin:
    """Действие «Экспорт в CSV» для выбранных строк. Поля — из `export_fields`
    (если не задано — все поля модели). Файл с BOM, чтобы кириллица открывалась
    в Excel корректно."""
    export_fields = None
    csv_filename = "export"

    @admin.action(description="Экспорт выбранных в CSV")
    def export_as_csv(self, request, queryset):
        fields = self.export_fields or [f.name for f in self.model._meta.fields]
        resp = HttpResponse(content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = f'attachment; filename="{self.csv_filename}.csv"'
        resp.write(chr(0xFEFF))  # BOM, чтобы кириллица открывалась в Excel
        writer = csv.writer(resp)
        writer.writerow(fields)
        for obj in queryset:
            writer.writerow([getattr(obj, f, "") for f in fields])
        return resp


class UserRefMixin:
    """Добавляет метод user_ref (колонка «Пользователь»). Поле с id берётся из
    user_id_field (по умолчанию 'user_id'; для клуба — 'owner_id')."""
    user_id_field = "user_id"

    @admin.display(description="Пользователь")
    def user_ref(self, obj):
        from accounts.models import Account

        uid = getattr(obj, self.user_id_field, "") or ""
        if not uid:
            return "—"
        acc = Account.objects.filter(id=uid).only("name", "phone", "email").first()
        if not acc:
            return f"{uid} (удалён)"
        name = acc.name or acc.phone or acc.email or uid
        extra = acc.phone or acc.email or ""
        return f"{name} · {extra}" if extra and extra != name else name


# Скрытые столбцы текущего запроса. Переменная контекста, а не поле класса:
# ModelAdmin в Django один на всё приложение и обслуживает запросы параллельно —
# запись в self утекла бы к соседнему сотруднику.
_hidden_now = contextvars.ContextVar("hidden_columns", default=())


class ColumnPickerMixin:
    """Шестерёнка «Столбцы» над списком: каждый сам выбирает, что видеть.

    Колонок в больших списках много (в «Товарах» — всё, что ведёт 1С, плюс наши
    поля витрины), и нужны они не все сразу. Выбор личный и запоминается между
    заходами (`core.AdminColumns`).

    Почему заодно фильтруем `list_editable`: часть колонок правится прямо в
    списке. Если скрыть такую колонку, оставив её в `list_editable`, Django
    соберёт форму с полем, которого на странице нет, и «Сохранить» затрёт
    значение пустотой. Поэтому редактируемые колонки объявляются в
    `columns_editable`, а `list_editable` собирается из них по видимым.
    """

    columns_locked = ()          # эти скрыть нельзя (колонка-ссылка на карточку)
    columns_hidden_default = ()  # скрыто у того, кто ещё ничего не выбирал
    columns_editable = ()        # правится прямо в списке (бывший list_editable)
    # Панель ставим штатным крючком темы — ДО формы списка. Внутри формы её быть не
    # может: форма в форме запрещена в HTML, браузер выбрасывает внутреннюю и кнопка
    # «Применить» уходит не туда (тесты этого не ловят — они шлют запрос напрямую).
    list_before_template = "admin/column_picker.html"

    @property
    def list_editable(self):
        hidden = _hidden_now.get()
        return tuple(f for f in self.columns_editable if f not in hidden)

    # ── чтение и запись настройки ──────────────────────────────────────────
    def _columns_key(self) -> str:
        return f"{self.opts.app_label}.{self.opts.model_name}"

    def hidden_columns(self, request) -> tuple:
        """Что скрыто у этого сотрудника. Заблокированные колонки не скрываем никогда."""
        from core.models import AdminColumns

        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return tuple(self.columns_hidden_default)
        row = AdminColumns.objects.filter(user=user, model_label=self._columns_key()).first()
        source = self.columns_hidden_default if row is None else (row.hidden or [])
        return tuple(c for c in source if c not in self.columns_locked)

    def all_columns(self) -> tuple:
        """Полный набор колонок списка — то, что перечислено в list_display класса."""
        return tuple(self.list_display)

    def column_choices(self, request, hidden) -> list:
        out = []
        for name in self.all_columns():
            out.append({
                "name": name,
                "label": label_for_field(name, self.model, self, return_attr=False),
                "visible": name not in hidden,
                "locked": name in self.columns_locked,
            })
        return out

    # ── страница списка ────────────────────────────────────────────────────
    def get_list_display(self, request):
        hidden = self.hidden_columns(request)
        return tuple(c for c in self.all_columns() if c not in hidden)

    def changelist_view(self, request, extra_context=None):
        hidden = self.hidden_columns(request)
        token = _hidden_now.set(hidden)
        try:
            info = self.opts.app_label, self.opts.model_name
            return super().changelist_view(request, {
                **(extra_context or {}),
                "column_choices": self.column_choices(request, hidden),
                "column_form_url": reverse("admin:%s_%s_columns" % info),
                "columns_hidden_count": len(hidden),
            })
        finally:
            _hidden_now.reset(token)

    # ── сохранение выбора ──────────────────────────────────────────────────
    def get_urls(self):
        info = self.opts.app_label, self.opts.model_name
        return [
            path("columns/", self.admin_site.admin_view(self.columns_view),
                 name="%s_%s_columns" % info),
        ] + super().get_urls()

    def columns_view(self, request):
        """Сохранить личный выбор столбцов и вернуть человека туда, где он был."""
        from core.models import AdminColumns

        back = request.POST.get("next") or ""
        if not url_has_allowed_host_and_scheme(back, allowed_hosts=None):
            info = self.opts.app_label, self.opts.model_name
            back = reverse("admin:%s_%s_changelist" % info)

        if request.method != "POST":
            return HttpResponseRedirect(back)

        key = self._columns_key()
        if request.POST.get("reset"):
            AdminColumns.objects.filter(user=request.user, model_label=key).delete()
            return HttpResponseRedirect(back)

        shown = set(request.POST.getlist("show"))
        hidden = [c for c in self.all_columns()
                  if c not in shown and c not in self.columns_locked]
        AdminColumns.objects.update_or_create(
            user=request.user, model_label=key, defaults={"hidden": hidden},
        )
        return HttpResponseRedirect(back)
