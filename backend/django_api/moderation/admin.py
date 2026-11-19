"""Разбор жалоб и чёрный список в админке.

Жалоба без видимого решения бесполезна: человек не узнает, что с ней стало,
а модератор через неделю не вспомнит, почему отклонил. Поэтому в списке сразу
видно причину, цель, статус и дату, а в карточке — поле решения.
"""
from django.contrib import admin, messages
from django.utils import timezone

from accounts.models import Account
from clubs.models import Club
from notifications.models import create_notification

from .models import Block, ModerationMeasure, Report


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ("created_at", "reason", "target_type", "target_label",
                    "reporter_label", "status")
    list_filter = ("status", "reason", "target_type")
    search_fields = ("target_id", "reporter_id", "comment")
    readonly_fields = ("reporter_id", "target_type", "target_id", "reason",
                       "comment", "created_at", "resolved_at")
    fields = ("created_at", "reporter_id", "target_type", "target_id", "reason",
              "comment", "status", "resolution", "resolved_at")
    actions = ["mark_accepted", "mark_rejected"]

    @admin.display(description="Цель")
    def target_label(self, obj):
        if obj.target_type == Report.TARGET_CLUB:
            club = Club.objects.filter(id=obj.target_id).first()
            return club.name if club else obj.target_id
        acc = Account.objects.filter(id=obj.target_id).first()
        return (acc.name or acc.id) if acc else obj.target_id

    @admin.display(description="Заявитель")
    def reporter_label(self, obj):
        acc = Account.objects.filter(id=obj.reporter_id).first()
        return (acc.name or acc.id) if acc else obj.reporter_id

    def _resolve(self, queryset, status):
        return queryset.update(status=status, resolved_at=timezone.now())

    @admin.action(description="Приняты меры — предупредить и уведомить")
    def mark_accepted(self, request, queryset):
        """Мера без объяснения человеку — это мера, которую нельзя обжаловать.

        Поэтому действие требует заполненного «решения»: его текст и уходит
        тому, к кому применили меру. Жалоба ему не показывается никогда —
        в ней чужое имя и чужие слова.
        """
        done, skipped = 0, []
        for report in queryset:
            if not report.resolution.strip():
                skipped.append(str(report.pk))
                continue
            measure = ModerationMeasure.objects.create(
                target_type=report.target_type,
                target_id=report.target_id,
                kind=ModerationMeasure.KIND_WARNING,
                summary=report.resolution.strip(),
                report=report,
            )
            notify_measure(measure)
            notify_reporter(report, accepted=True)
            done += 1
        self._resolve(queryset.exclude(resolution=""), Report.ACCEPTED)
        if done:
            self.message_user(request, f"Мера применена и человек уведомлён: {done}")
        if skipped:
            self.message_user(
                request,
                "Без «решения модератора» меру применить нельзя — человеку нечего "
                f"будет обжаловать. Пропущены: {', '.join(skipped)}",
                level=messages.WARNING,
            )

    @admin.action(description="Отклонить")
    def mark_rejected(self, request, queryset):
        reports = list(queryset.filter(status=Report.NEW))
        self._resolve(queryset, Report.REJECTED)
        for report in reports:
            notify_reporter(report, accepted=False)

    def save_model(self, request, obj, form, change):
        if obj.status != Report.NEW and not obj.resolved_at:
            obj.resolved_at = timezone.now()
        super().save_model(request, obj, form, change)


@admin.register(Block)
class BlockAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user_id", "blocked_id")
    search_fields = ("user_id", "blocked_id")
    # Чёрный список — выбор пользователя, а не модератора: смотреть можно,
    # править из админки нечего.
    readonly_fields = ("user_id", "blocked_id", "created_at")

    def has_add_permission(self, request):
        return False


def notify_measure(measure: ModerationMeasure) -> None:
    """Сказать человеку, что к нему применили меру.

    Уведомление — единственный способ узнать: в приложение за мерами никто
    специально не ходит. Без него экран возражений существует для тех, кто
    и так догадался посмотреть.
    """
    if measure.target_type == Report.TARGET_CLUB:
        club = Club.objects.filter(id=measure.target_id).first()
        if club is None:
            return
        user_id, where = club.owner_id, f"к клубу «{club.name}»"
    else:
        user_id, where = measure.target_id, "к вашему профилю"

    create_notification(
        user_id,
        "Решение модерации",
        f"Применена мера {where}: {measure.summary[:300]} "
        "Не согласны — возразите в «Профиль → Настройки → Модерация».",
        type="system",
    )


def notify_reporter(report: Report, accepted: bool) -> None:
    """Сказать заявителю, чем кончилась его жалоба (§10: жалоба не уходит «в никуда»).

    Что именно применили, к кому и за что — заявителю не пересказываем: это
    решение о другом человеке. Хватает «разобрали, меры приняты / нарушения нет».
    """
    body = (
        "Мы разобрали вашу жалобу и приняли меры. Спасибо, что сообщили."
        if accepted
        else "Мы разобрали вашу жалобу и нарушения правил не нашли."
    )
    create_notification(report.reporter_id, "Жалоба рассмотрена",
                        body + " Подробности — «Профиль → Настройки → Модерация».",
                        type="system")


def notify_appeal(measure: ModerationMeasure) -> None:
    """Ответ на возражение: без него возражение — та же кнопка «в никуда»."""
    if measure.target_type == Report.TARGET_CLUB:
        club = Club.objects.filter(id=measure.target_id).first()
        user_id = club.owner_id if club else None
    else:
        user_id = measure.target_id
    accepted = measure.appeal_status == ModerationMeasure.APPEAL_ACCEPTED
    body = ("Возражение принято, мера снята." if accepted
            else "Возражение рассмотрено, мера остаётся в силе.")
    if measure.appeal_reply.strip():
        body += f" Ответ модератора: {measure.appeal_reply.strip()[:300]}"
    create_notification(user_id, "Ответ на возражение", body, type="system")


@admin.register(ModerationMeasure)
class ModerationMeasureAdmin(admin.ModelAdmin):
    list_display = ("created_at", "kind", "target_type", "target_id",
                    "active", "appeal_status")
    list_filter = ("kind", "appeal_status", "active", "target_type")
    search_fields = ("target_id", "summary", "appeal_text")
    readonly_fields = ("created_at", "appeal_text", "appeal_at", "report")
    fields = ("created_at", "target_type", "target_id", "kind", "summary", "active",
              "report", "appeal_text", "appeal_at", "appeal_status", "appeal_reply",
              "appeal_resolved_at")
    actions = ["appeal_accept", "appeal_reject"]

    def _close_appeal(self, queryset, status, active):
        pending = list(queryset.filter(appeal_status=ModerationMeasure.APPEAL_NEW))
        for m in pending:
            m.appeal_status, m.active, m.appeal_resolved_at = status, active, timezone.now()
            m.save(update_fields=["appeal_status", "active", "appeal_resolved_at"])
            notify_appeal(m)
        return len(pending)

    @admin.action(description="Возражение принято — снять меру")
    def appeal_accept(self, request, queryset):
        n = self._close_appeal(queryset, ModerationMeasure.APPEAL_ACCEPTED, False)
        self.message_user(request, f"Мер снято: {n}")

    @admin.action(description="Возражение отклонено")
    def appeal_reject(self, request, queryset):
        n = self._close_appeal(queryset, ModerationMeasure.APPEAL_REJECTED, True)
        self.message_user(request, f"Возражений отклонено: {n}")

    def save_model(self, request, obj, form, change):
        """Ручной разбор возражения в карточке — с тем же уведомлением, что и действие."""
        closed = (ModerationMeasure.APPEAL_ACCEPTED, ModerationMeasure.APPEAL_REJECTED)
        newly_closed = obj.appeal_status in closed and not obj.appeal_resolved_at
        if newly_closed:
            obj.appeal_resolved_at = timezone.now()
            obj.active = obj.appeal_status != ModerationMeasure.APPEAL_ACCEPTED
        super().save_model(request, obj, form, change)
        if newly_closed:
            notify_appeal(obj)
