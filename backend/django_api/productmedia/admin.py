"""Админка фотопайплайна: пакеты и задания, действие «прогнать пакет» (в фон, Celery).

Полноценная плитка-загрузка партии по артикулам появится отдельной вкладкой позже; здесь —
базовое управление и наблюдаемость: где готово, где без товара, где ошибка (например 403 с РФ-IP).
"""
from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline

from productmedia import service
from productmedia.models import PhotoBatch, PhotoJob


class PhotoJobInline(TabularInline):
    model = PhotoJob
    extra = 0
    fields = ("article", "product", "status", "attach_as", "error")
    readonly_fields = ("article", "product", "status", "attach_as", "error")
    show_change_link = True
    can_delete = False


@admin.register(PhotoBatch)
class PhotoBatchAdmin(ModelAdmin):
    list_display = ("created_at", "track", "created_by", "jobs_total")
    list_filter = ("track", "created_at")
    readonly_fields = ("created_at", "created_by")
    inlines = [PhotoJobInline]
    actions = ["run_now"]

    @admin.display(description="Заданий")
    def jobs_total(self, obj):
        return obj.jobs.count()

    @admin.action(description="Прогнать пакет (обработать в фоне)")
    def run_now(self, request, queryset):
        # Отправляем в Celery, чтобы тяжёлые вызовы ИИ не держали запрос.
        from productmedia.tasks import process_batch
        for batch in queryset:
            process_batch.delay(batch.id)
        self.message_user(request, "Пакетов отправлено в обработку: %d" % queryset.count())


@admin.register(PhotoJob)
class PhotoJobAdmin(ModelAdmin):
    list_display = ("article", "product", "track", "attach_as", "status", "created_at")
    list_filter = ("status", "track", "attach_as", "created_at")
    search_fields = ("article", "product__name", "product__article")
    readonly_fields = ("batch", "source", "master", "webp", "attempts", "reviewed_by",
                       "reviewed_at", "created_at", "updated_at", "attached_at")
    raw_id_fields = ("product",)   # товаров тысячи — без autocomplete-зависимости от ProductAdmin
    actions = ["run_selected"]

    @admin.action(description="Сгенерировать выбранные (результат — «На проверке»)")
    def run_selected(self, request, queryset):
        # Только генерация: на витрину снимок попадает после «Принять» на экране проверки.
        review = failed = skipped = 0
        for job in queryset:
            service.generate(job, from_statuses=service.CLAIM_MANUAL)
            review += job.status == PhotoJob.STATUS_REVIEW
            failed += job.status == PhotoJob.STATUS_FAILED
            skipped += job.status == PhotoJob.STATUS_SKIPPED
        self.message_user(
            request, "На проверке: %d · Ошибок: %d · Без товара: %d" % (review, failed, skipped))
