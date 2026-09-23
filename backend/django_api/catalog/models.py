"""Каталог Store на бэке (D-13): категории, товары, баннеры.
Контракт JSON совпадает с моделями SportStore (Category/Product), чтобы клиент
только переключил флаг useApiCatalog без правок парсинга."""
from django.db import models
from django.utils import timezone


class Category(models.Model):
    id = models.CharField(primary_key=True, max_length=40, verbose_name="ID")
    name = models.CharField(max_length=120, verbose_name="Название")
    emoji = models.CharField(max_length=16, blank=True, default="", verbose_name="Эмодзи")
    image_url = models.CharField(max_length=300, null=True, blank=True, verbose_name="Ссылка на фото")
    # Загруженное в админке фото категории (приоритетнее image_url).
    image = models.ImageField(upload_to="uploads/categories/", null=True, blank=True, verbose_name="Фото")
    sort = models.IntegerField(default=0, verbose_name="Порядок")
    # Типовая посылка для товаров категории, пока у самих товаров нет веса и
    # габаритов (D-79). Граммы и сантиметры — в них считают службы доставки.
    default_weight_g = models.PositiveIntegerField(null=True, blank=True, verbose_name="Типовой вес, г")
    default_length_cm = models.PositiveIntegerField(null=True, blank=True, verbose_name="Типовая длина, см")
    default_width_cm = models.PositiveIntegerField(null=True, blank=True, verbose_name="Типовая ширина, см")
    default_height_cm = models.PositiveIntegerField(null=True, blank=True, verbose_name="Типовая высота, см")
    # Родитель из 1С (D-62). Витрина пока плоская и это поле не показывает, но
    # принимать и хранить его надо: иначе, когда дерево понадобится, придётся
    # просить 1С выгружать справочник заново.
    parent_id = models.CharField(max_length=40, blank=True, default="", db_index=True,
                                 verbose_name="Родительская категория (ID)")

    class Meta:
        db_table = "catalog_categories"
        ordering = ["sort"]
        verbose_name = "Категория"
        verbose_name_plural = "Категории"

    def __str__(self) -> str:
        return self.name

    def network_image_url(self) -> str:
        """Сетевой URL фото: приоритет — загруженное в админке, иначе ссылка."""
        if self.image:
            return self.image.url
        return self.image_url or ""

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "emoji": self.emoji,
            "imageUrl": self.network_image_url(),
        }


class Product(models.Model):
    id = models.CharField(primary_key=True, max_length=40, verbose_name="ID")
    name = models.CharField(max_length=200, verbose_name="Название")
    # Общее (родовое) название модели из 1С: в `name` у них лежит конкретная
    # позиция — «BMAI PURE 2.0 черный 36р.», а общее название одно на все размеры
    # и цвета. Нужно, чтобы на витрине собирать карточку модели, а не 30 карточек.
    global_name = models.CharField(max_length=200, blank=True, default="",
                                   verbose_name="Общее название (1С)")
    # Витринное название: складское имя 1С без артикула, цвета и размера
    # («ЖИЛЕТ Жен. BMAI арт. FRWK006-1 цвет ЧЕРНЫЙ р. XL» → «Жилет женский BMAI»).
    # Считается автоматически при каждой выгрузке (catalog/naming.py).
    display_name = models.CharField(max_length=200, blank=True, default="",
                                    verbose_name="Витринное название")
    # Ручная правка: если заполнено — показываем её, автоматика не перебивает.
    display_name_override = models.CharField(max_length=200, blank=True, default="",
                                             verbose_name="Витринное название вручную")
    brand = models.CharField(max_length=120, blank=True, default="", verbose_name="Бренд")
    category_id = models.CharField(max_length=40, db_index=True, verbose_name="Категория")
    price = models.FloatField(verbose_name="Цена")
    old_price = models.FloatField(null=True, blank=True, verbose_name="Старая цена")
    image_urls = models.JSONField(default=list, verbose_name="Старые фото (бандл)")
    # Загруженное в админке фото (приоритетнее image_urls). Отдаётся по сети как
    # /media/uploads/products/... — видно в каталоге и трекере кроссовок Квартала.
    image = models.ImageField(upload_to="uploads/products/", null=True, blank=True, verbose_name="Фото")
    description = models.TextField(blank=True, default="", verbose_name="Описание")
    sizes = models.JSONField(default=list, verbose_name="Размеры")
    colors = models.JSONField(default=list, verbose_name="Цвета")
    is_new = models.BooleanField(default=False, verbose_name="Новинка")
    is_featured = models.BooleanField(default=False, verbose_name="Рекомендуемый")
    rating = models.FloatField(default=0, verbose_name="Рейтинг")
    review_count = models.IntegerField(default=0, verbose_name="Кол-во отзывов")
    in_stock = models.BooleanField(default=True, verbose_name="В наличии")
    # Draft→Publish: на витрине (сайт/приложение) видны только опубликованные;
    # черновик виден в админ-превью (?preview=1). Существующие → опубликованы.
    is_published = models.BooleanField(default=True, db_index=True, verbose_name="Опубликован")
    sort = models.IntegerField(default=0, verbose_name="Порядок")
    # Раздельный порядок витрины по площадкам (мерчендайзинг per-channel): данные
    # товара общие, а раскладка раздельная. API отдаёт порядок по ?platform=site|app
    # (sort_site / sort_app); без параметра — по общему sort (обратная совместимость).
    sort_site = models.IntegerField(default=0, verbose_name="Порядок (сайт)")
    sort_app = models.IntegerField(default=0, verbose_name="Порядок (приложение)")

    # ── Обмен с 1С (D-62). Источник правды по номенклатуре — 1С, но владелец может
    # точечно переопределить поле в Конструкторе: тогда импорт его НЕ затирает.
    # Схема: эффективное значение живёт в обычных полях (витрина не меняется),
    # `from_1c` хранит последнее присланное 1С, `overrides` — что владелец правил руками.
    external_id = models.CharField(max_length=64, null=True, blank=True, unique=True,
                                   db_index=True, verbose_name="ID в 1С")
    article = models.CharField(max_length=64, blank=True, default="", db_index=True,
                               verbose_name="Артикул")
    stock_count = models.IntegerField(null=True, blank=True, verbose_name="Остаток, шт")
    # Остаток по размерам: {"41": 0, "42": 7}. Нужен, чтобы витрина гасила размер,
    # которого нет, а не сообщала об этом уже в корзине. Общий остаток
    # (`stock_count`) остаётся суммой — на него смотрит карточка списка.
    stock_by_size = models.JSONField(default=dict, blank=True, verbose_name="Остаток по размерам")
    # «В продаже» по данным 1С. Отдельно от is_published: 1С снимает с продажи,
    # владелец скрывает с витрины — эти решения независимы.
    is_active_1c = models.BooleanField(default=True, db_index=True, verbose_name="В продаже (1С)")
    source_updated_at = models.DateTimeField(null=True, blank=True, verbose_name="Изменён в 1С")
    from_1c = models.JSONField(default=dict, blank=True, verbose_name="Значения из 1С")
    overrides = models.JSONField(default=list, blank=True, verbose_name="Переопределено владельцем")
    # Вес и габариты в упаковке — для расчёта доставки (D-79). Ведёт 1С (склад знает
    # точный вес); если 1С не прислала, остаётся ручной ввод в админке. На витрину
    # не отдаются — это логистика, не контент.
    weight_g = models.PositiveIntegerField(null=True, blank=True, verbose_name="Вес в упаковке, г")
    length_cm = models.PositiveIntegerField(null=True, blank=True, verbose_name="Длина упаковки, см")
    width_cm = models.PositiveIntegerField(null=True, blank=True, verbose_name="Ширина упаковки, см")
    height_cm = models.PositiveIntegerField(null=True, blank=True, verbose_name="Высота упаковки, см")

    class Meta:
        db_table = "catalog_products"
        ordering = ["sort"]
        verbose_name = "Товар"
        verbose_name_plural = "Товары"

    def __str__(self) -> str:
        return self.name

    @property
    def shop_title(self) -> str:
        """Что видит покупатель: ручная правка, иначе автоматическая, иначе имя 1С."""
        return (self.display_name_override or self.display_name or self.name).strip()

    def rebuild_display_name(self) -> str:
        """Пересчитать витринное имя из складского. Возвращает результат."""
        from .naming import shop_name

        self.display_name = shop_name(self.name, self.sizes, self.colors, self.article)[:200]
        return self.display_name

    def network_image_url(self) -> str:
        """Сетевой URL фото товара (для Квартала/сайта). Приоритет — загруженное
        в админке фото; иначе первый из старых бандл-ассетов как /media/products/…"""
        if self.image:
            return self.image.url
        imgs = self.image_urls or []
        if imgs:
            return f"/media/products/{str(imgs[0]).split('/')[-1]}"
        return ""

    # Поля, которые владелец вправе переопределить (остаток — нет: продадим то, чего нет).
    OVERRIDABLE = ("price", "oldPrice", "description", "sizes", "colors", "images")

    def is_overridden(self, field: str) -> bool:
        return field in (self.overrides or [])

    def set_override(self, field: str, on: bool = True) -> None:
        """Отметить/снять ручное переопределение поля владельцем."""
        cur = list(self.overrides or [])
        if on and field not in cur:
            cur.append(field)
        if not on and field in cur:
            cur.remove(field)
        self.overrides = cur

    def onec_diff(self) -> dict:
        """Где значение владельца разошлось с 1С — для пометки в Конструкторе."""
        src = self.from_1c or {}
        mine = {
            "price": self.price, "oldPrice": self.old_price,
            "description": self.description, "sizes": self.sizes or [],
            "colors": self.colors or [], "images": self.image_urls or [],
        }
        out = {}
        for f in self.OVERRIDABLE:
            if f in src and self.is_overridden(f) and src[f] != mine.get(f):
                out[f] = {"onec": src[f], "mine": mine.get(f)}
        return out

    def to_json(self) -> dict:
        return {
            "id": self.id,
            # Покупателю — чистое имя модели. Складское («…арт. FRWK006-1 цвет
            # ЧЕРНЫЙ р. XL») нужно магазину для этикеток, но не витрине.
            "name": self.shop_title,
            "brand": self.brand,
            "categoryId": self.category_id,
            "price": self.price,
            "oldPrice": self.old_price,
            "imageUrls": self.image_urls or [],
            "imageUrl": self.network_image_url(),
            "description": self.description,
            "sizes": self.sizes or [],
            "colors": self.colors or [],
            "isNew": self.is_new,
            "isFeatured": self.is_featured,
            "rating": self.rating,
            "reviewCount": self.review_count,
            "inStock": self.in_stock,
            # Пусто = разбивки нет (1С прислала общий остаток или товар не из 1С).
            # Витрина в этом случае считает доступными все размеры, как раньше.
            "stockBySize": self.stock_by_size or {},
        }


class Banner(models.Model):
    id = models.AutoField(primary_key=True, verbose_name="ID")
    title = models.CharField(max_length=200, verbose_name="Заголовок")
    subtitle = models.CharField(max_length=200, blank=True, default="", verbose_name="Подзаголовок")
    image_url = models.CharField(max_length=300, blank=True, default="", verbose_name="Ссылка на фото")
    # Загруженный в админке баннер (приоритетнее image_url) → /media/uploads/banners/…
    image = models.ImageField(upload_to="uploads/banners/", null=True, blank=True, verbose_name="Фото")
    action = models.CharField(max_length=80, blank=True, default="", verbose_name="Действие")
    is_published = models.BooleanField(default=True, db_index=True, verbose_name="Опубликован")
    # Подгон фото баннера: cover — заполнить (обрезка); contain — фото целиком (не режется).
    image_fit = models.CharField(max_length=10, default="cover", verbose_name="Подгон фото")
    # Фокус-область (background-position), напр. "50% 30%".
    image_focal = models.CharField(max_length=16, default="50% 50%", verbose_name="Фокус фото")
    sort = models.IntegerField(default=0, verbose_name="Порядок")
    # Раздельный порядок промо по площадкам (мерчендайзинг per-channel), как у товаров.
    sort_site = models.IntegerField(default=0, verbose_name="Порядок (сайт)")
    sort_app = models.IntegerField(default=0, verbose_name="Порядок (приложение)")

    class Meta:
        db_table = "catalog_banners"
        ordering = ["sort"]
        verbose_name = "Баннер"
        verbose_name_plural = "Баннеры"

    def __str__(self) -> str:
        return self.title

    def network_image_url(self) -> str:
        """Сетевой URL баннера: приоритет — загруженное в админке, иначе ссылка."""
        if self.image:
            return self.image.url
        return self.image_url or ""

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "subtitle": self.subtitle,
            "imageUrl": self.network_image_url(),
            "action": self.action,
            "imageFit": self.image_fit or "cover",
            "imageFocal": self.image_focal or "50% 50%",
        }


class Review(models.Model):
    """Отзыв на товар. Один отзыв на пользователя+товар (можно отредактировать).
    Рейтинг/кол-во в Product пересчитываются из отзывов."""

    id = models.CharField(primary_key=True, max_length=40, verbose_name="ID")
    product_id = models.CharField(max_length=40, db_index=True, verbose_name="Товар (ID)")
    user_id = models.CharField(max_length=40, db_index=True, verbose_name="Пользователь (ID)")
    rating = models.IntegerField(verbose_name="Оценка (1–5)")
    text = models.TextField(blank=True, default="", verbose_name="Текст")
    photos = models.JSONField(default=list, blank=True, verbose_name="Фото (URL)")
    hidden = models.BooleanField(default=False, verbose_name="Скрыт (модерация)")
    created_at = models.DateTimeField(default=timezone.now, verbose_name="Создан")

    class Meta:
        db_table = "catalog_reviews"
        unique_together = (("product_id", "user_id"),)
        ordering = ["-created_at"]
        verbose_name = "Отзыв"
        verbose_name_plural = "Отзывы"


class SiteContent(models.Model):
    """Редактируемый контент сайта (мини-CMS для «Конструктора»): тексты и фото
    шапки/hero/секций. Ключ → текст/фото. Сайт читает через GET /v1/site/content и
    подставляет в элементы с data-edit / data-edit-img; правится кликом в конструкторе."""

    key = models.CharField(primary_key=True, max_length=80, verbose_name="Ключ")
    value = models.TextField(blank=True, default="", verbose_name="Текст")
    image = models.ImageField(upload_to="uploads/site/", null=True, blank=True, verbose_name="Фото")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Обновлено")

    class Meta:
        db_table = "site_content"
        verbose_name = "Контент сайта"
        verbose_name_plural = "Контент сайта"

    def __str__(self) -> str:
        return self.key

    def image_url(self) -> str:
        return self.image.url if self.image else ""

    def to_json(self) -> dict:
        return {"value": self.value, "imageUrl": self.image_url()}
