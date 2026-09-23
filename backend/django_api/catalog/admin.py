from django.contrib import admin, messages
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.db.models import Avg, Count, F, Q
from django.template.response import TemplateResponse
from django.utils.html import format_html, format_html_join
from unfold.admin import ModelAdmin

from common.adminutils import ColumnPickerMixin, UserRefMixin
from config.onec_fill_view import FIELDS as MISSING_FIELDS
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
    list_display = ("preview", "name", "emoji", "sort")
    list_display_links = ("name",)
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


class MissingFilter(admin.SimpleListFilter):
    """«Не заполнено» — переход со страницы «Заполненность 1С» к нужным карточкам.

    Условия берём оттуда же, чтобы список и сводка не разошлись: если на странице
    написано «без категории 3159», то по ссылке должно открыться ровно 3159 карточек.
    """

    title = "Не заполнено"
    parameter_name = "missing"

    def lookups(self, request, model_admin):
        return [(key, title) for key, title, _c, _r in MISSING_FIELDS]

    def queryset(self, request, queryset):
        for key, _title, cond, _risk in MISSING_FIELDS:
            if self.value() == key:
                return queryset.filter(cond)
        return queryset


class ShopTitleFilter(admin.SimpleListFilter):
    """Витринное название: что разобралось, что правили руками, что не вышло.

    Автоматика закрывает почти всё; остаток правится руками — этот фильтр и есть
    список «что проверить».
    """

    title = "Витринное название"
    parameter_name = "shop_title"

    def lookups(self, request, model_admin):
        return [("manual", "Правлено вручную"), ("raw", "Не разобрано"),
                ("auto", "Разобрано автоматически")]

    def queryset(self, request, queryset):
        value = self.value()
        raw = Q(display_name="") | Q(display_name=F("name"))
        if value == "manual":
            return queryset.exclude(display_name_override="")
        if value == "raw":
            return queryset.filter(display_name_override="").filter(raw)
        if value == "auto":
            return queryset.filter(display_name_override="").exclude(raw)
        return queryset


@admin.register(Product)
class ProductAdmin(ColumnPickerMixin, ModelAdmin):
    # Полный набор колонок: всё, что ведёт 1С, и всё, что ведём мы. Показывать всё
    # сразу тесно, поэтому набор настраивается шестерёнкой «Столбцы» — у каждого свой.
    # ID в списке нет: товар открывается по названию, найти по ID можно поиском.
    # Порядок — по важности для работы: фото, название целиком, общее название,
    # бренд, цена, размеры и цвета. Остальное правее и частью скрыто — включается
    # шестерёнкой «Столбцы».
    list_display = (
        "preview",
        "shop_title",
        "name",
        "brand",
        "price",
        "old_price",
        "sizes_list",
        "colors_list",
        "stock",
        "in_stock",
        "is_published",
        "is_featured",
        "is_new",
        "article",
        "category_name",
        "sort_site",
        "sort_app",
        "is_active_1c",
        "source_updated_at",
        "parcel",
        "description_short",
        "onec_code",
        "model_group",
    )
    list_display_links = ("name",)
    # Скрывать нельзя: по названию открывается карточка, а витринное имя — то,
    # что видит покупатель, и его проверяют глазами.
    columns_locked = ("name", "shop_title")
    # По умолчанию — компактный набор. Остальное не потеряно: включается шестерёнкой.
    columns_hidden_default = ("description_short", "onec_code", "source_updated_at",
                              "parcel", "category_name", "model_group")
    columns_editable = (
        "price",
        "old_price",
        "in_stock",
        "is_published",
        "is_featured",
        "is_new",
        "sort_site",
        "sort_app",
    )
    list_filter = (ShopTitleFilter, MissingFilter, "category_id", "brand", "in_stock",
                   "is_published", "is_featured", "is_new", "is_active_1c")
    search_fields = ("id", "name", "display_name", "display_name_override", "model_key",
                     "model_key_override", "brand", "article", "description")
    ordering = ("sort",)
    actions = [make_published, make_draft, "rebuild_names", delete_products]
    fieldsets = (
        ("Основное", {
            "fields": ("id", "name", "display_name", "display_name_override",
                       "model_key", "model_key_override",
                       "brand", "article", "category_id", "description"),
            "description": "«Название» 1С шлёт по позиции — с артикулом, цветом и размером "
            "(«ЖИЛЕТ Жен. BMAI арт. FRWK006-1 цвет ЧЕРНЫЙ р. XL»): так удобно на "
            "этикетке и в офлайн-магазине. «Витринное название» считается из него "
            "автоматически — это то, что видит покупатель. Если разобрано неверно, "
            "впишите своё в «Витринное название вручную»: оно сильнее автоматики. "
            "«Ключ модели» собирает позиции в одну карточку на витрине: у одежды это "
            "артикул модели (FRWK006 из FRWK006-1), у обуви — витринное название. "
            "Чтобы перенести позицию в другую карточку, впишите её ключ вручную.",
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
    readonly_fields = ("preview_large", "display_name", "model_key")

    @admin.action(description="🔤 Пересчитать витринные названия и модели")
    def rebuild_names(self, request, queryset):
        """Пересчитать разбор названий у выбранных товаров.

        Обычно имя и ключ модели считаются сами при выгрузке из 1С. Кнопка нужна,
        когда правила разбора поменялись, а выгрузки ждать незачем — и чтобы это
        не требовало доступа к серверу. Ручные правки не трогаем: они сильнее.
        """
        changed = []
        for product in queryset.iterator(chunk_size=500):
            was = (product.display_name, product.model_key)
            product.rebuild_display_name()
            if (product.display_name, product.model_key) != was:
                changed.append(product)
        for start in range(0, len(changed), 500):
            Product.objects.bulk_update(changed[start:start + 500],
                                        ["display_name", "model_key"])
        StaffAudit.write(request, f"пересчитаны витринные названия: {len(changed)}")
        self.message_user(request, f"Пересчитано названий: {len(changed)}", messages.SUCCESS)

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

    @admin.display(description="Размеры")
    def sizes_list(self, obj):
        return self._joined(obj.sizes)

    @admin.display(description="Цвета")
    def colors_list(self, obj):
        return self._joined(obj.colors)

    @staticmethod
    def _joined(values):
        """Список из 1С в строку. Пусто — прочерк: карточка ещё не заполнена."""
        items = [str(v).strip() for v in (values or []) if str(v or "").strip()]
        if not items:
            return "—"
        shown = ", ".join(items[:6]) + ("…" if len(items) > 6 else "")
        return format_html('<span title="{}">{}</span>', ", ".join(items), shown)

    @admin.display(description="Посылка", ordering="weight_g")
    def parcel(self, obj):
        """Вес и габариты для расчёта доставки. Прочерк — 1С ещё не прислала."""
        if not obj.weight_g and not obj.length_cm:
            return "—"
        size = "×".join(str(v) for v in (obj.length_cm, obj.width_cm, obj.height_cm) if v)
        weight = f"{obj.weight_g} г" if obj.weight_g else ""
        return format_html('<span style="white-space:nowrap">{}</span>',
                           " · ".join(x for x in (weight, f"{size} см" if size else "") if x))

    @admin.display(description="Описание")
    def description_short(self, obj):
        text = (obj.description or "").strip()
        if not text:
            return "—"
        short = text[:60] + ("…" if len(text) > 60 else "")
        return format_html('<span title="{}">{}</span>', text[:400], short)

    @admin.display(description="Код 1С", ordering="external_id")
    def onec_code(self, obj):
        return obj.external_id or obj.article or "—"

    @admin.display(description="Витринное название", ordering="display_name")
    def shop_title(self, obj):
        """Что увидит покупатель. Складское имя 1С остаётся в колонке «Название»:
        оно нужно магазину для этикеток и поиска по артикулу."""
        title = obj.shop_title
        if obj.display_name_override:
            return format_html('{} <span class="m-tag info">вручную</span>', title)
        if title == obj.name:
            return format_html('<span title="{}">{}</span> '
                               '<span class="m-tag warn">не разобрано</span>', obj.name, title)
        return format_html('<span title="{}">{}</span>', obj.name, title)

    @admin.display(description="Модель", ordering="model_key")
    def model_group(self, obj):
        """Ключ карточки на витрине: у одежды это артикул модели, у обуви — имя.
        Позиции с одним ключом покупатель видит как одну карточку."""
        key = obj.shop_model_key
        if not key:
            return "—"
        if obj.model_key_override:
            return format_html('{} <span class="m-tag info">вручную</span>', key)
        return key

    @admin.display(description="Категория")
    def category_name(self, obj):
        c = Category.objects.filter(id=obj.category_id).only("name").first()
        return c.name if c else (obj.category_id or "—")

    @admin.display(description="Фото")
    def preview(self, obj):
        url = obj.network_image_url()
        if url:
            return format_html(
                '<img src="{}" style="height:30px;width:30px;'
                'object-fit:cover;border-radius:5px"/>',
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
    list_display = ("preview", "title", "subtitle", "action", "is_published",
                    "sort_site", "sort_app")
    list_display_links = ("title",)
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
        "product_ref", "user_ref", "rating", "short_text",
        "photos_count", "hidden", "created_at",
    )
    list_display_links = ("short_text",)
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
