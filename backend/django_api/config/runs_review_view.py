"""Страница «Проверка забегов» в блоке «Бег и модерация» (S-04, фаза 2).

Анти-чит придерживает баллы за неправдоподобный забег, но решение принимает
человек. Раньше для этого был только плоский список забегов: видно строку, не
видно бегуна — сколько у него флагов, честные ли остальные забеги, нет ли рядом
второго аккаунта с того же телефона. Здесь всё собрано вокруг ЧЕЛОВЕКА: карточка
бегуна, его цифры, признаки мульти-аккаунта и его помеченные забеги с решениями.

Уровни доступа вкладки «Забеги» разведены по тяжести последствий:
- «смотреть» — только читать очередь;
- «редактировать» — решения по забегам, снять метку ревью, пересчитать баллы;
- «редактировать и удалять» — блокировка аккаунта.

Блокировка вдобавок требует прав на вкладку «Пользователи»: она отрезает человеку
вход в приложение, то есть это действие над аккаунтом, а не над забегом. Иначе
модератор бега получал бы власть над учётными записями в обход выданных вкладок
(D-63: право выдаётся на вкладку).
"""
from django.contrib import admin
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.utils import timezone

from accounts.models import Account
from common.security import forget_account
from runs.models import Run
from runs.review import approve_run, pending_queryset, recalculate, reject_run, runner_context
from runs.rules import REVIEW_FLAGGED_THRESHOLD, REVIEW_WINDOW
from staff.access import can, tab_required
from staff.models import LEVEL_EDIT, LEVEL_FULL, StaffAudit

MAX_RUNNERS = 50      # столько бегунов показываем за раз — очередь, а не архив
MAX_RUNS_EACH = 12    # столько помеченных забегов на карточку бегуна


def _local(dt):
    return timezone.localtime(dt).strftime("%d.%m.%Y %H:%M") if dt else ""


def _run_row(run):
    return {
        "id": run.id,
        "when": _local(run.finished_at),
        "km": round(run.distance_km, 2),
        "minutes": round(run.duration_s / 60.0),
        "speed": round(run.speed_kmh, 1),
        "reason": run.flag_reason,
        "points": run.points_awarded,
        "zones": run.captured_zones,
        "pending": run.pending_review,
        "reviewed": _local(run.reviewed_at),
        "reviewed_by": run.reviewed_by,
        "verdict": ("нарушение" if run.flagged else "одобрен") if run.reviewed_at else "",
    }


def _scope(request):
    """Что показываем: очередь (по умолчанию), всё помеченное или аккаунты на ревью."""
    mode = (request.GET.get("mode") or "pending").strip()
    if mode == "all":
        return mode, Run.objects.filter(flagged=True)
    if mode == "review":
        uids = Account.objects.filter(needs_review=True).values_list("id", flat=True)
        return mode, Run.objects.filter(flagged=True, user_id__in=list(uids))
    return "pending", pending_queryset()


def _act(request):
    """Применить решение модератора. Возвращает текст для баннера или ''."""
    action = (request.POST.get("action") or "").strip()
    who = request.user.get_username()

    def need(level):
        if not can(request.user, "runs", level):
            raise PermissionDenied("Недостаточно прав для этого действия")

    if action in ("approve", "reject"):
        need(LEVEL_EDIT)
        run = Run.objects.filter(id=(request.POST.get("run") or "")[:40]).first()
        if not run:
            return "Забег не найден — возможно, его уже разобрали."
        if action == "approve":
            points = approve_run(run, by=who)
            StaffAudit.write(request, f"забег одобрен: {run.id} (бегун {run.user_id})")
            return f"Забег одобрен, начислено баллов: {points}."
        revoked = reject_run(run, by=who)
        StaffAudit.write(request, f"забег признан нарушением: {run.id} (бегун {run.user_id})")
        return ("Забег признан нарушением."
                + (f" Списано ранее начисленных баллов: {revoked}." if revoked else ""))

    uid = (request.POST.get("uid") or "")[:40]
    if not uid:
        return ""

    if action == "clear_review":
        need(LEVEL_EDIT)
        Account.objects.filter(id=uid).update(needs_review=False)
        StaffAudit.write(request, f"снята метка «на проверке»: бегун {uid}")
        return "Метка «на проверке» снята."

    if action == "recalc":
        need(LEVEL_EDIT)
        res = recalculate(uid)
        StaffAudit.write(request, f"пересчёт баллов за бег: бегун {uid}")
        if not res["runs"]:
            return "Пересчёт: расхождений нет, баллы совпадают с забегами."
        sign = "+" if res["delta"] >= 0 else ""
        return (f"Пересчитано забегов: {res['runs']}, "
                f"изменение баланса: {sign}{res['delta']}.")

    if action in ("block", "unblock"):
        need(LEVEL_FULL)
        if not can(request.user, "accounts", LEVEL_EDIT):
            raise PermissionDenied(
                "Блокировка аккаунта требует доступа к вкладке «Пользователи»"
            )
        if action == "block":
            reason = (request.POST.get("reason") or "Нарушение правил (анти-чит)")[:300]
            Account.objects.filter(id=uid).update(is_blocked=True, block_reason=reason)
            forget_account(uid)
            StaffAudit.write(request, f"аккаунт заблокирован: бегун {uid}")
            return "Аккаунт заблокирован — вход отрезан."
        Account.objects.filter(id=uid).update(is_blocked=False, block_reason="")
        forget_account(uid)
        StaffAudit.write(request, f"аккаунт разблокирован: бегун {uid}")
        return "Аккаунт разблокирован."

    return ""


@staff_member_required
@tab_required("runs")
def runs_review(request):
    if request.method == "POST":
        note = _act(request)
        # POST → redirect → GET: обновление страницы не повторит решение.
        request.session["runs_review_note"] = note
        return redirect(f"{request.path}?mode={request.POST.get('mode') or 'pending'}")

    mode, qs = _scope(request)

    # Группируем по бегуну: модератор решает про человека, а не про строку.
    order = []
    by_user = {}
    for run in qs.order_by("-finished_at")[:MAX_RUNNERS * MAX_RUNS_EACH]:
        if run.user_id not in by_user:
            if len(order) >= MAX_RUNNERS:
                continue
            order.append(run.user_id)
            by_user[run.user_id] = []
        if len(by_user[run.user_id]) < MAX_RUNS_EACH:
            by_user[run.user_id].append(_run_row(run))

    runners = []
    for uid in order:
        ctx = runner_context(uid)
        ctx["runs"] = by_user[uid]
        ctx["pending_here"] = sum(1 for r in by_user[uid] if r["pending"])
        runners.append(ctx)
    # Сверху — у кого больше всего ждёт решения, затем самые «горячие» по флагам.
    runners.sort(key=lambda r: (-r["pending_here"], -r["flags_recent"]))

    week = timezone.now() - REVIEW_WINDOW
    ctx = {
        **admin.site.each_context(request),
        "title": "Проверка забегов",
        "runners": runners,
        "mode": mode,
        "note": request.session.pop("runs_review_note", ""),
        "may_edit": can(request.user, "runs", LEVEL_EDIT),
        # Блокировка — действие над аккаунтом: нужны обе вкладки.
        "may_block": (can(request.user, "runs", LEVEL_FULL)
                      and can(request.user, "accounts", LEVEL_EDIT)),
        "summary": {
            "pending": pending_queryset().count(),
            "accounts": Account.objects.filter(needs_review=True).count(),
            "week_flags": Run.objects.filter(flagged=True, created_at__gte=week).count(),
            "week_done": Run.objects.filter(reviewed_at__gte=week).count(),
        },
        "threshold": REVIEW_FLAGGED_THRESHOLD,
        "window_days": REVIEW_WINDOW.days,
        "limit": MAX_RUNNERS,
    }
    return TemplateResponse(request, "admin/runs_review.html", ctx)
