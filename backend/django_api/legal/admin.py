from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.db.models import Count, IntegerField, OuterRef, Subquery
from django.db.models.functions import Coalesce
from django.template.response import TemplateResponse
from django.utils import timezone
from django.utils.html import format_html
from unfold.admin import ModelAdmin

from common.adminutils import UserRefMixin

from .models import ConsentClient, LegalDocument, UserConsent

SOURCES = {"kvartal": "Квартал", "mata_store": "Store", "site": "Сайт"}


@admin.register(LegalDocument)
class LegalDocumentAdmin(ModelAdmin):
    list_display = (
        "doc_type", "version", "title", "is_required", "published_at", "created_at",
    )
    list_display_links = ("doc_type", "title")  # тип/заголовок кликабельны
    list_filter = ("doc_type", "is_required")
    search_fields = ("title", "body", "version")
    date_hierarchy = "created_at"
    actions = ["publish", "unpublish"]

    @admin.action(description="Опубликовать выбранные")
    def publish(self, request, queryset):
        queryset.filter(published_at__isnull=True).update(published_at=timezone.now())

    @admin.action(description="Снять с публикации (в черновик)")
    def unpublish(self, request, queryset):
        queryset.update(published_at=None)


@admin.register(UserConsent)
class UserConsentAdmin(UserRefMixin, ModelAdmin):
    list_display = ("id", "user_ref", "document", "source", "accepted_at", "revoked_at")
    list_filter = ("source", "document__doc_type")
    search_fields = ("user_id",)
    date_hierarchy = "accepted_at"
    ordering = ("-accepted_at",)

    # Аудит согласий (152-ФЗ): запись — доказательство согласия. Не правим и не
    # удаляем вручную, иначе теряется доказательная сила. Только просмотр.
    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


def _required_ids():
    """Текущие версии обязательных документов — их и должен принять каждый клиент."""
    return [d.pk for d in LegalDocument.current() if d.is_required]


def _count(qs, field):
    """Подзапрос «сколько» по клиенту — чтобы считать и фильтровать в SQL, а не в цикле."""
    grouped = qs.order_by().values("user_id").annotate(n=Count(field, distinct=True)).values("n")[:1]
    return Coalesce(Subquery(grouped, output_field=IntegerField()), 0)


class RequiredConsentsFilter(admin.SimpleListFilter):
    title = "Обязательные согласия"
    parameter_name = "required"

    def lookups(self, request, model_admin):
        return (("all", "Все даны"), ("missing", "Не все даны"))

    def queryset(self, request, queryset):
        total = len(_required_ids())
        if self.value() == "all":
            return queryset.filter(required_given__gte=total)
        if self.value() == "missing":
            return queryset.filter(required_given__lt=total)
        return queryset


@admin.register(ConsentClient)
class ConsentClientAdmin(ModelAdmin):
    """«Согласия»: клиент в списке один раз, его согласия — на его странице.

    Построчный журнал (`UserConsent`) остаётся доказательной базой по 152-ФЗ; здесь
    тот же журнал, сгруппированный по людям, — чтобы искать клиента и видеть, каких
    обязательных согласий у него не хватает.
    """

    list_display = ("client", "phone", "consents_total", "required_status", "last_consent")
    list_display_links = ("client",)
    search_fields = ("name", "phone", "email", "id")
    list_filter = (RequiredConsentsFilter,)
    list_per_page = 50

    def get_queryset(self, request):
        active = UserConsent.objects.filter(user_id=OuterRef("id"), revoked_at__isnull=True)
        latest = (UserConsent.objects.filter(user_id=OuterRef("id"))
                  .order_by("-accepted_at").values("accepted_at")[:1])
        return (
            super().get_queryset(request)
            .filter(id__in=UserConsent.objects.values("user_id"))
            .annotate(
                consents_count=_count(active, "id"),
                required_given=_count(active.filter(document_id__in=_required_ids()), "document_id"),
                last_consent_at=Subquery(latest),
            )
            # Сортировку ставим здесь, после расчёта: ModelAdmin.get_ordering применяется
            # раньше аннотаций и о `last_consent_at` ещё не знает.
            .order_by("-last_consent_at", "name")
        )

    @admin.display(description="Клиент", ordering="name")
    def client(self, obj):
        return obj.name or obj.phone or obj.email or obj.id

    @admin.display(description="Согласий", ordering="consents_count")
    def consents_total(self, obj):
        return obj.consents_count

    @admin.display(description="Обязательные", ordering="required_given")
    def required_status(self, obj):
        total = len(_required_ids())
        missing = total - obj.required_given
        if missing <= 0:
            return format_html('<span style="color:#16a34a;font-weight:600">Все {}</span>', total)
        return format_html('<span style="color:#dc2626;font-weight:600">Нет {} из {}</span>',
                           missing, total)

    @admin.display(description="Последнее согласие", ordering="last_consent_at")
    def last_consent(self, obj):
        if not obj.last_consent_at:
            return "—"
        return timezone.localtime(obj.last_consent_at).strftime("%d.%m.%Y %H:%M")

    # Только просмотр: согласие — доказательство, руками его не правят и не удаляют.
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def change_view(self, request, object_id, form_url="", extra_context=None):
        client = self.get_object(request, object_id)
        if client is None:
            return self._get_obj_does_not_exist_redirect(request, self.opts, object_id)
        if not self.has_view_permission(request, client):
            raise PermissionDenied

        current = {d.doc_type: d for d in LegalDocument.current()}
        consents = list(UserConsent.objects.filter(user_id=client.id)
                        .select_related("document").order_by("-accepted_at"))
        rows = []
        for c in consents:
            doc = c.document
            now_doc = current.get(doc.doc_type)
            rows.append({
                "title": doc.get_doc_type_display(),
                "version": doc.version,
                "outdated": now_doc is not None and now_doc.pk != doc.pk,
                "required": bool(now_doc and now_doc.is_required),
                "accepted_at": c.accepted_at,
                "source": SOURCES.get(c.source, c.source or "—"),
                "revoked_at": c.revoked_at,
            })

        accepted_now = {c.document_id for c in consents if c.revoked_at is None}
        accepted_types = {c.document.doc_type for c in consents if c.revoked_at is None}
        missing_required, missing_optional = [], []
        for doc in sorted(current.values(), key=lambda d: d.get_doc_type_display()):
            if doc.pk in accepted_now:
                continue
            item = {"title": doc.get_doc_type_display(), "version": doc.version,
                    "old_version": doc.doc_type in accepted_types}
            (missing_required if doc.is_required else missing_optional).append(item)

        context = {
            **self.admin_site.each_context(request),
            "title": f"Согласия: {self.client(client)}",
            "opts": self.opts,
            "client": client,
            "rows": rows,
            "missing_required": missing_required,
            "missing_optional": missing_optional,
            "required_total": sum(1 for d in current.values() if d.is_required),
            "journal_url": f"../../../userconsent/?user_id={client.id}",
            **(extra_context or {}),
        }
        return TemplateResponse(request, "admin/legal/consent_client.html", context)

