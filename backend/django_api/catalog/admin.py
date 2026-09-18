from django.contrib import admin, messages
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.db.models import Avg, Count
from django.template.response import TemplateResponse
from django.utils.html import format_html, format_html_join
from unfold.admin import ModelAdmin

from common.adminutils import UserRefMixin
from staff.models import StaffAudit

from .models import Banner, Category, Product, Review


@admin.action(description="Опубликовать (на витрину)")
def make_published(modeladmin, request, queryset):
    n = queryset.update(is_published=True)
    modeladmin.message_user(request, f"Опубликовано: {n}")


@admin.action(description="Снять с публикации (в черновик)")
def make_draft(modeladmin, request, queryset):
    n = queryset.update(is_published=False)
    modeladmin.message_user(request, f"В черновик: {n}")


DELETE_CHUNK = 500  # пачка удаления: один SQL на 500 карточек


@admin.action(description="Удалить выбранные товары", permissions=["delete"])
def delete_products(modeladmin, request, queryset):
    """Удаление любого числа товаров.

    У штатного «Удалить выбранные» страница подтверждения кладёт скрытое поле на
    КАЖДЫЙ товар: на 3309 карточках запрос упирается в `DATA_UPLOAD_MAX_NUMBER_FIELDS`
    (1000 полей) и возвращается 400 — удалять получалось только по сотне, страницами.
    Здесь подтверждение не зависит от числа товаров: пересылаем ровно то, что пришло из
    списка (строки текущей страницы и флаг «выбрано всё»), а удаляем пачками.
    """
    if request.POST.get("confirm") == "yes":
        ids = list(queryset.values_list("pk", flat=True))
        deleted = 0
        for start in range(0, len(ids), DELETE_CHUNK):
            deleted += Product.objects.filter(pk__in=ids[start:start + DELETE_CHUNK]).delete()[0]
        StaffAudit.write(request, f"удалено товаров: {deleted}")
        modeladmin.message_user(request, f"Удалено товаров: {deleted}", messages.SUCCESS)
        return None

    return TemplateResponse(request, "admin/catalog/delete_products.html", {
        **modeladmin.admin_site.each_context(request),
        "title": "Удалить товары",
        "opts": modeladmin.model._meta,
        "count": queryset.count(),
        "sample": list(queryset.values_list("name", flat=True)[:8]),
        "action_checkbox_name": ACTION_CHECKBOX_NAME,
        "selected": request.POST.getlist(ACTION_CHECKBOX_NAME),
        "select_across": request.POST.get("select_across", "0"),
    })


@admin.register(Category)
class CategoryAdmin(ModelAdmin):
    list_display = ("preview", "id", "name", "emoji", "sort")
    list_display_links = ("id", "name")  # имя кликабельно → открыть/редактировать
    list_editable = ("sort",)
    search_fields = ("id", "name")
    ordering = ("sort",)
    readonly_fields = ("preview_large",)
    fieldsets = (
        (None, {"fields": ("id", "name", "emoji", "image", "preview_large", "image_url", "sort")}),
        ("Типовая посылка", {
            "fields": ("default_weight_g", "default_length_cm", "default_width_cm",
                       "default_height_cm"),
            "description": "Для расчёта доставки, пока у товаров категории нет своего веса и "
            "габаритов. Пусто — возьмём значения родительской категории, а если и там "
            "пусто — коробку 35×25×15 см, 1 кг.",
        }),
    )

    @admin.display(description="Фото")
    def preview(self, obj):
        url = obj.network_image_url()
        if url:
            return format_html(
                '<img src="{}" style="height:34px;width:34px;object-fit:cover;'
                'border-radius:6px"/>', url,
            )
        return "—"

    @admin.display(description="Текущее фото")
    def preview_large(self, obj):
        url = obj.network_image_url()
        if url:
            return format_html(
                '<img src="{}" style="max-height:120px;border-radius:10px"/>', url
            )
        return "Нет фото"


# Порядок размеров одежды: по алфавиту вышло бы «L, M, S, XL».
_SIZE_ORDER = {"XXS": 0, "XS": 1, "S": 2, "M": 3, "L": 4, "XL": 5, "XXL": 6, "XXXL": 7, "3XL": 7}


def _size_key(item):
    size = str(item[0]).strip()
    if size.upper() in _SIZE_ORDER:
        return (0, _SIZE_ORDER[size.upper()], size)
    try:
        return (1, float(size.replace(",", ".")), size)
    except ValueError:
        return (2, 0, size)


@admin.register(Product)
class ProductAdmin(ModelAdmin):
    # ID в списке — служебный шум: товар открывается по названию, найти по ID можно поиском.
    list_display = (
        "preview",
        "name",
        "brand",
        "category_name",
        "price",
        "old_price",
        "stock",
        "in_stock",
        "is_published",
        "is_featured",
        "is_new",
        "sort_site",
        "sort_app",
    )
    list_display_links = ("name",)
    list_editable = (
        "price",
        "old_price",
        "in_stock",
        "is_published",
        "is_featured",
        "is_new",
        "sort_site",
        "sort_app",
    )
    list_filter = ("category_id", "brand", "in_stock", "is_published", "is_featured", "is_new")
    search_fields = ("id", "name", "brand", "description")
    ordering = ("sort",)
    actions = [make_published, make_draft, delete_products]
    fieldsets = (
        ("Основное", {
            "fields": ("id", "name", "brand", "category_id", "description"),
        }),
        ("Фото", {
            "fields": ("image", "preview_large", "image_urls"),
            "description": "Загрузите фото — оно используется в каталоге и трекере "
            "кроссовок Квартала. image_urls — старые бандл-ассеты (можно не трогать).",
        }),
        ("Цена и наличие", {
            "fields": ("price", "old_price", "in_stock", "sizes", "colors"),
        }),
        ("Доставка: вес и габариты", {
            "fields": ("weight_g", "length_cm", "width_cm", "height_cm"),
            "description": "В упаковке, в граммах и сантиметрах — по ним службы доставки "
            "считают цену. Обычно приходят из 1С и перезаписываются при обмене; вручную "
            "заполняйте, только если 1С их не присылает. Пусто — возьмём типовую посылку "
            "категории.",
        }),
        ("Витрина", {
            "fields": ("is_published", "is_new", "is_featured", "rating",
                       "review_count", "sort", "sort_site", "sort_app"),
            "description": "is_published — виден ли товар на витрине (сайт/приложение). "
            "Порядок раздельный по площадкам: sort_site — на сайте, sort_app — в "
            "приложении (данные общие, раскладка своя). Удобное перетаскивание — на "
            "странице «Конструктор витрины».",
        }),
    )
    readonly_fields = ("preview_large",)

    def get_actions(self, request):
        # Штатное «Удалить выбранные» на тысячах товаров упиралось в лимит полей
        # запроса — оставляем один путь удаления, свой.
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)
        return actions

    @admin.display(description="Остаток", ordering="stock_count")
    def stock(self, obj):
        """Остаток из 1С: всего и по размерам. Прочерк — 1С остаток ещё не присылала."""
        if obj.stock_count is None:
            return format_html('<span style="color:#9ca3af" title="{}">—</span>',
                               "1С ещё не присылала остаток")
        color = "#dc2626" if obj.stock_count <= 0 else "inherit"
        total = format_html('<b style="color:{};white-space:nowrap">{} шт</b>', color, obj.stock_count)
        sizes = sorted((obj.stock_by_size or {}).items(), key=_size_key)
        if not sizes:
            return total
        parts = [f"{size}: {count}" for size, count in sizes]
        shown = " · ".join(parts[:8]) + (" · …" if len(parts) > 8 else "")
        return format_html(
            '{}<div style="font-size:11px;color:#6b7280;white-space:nowrap" title="{}">{}</div>',
            total, " · ".join(parts), shown,
        )

    @admin.display(description="Категория")
    def category_name(self, obj):
        c = Category.objects.filter(id=obj.category_id).only("name").first()
        return c.name if c else (obj.category_id or "—")

    @admin.display(description="Фото")
    def preview(self, obj):
        url = obj.network_image_url()
        if url:
            return format_html(
                '<img src="{}" style="height:38px;width:38px;'
                'object-fit:cover;border-radius:6px"/>',
                url,
            )
        return "—"

    @admin.display(description="Текущее фото")
    def preview_large(self, obj):
        url = obj.network_image_url()
        if url:
            return format_html(
                '<img src="{}" style="max-height:160px;border-radius:10px"/>', url
            )
        return "Нет фото"


@admin.register(Banner)
class BannerAdmin(ModelAdmin):
    list_display = ("preview", "id", "title", "subtitle", "action", "is_published",
                    "sort_site", "sort_app")
    list_display_links = ("id", "title")  # заголовок кликабелен → открыть/редактировать
    list_editable = ("is_published", "sort_site", "sort_app")
    list_filter = ("is_published",)
    search_fields = ("title", "subtitle")
    ordering = ("sort",)
    actions = [make_published, make_draft]
    readonly_fields = ("preview_large",)
    fields = ("title", "subtitle", "image", "preview_large", "image_url",
              "action", "is_published", "sort", "sort_site", "sort_app")

    @admin.display(description="Фото")
    def preview(self, obj):
        url = obj.network_image_url()
        if url:
            return format_html(
                '<img src="{}" style="height:34px;border-radius:6px"/>', url
            )
        return "—"

    @admin.display(description="Текущий баннер")
    def preview_large(self, obj):
        url = obj.network_image_url()
        if url:
            return format_html(
                '<img src="{}" style="max-height:130px;border-radius:10px"/>', url
            )
        return "Нет фото"


# ── Модерация отзывов ───────────────────────────────────────────────────────

def _recompute_product_rating(product_id):
    """Пересчёт рейтинга/кол-ва товара по видимым отзывам (скрытые не считаются)."""
    agg = Review.objects.filter(product_id=product_id, hidden=False).aggregate(
        a=Avg("rating"), c=Count("id")
    )
    Product.objects.filter(id=product_id).update(
        rating=round(agg["a"] or 0, 1), review_count=agg["c"] or 0
    )


@admin.action(description="Скрыть (модерация)")
def hide_reviews(modeladmin, request, queryset):
    pids = set(queryset.values_list("product_id", flat=True))
    n = queryset.update(hidden=True)
    for pid in pids:
        _recompute_product_rating(pid)
    modeladmin.message_user(request, f"Скрыто отзывов: {n}")


@admin.action(description="Показать (снять скрытие)")
def show_reviews(modeladmin, request, queryset):
    pids = set(queryset.values_list("product_id", flat=True))
    n = queryset.update(hidden=False)
    for pid in pids:
        _recompute_product_rating(pid)
    modeladmin.message_user(request, f"Показано отзывов: {n}")


@admin.register(Review)
class ReviewAdmin(UserRefMixin, ModelAdmin):
    list_display = (
        "id", "product_ref", "user_ref", "rating", "short_text",
        "photos_count", "hidden", "created_at",
    )
    list_display_links = ("id",)
    list_editable = ("hidden",)
    list_filter = ("hidden", "rating", "created_at")
    search_fields = ("id", "product_id", "user_id", "text")
    ordering = ("-created_at",)
    actions = [hide_reviews, show_reviews]
    readonly_fields = ("photos_preview", "created_at")

    @admin.display(description="Товар")
    def product_ref(self, obj):
        p = Product.objects.filter(id=obj.product_id).only("name").first()
        return f"{p.name}" if p else f"{obj.product_id} (нет)"

    @admin.display(description="Текст")
    def short_text(self, obj):
        t = obj.text or ""
        return (t[:60] + "…") if len(t) > 60 else (t or "—")

    @admin.display(description="Фото")
    def photos_count(self, obj):
        return len(obj.photos or [])

    @admin.display(description="Фото отзыва")
    def photos_preview(self, obj):
        urls = obj.photos or []
        if not urls:
            return "Нет фото"
        return format_html_join(
            "",
            '<img src="{}" style="height:90px;border-radius:8px;'
            'margin:0 6px 6px 0;object-fit:cover"/>',
            ((u,) for u in urls),
        )
