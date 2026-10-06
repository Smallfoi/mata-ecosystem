"""Раздел админки «Программа лояльности» (ТЗ v1 30.09.2026, этап «админка владельца»).

Всё, что связано с лояльностью, владелец настраивает здесь сам, без программиста:
- «Обзор» — выключатель программы, перенос балансов, главные цифры;
- «Уровни» — таблица четырёх уровней (пороги, проценты, сроки, лимиты);
- «Начисления» — бонусы за действия, лимиты, удержание, проверка пробежки, стоп-кран;
- «Товары в программе» — какие категории, бренды и товары оплачиваются бонусами
  и дают бонусы; проверка «почему этот товар не оплачивается бонусами»;
- «Участники» — карточка человека, ручное начисление/списание с комментарием;
- «Журнал» — события loyalty_events (только просмотр) и выгрузка CSV;
- «История настроек» — кто, когда, что поменял.

Страницы «Уровни» и «Начисления» строятся из реестра `loyalty.config.SPECS`:
новый ключ (например, этапа 2) появляется на своей странице сам.
Доступ — вкладка «Программа лояльности» (`loyalty_settings`): «смотреть» — всё
видно, «редактировать» — менять настройки и делать ручные операции.
Сохранение сбрасывает кэш настроек — изменения действуют сразу.
"""
import csv
from datetime import datetime, time, timedelta

from django.contrib import admin
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils import timezone

from catalog.models import Category, Product
from loyalty import config, program, v1
from loyalty.models_v1 import LoyaltyEvent, LoyaltySettingChange
from staff.access import can, tab_required
from staff.models import LEVEL_EDIT, StaffAudit

TAB = "loyalty_settings"
NOTE_KEY = "loyalty_program_note"

PAGES = (
    ("loyalty_program", "Обзор"),
    ("loyalty_levels", "Уровни"),
    ("loyalty_accruals", "Начисления"),
    ("loyalty_products", "Товары в программе"),
    ("loyalty_members", "Участники"),
    ("loyalty_journal", "Журнал"),
    ("loyalty_history", "История настроек"),
)

EVENT_TITLES = {
    "accrue_purchase": "Начисление за покупку",
    "accrue_run": "Бонус за пробежку",
    "accrue_capture": "Бонус за захват",
    "accrue_stage": "Бонус за этап",
    "accrue_referral": "Бонус за приглашение",
    "accrue_signup": "Бонус за регистрацию",
    "accrue_manual": "Ручная операция",
    "accrue_migration": "Перенос баланса",
    "hold_release": "Вышло из удержания",
    "redeem": "Оплата бонусами",
    "redeem_return": "Возврат бонусов",
    "cancel": "Отмена начисления",
    "expire": "Сгорание",
    "level_up": "Повышение уровня",
    "level_down": "Понижение уровня",
    "stoploss_on": "Стоп-кран включён",
    "stoploss_off": "Стоп-кран выключен",
}

LOT_STATES = dict((k, v) for k, v in v1.LoyaltyLot.STATE_CHOICES)


# ── общее ────────────────────────────────────────────────────────────────────

def _may_edit(request) -> bool:
    return can(request.user, TAB, LEVEL_EDIT)


def _need_edit(request):
    if not _may_edit(request):
        raise PermissionDenied("Недостаточно прав: нужно «редактировать» на вкладке "
                               "«Программа лояльности»")


def _who(request) -> str:
    return request.user.get_username()[:150]


def _local(dt, fmt="%d.%m.%Y %H:%M"):
    return timezone.localtime(dt).strftime(fmt) if dt else "—"


def _note(request, text, kind="good"):
    request.session[NOTE_KEY] = {"text": text, "kind": kind}


def _ctx(request, current, title, **extra):
    note = request.session.pop(NOTE_KEY, None)
    return {
        **admin.site.each_context(request),
        "title": f"Программа лояльности · {title}",
        "nav": [{"url": reverse(name), "title": t, "on": name == current} for name, t in PAGES],
        "may_edit": _may_edit(request),
        "note": note,
        "program_on": config.enabled(),
        **extra,
    }


def _back(request, name, query=""):
    url = reverse(name)
    return redirect(f"{url}?{query}" if query else url)


# ── значения настроек: показ и разбор ввода ─────────────────────────────────

def _num_text(v) -> str:
    return f"{round(float(v), 6):g}".replace(".", ",")


def show_one(spec, v) -> str:
    """Одно число так, как его видит владелец (проценты, м:сс)."""
    if v is None:
        return "—"
    if spec.unit == "%":
        return _num_text(float(v) * 100) + "%"
    if spec.unit == "pace":
        v = int(v)
        return f"{v // 60}:{v % 60:02d}"
    if isinstance(v, bool):
        return "да" if v else "нет"
    return _num_text(v) if isinstance(v, float) else str(v)


def show(key, value) -> str:
    spec = config.SPECS.get(key)
    if value is None:
        return "по ТЗ"
    if spec is None:
        return str(value)
    if isinstance(value, list):
        if spec.kind in ("codes", "names"):
            return ", ".join(str(x) for x in value) if value else "пусто"
        return " / ".join(show_one(spec, x) for x in value)
    return show_one(spec, value)


def input_text(spec, v) -> str:
    """Значение в поле ввода (без знака %)."""
    if spec.unit == "%":
        return _num_text(float(v) * 100)
    if spec.unit == "pace":
        v = int(v)
        return f"{v // 60}:{v % 60:02d}"
    return _num_text(v) if isinstance(v, float) else str(v)


def parse_one(spec, raw):
    """Текст поля → значение в единицах хранения. ConfigError — понятным текстом."""
    text = (raw or "").strip().replace(" ", "").replace(",", ".").rstrip("%")
    if not text:
        raise config.ConfigError("заполните поле")
    integer = spec.kind in ("int", "levels_int", "thresholds")
    if spec.unit == "pace":
        try:
            if ":" in text:
                m, s = text.split(":", 1)
                m, s = int(m), int(s)
                if not 0 <= s < 60:
                    raise ValueError
                return m * 60 + s
            return int(text)
        except ValueError:
            raise config.ConfigError("темп пишите как мин:сек, например 3:00") from None
    try:
        num = float(text)
    except ValueError:
        raise config.ConfigError("нужно число") from None
    if spec.unit == "%":
        if not 0 <= num <= 100:
            raise config.ConfigError("процент — от 0 до 100")
        return round(num / 100, 6)
    if integer:
        if num != int(num):
            raise config.ConfigError("нужно целое число")
        return int(num)
    return num


def _field(key, spec, value, name, label=""):
    return {"key": key, "name": name, "label": label, "value": input_text(spec, value),
            "unit": "%" if spec.unit == "%" else ""}


def _save(request, values: dict, comment: str, where: str):
    """Проверить и сохранить. Возвращает (ошибки {ключ: текст}, изменённые ключи)."""
    try:
        changed = config.set_many(values, by=_who(request), comment=comment)
    except config.ConfigError as e:
        errs = e.args[0] if e.args and isinstance(e.args[0], dict) else {"": str(e)}
        return errs, []
    if changed:
        StaffAudit.write(request, f"лояльность: {where} — изменено: {', '.join(changed)}")
    return {}, changed


def _saved_text(changed):
    if not changed:
        return "Ничего не изменилось."
    titles = ", ".join(f"«{config.SPECS[k].title}»" for k in changed)
    return f"Сохранено и уже действует: {titles}."


# ── 1. Обзор ─────────────────────────────────────────────────────────────────

def _warnings():
    out = []
    mig = program.migration_status()
    if mig["pending"]:
        out.append(f"Перенос балансов не завершён: ещё {mig['pending']} аккаунтов не "
                   "перенесены. Сначала «Выполнить перенос».")
    if not config.get("EXCLUDED_CATEGORIES_1C"):
        out.append("Не заданы категории без оплаты бонусами (спортпитание, сертификаты, "
                   "архив — по ТЗ). Задайте их в «Товары в программе».")
    return mig, out


@staff_member_required
@tab_required(TAB)
def loyalty_program(request):
    if request.method == "POST":
        action = request.POST.get("action") or ""
        if action == "toggle":
            _need_edit(request)
            turn_on = request.POST.get("value") == "on"
            _mig, warns = _warnings()
            if turn_on and warns and request.POST.get("confirm") != "yes":
                _note(request, "Программа НЕ включена: отметьте «Понимаю, включить "
                      "всё равно» — или сначала устраните предупреждения.", "err")
                return _back(request, "loyalty_program")
            comment = (request.POST.get("comment") or "").strip()
            config.set_value("LOYALTY_V1_ENABLED", turn_on, by=_who(request),
                             comment=comment or ("включена из админки" if turn_on
                                                 else "выключена из админки"))
            StaffAudit.write(request, "лояльность: программа "
                             + ("ВКЛЮЧЕНА" if turn_on else "выключена"))
            _note(request, "Программа лояльности включена — новые правила действуют."
                  if turn_on else "Программа лояльности выключена — работают прежние правила.")
            return _back(request, "loyalty_program")
        if action in ("migrate_dry", "migrate_apply"):
            apply = action == "migrate_apply"
            if apply:
                _need_edit(request)
                if request.POST.get("confirm") != "yes":
                    _note(request, "Перенос не выполнен: нужно подтверждение.", "err")
                    return _back(request, "loyalty_program")
            res = program.migrate_all(apply=apply)
            if apply:
                StaffAudit.write(request, f"лояльность: перенос в v1 — перенесено "
                                          f"{res['moved']}, баллов {res['total']}")
            request.session["loyalty_migration"] = {
                k: res[k] for k in ("apply", "moved", "skipped", "total", "held", "negative",
                                    "levels")}
            return _back(request, "loyalty_program")
        return _back(request, "loyalty_program")

    mig, warns = _warnings()
    return TemplateResponse(request, "admin/loyalty_program/overview.html", _ctx(
        request, "loyalty_program", "Обзор",
        stats=program.overview(), migration=mig, warnings=warns,
        migration_result=request.session.pop("loyalty_migration", None),
        enabled_spec=config.SPECS["LOYALTY_V1_ENABLED"],
    ))


# ── 2. Уровни ────────────────────────────────────────────────────────────────

def _level_columns():
    """Столбцы таблицы уровней — из реестра настроек (страница levels)."""
    cols = []
    for key, spec in config.SPECS.items():
        if config.page_of(key) != "levels":
            continue
        value = config.get(key)
        cells = []
        for lvl in range(len(config.LEVELS)):
            if spec.kind == "thresholds":
                cell = None if lvl == 0 else _field(key, spec, value[lvl - 1], f"{key}__{lvl - 1}")
            elif spec.kind in ("levels_int", "levels_float"):
                cell = _field(key, spec, value[lvl], f"{key}__{lvl}")
            elif spec.kind in ("int", "float") and spec.level_only is not None:
                cell = _field(key, spec, value, key) if lvl == spec.level_only else None
            else:
                cell = None
            cells.append(cell)
        cols.append({"key": key, "spec": spec, "cells": cells, "effective": show(key, value),
                     "default": show(key, spec.default)})
    return cols


def _read_level_form(post):
    values, errors = {}, {}
    for key, spec in config.SPECS.items():
        if config.page_of(key) != "levels":
            continue
        try:
            if spec.kind == "thresholds":
                values[key] = [parse_one(spec, post.get(f"{key}__{i}")) for i in range(3)]
            elif spec.kind in ("levels_int", "levels_float"):
                values[key] = [parse_one(spec, post.get(f"{key}__{i}")) for i in range(4)]
            elif spec.kind in ("int", "float") and key in post:
                values[key] = parse_one(spec, post.get(key))
        except config.ConfigError as e:
            errors[key] = str(e)
    return values, errors


@staff_member_required
@tab_required(TAB)
def loyalty_levels(request):
    errors, posted = {}, None
    if request.method == "POST":
        _need_edit(request)
        values, errors = _read_level_form(request.POST)
        if not errors:
            errors, changed = _save(request, values, request.POST.get("comment", "").strip(),
                                    "уровни")
            if not errors:
                _note(request, _saved_text(changed))
                return _back(request, "loyalty_levels")
        posted = request.POST
    cols = _level_columns()
    if posted is not None:  # при ошибке — показываем то, что ввёл человек
        for col in cols:
            for cell in col["cells"]:
                if cell:
                    cell["value"] = posted.get(cell["name"], cell["value"])
    rows = [{"title": t, "index": i, "cells": [c["cells"][i] for c in cols]}
            for i, t in enumerate(config.LEVEL_TITLES)]
    return TemplateResponse(request, "admin/loyalty_program/levels.html", _ctx(
        request, "loyalty_levels", "Уровни", cols=cols, rows=rows,
        errors=[(config.SPECS[k].title if k in config.SPECS else "", t)
                for k, t in errors.items()],
        hard_ceiling=round(config.HARD_REDEEM_CEILING * 100),
        history=_history_rows(LoyaltySettingChange.objects.filter(
            key__in=[c["key"] for c in cols])[:15]),
    ))


# ── 3. Начисления ────────────────────────────────────────────────────────────

def _accrual_keys():
    return [k for k in config.SPECS if config.page_of(k) == "accrual"
            and config.SPECS[k].kind in ("int", "float", "bool")]


@staff_member_required
@tab_required(TAB)
def loyalty_accruals(request):
    errors, posted = {}, None
    keys = _accrual_keys()
    if request.method == "POST":
        _need_edit(request)
        values = {}
        for key in keys:
            spec = config.SPECS[key]
            if spec.kind == "bool":
                if f"{key}__present" in request.POST:
                    values[key] = request.POST.get(key) == "on"
                continue
            if key not in request.POST:
                continue
            try:
                values[key] = parse_one(spec, request.POST.get(key))
            except config.ConfigError as e:
                errors[key] = str(e)
        if not errors:
            errors, changed = _save(request, values, request.POST.get("comment", "").strip(),
                                    "начисления")
            if not errors:
                _note(request, _saved_text(changed))
                return _back(request, "loyalty_accruals")
        posted = request.POST

    groups = {g: [] for g in config.GROUPS}
    for key in keys:
        spec = config.SPECS[key]
        value = config.get(key)
        item = {"key": key, "spec": spec, "kind": spec.kind,
                "effective": show(key, value), "default": show(key, spec.default),
                "is_default": value == spec.default, "error": errors.get(key, ""),
                "checked": bool(value) if spec.kind == "bool" else False,
                "value": "" if spec.kind == "bool" else input_text(spec, value),
                "unit": "%" if spec.unit == "%" else ("мин:сек" if spec.unit == "pace" else "")}
        if posted is not None and spec.kind != "bool":
            item["value"] = posted.get(key, item["value"])
        groups.setdefault(spec.group or config.OTHER_GROUP, []).append(item)
    return TemplateResponse(request, "admin/loyalty_program/accruals.html", _ctx(
        request, "loyalty_accruals", "Начисления",
        groups=[(g, items) for g, items in groups.items() if items],
        errors=[(config.SPECS[k].title if k in config.SPECS else "", t)
                for k, t in errors.items()],
        history=_history_rows(LoyaltySettingChange.objects.filter(key__in=keys)[:15]),
    ))


# ── 4. Товары в программе ────────────────────────────────────────────────────

def _products_post(request):
    _need_edit(request)
    action = request.POST.get("action") or ""
    comment = (request.POST.get("comment") or "").strip()
    post = request.POST
    if action == "categories":
        # Только категории, которые были на странице: появившаяся за это время
        # категория не исключится сама собой (флажок «не отмечен» = исключена).
        known = [c for c in post.getlist("cats") if c]
        known_set = set(known)
        values = {}
        for key, prefix in (("EXCLUDED_CATEGORIES_1C", "redeem_"),
                            ("NO_ACCRUAL_CATEGORIES_1C", "accrual_")):
            # Флажок = «участвует». Не отмечен — категория исключена. Коды, которых
            # нет в каталоге (категория пропала из 1С), сохраняем как были.
            keep = [c for c in config.get(key) if c not in known_set]
            values[key] = keep + [c for c in known if post.get(prefix + c) != "on"]
        errors, changed = _save(request, values, comment, "товары: категории")
    elif action == "brands":
        listed, i = [], 0
        while f"brand_{i}" in post:
            listed.append(post.get(f"brand_{i}"))
            i += 1
        listed_keys = {v1._brand_key(b) for b in listed}
        values = {}
        for key, prefix in (("EXCLUDED_BRANDS", "redeem_"), ("NO_ACCRUAL_BRANDS", "accrual_")):
            keep = [b for b in config.get(key) if v1._brand_key(b) not in listed_keys]
            values[key] = keep + [b for i, b in enumerate(listed)
                                  if post.get(f"{prefix}{i}") != "on"]
        errors, changed = _save(request, values, comment, "товары: бренды")
    elif action in ("product_add", "product_remove"):
        pid = (post.get("pid") or "").strip()[:40]
        key = {"redeem": "EXCLUDED_PRODUCTS", "accrual": "NO_ACCRUAL_PRODUCTS"}.get(
            post.get("list") or "")
        if not pid or not key:
            _note(request, "Не понял, какой товар и в какой список.", "err")
            return
        if action == "product_add" and not Product.objects.filter(pk=pid).exists():
            _note(request, "Такого товара нет в каталоге.", "err")
            return
        current = config.get(key)
        new = sorted(set(current) | {pid}) if action == "product_add" else [
            p for p in current if p != pid]
        errors, changed = _save(request, {key: new}, comment, "товары: отдельные товары")
    else:
        return
    if errors:
        _note(request, "Не сохранено: " + "; ".join(errors.values()), "err")
    else:
        _note(request, _saved_text(changed))


@staff_member_required
@tab_required(TAB)
def loyalty_products(request):
    if request.method == "POST":
        _products_post(request)
        return _back(request, "loyalty_products", request.POST.get("back") or "")

    rules = v1.exclusion_rules()
    ex_cat = set(config.get("EXCLUDED_CATEGORIES_1C"))
    na_cat = set(config.get("NO_ACCRUAL_CATEGORIES_1C"))
    cats = program.category_tree()
    names = {c["id"]: c["name"] for c in cats}
    for c in cats:
        c["redeem_on"] = c["id"] not in ex_cat
        c["accrual_on"] = c["id"] not in na_cat
        c["redeem_by"] = next((names[p] for p in c["parents"] if p in ex_cat), "")
        c["accrual_by"] = next((names[p] for p in c["parents"] if p in na_cat), "")
    ex_br = {v1._brand_key(b) for b in config.get("EXCLUDED_BRANDS")}
    na_br = {v1._brand_key(b) for b in config.get("NO_ACCRUAL_BRANDS")}
    brands = program.brand_counts()
    for b in brands:
        b["redeem_on"] = b["key"] not in ex_br
        b["accrual_on"] = b["key"] not in na_br

    def product_rows(ids):
        found = {p.pk: p for p in Product.objects.filter(pk__in=ids)}
        return [{"id": pid, "p": found.get(pid)} for pid in ids]

    q = (request.GET.get("q") or "").strip()
    results = []
    if q:
        from django.db.models import Q

        qs = Product.objects.filter(Q(name__icontains=q) | Q(article__icontains=q)
                                    | Q(id=q) | Q(brand__icontains=q)).order_by("name")[:30]
        ex_p, na_p = rules["redeem"]["products"], rules["accrual"]["products"]
        results = [{"p": p, "in_redeem": p.pk in ex_p, "in_accrual": p.pk in na_p,
                    "redeem": v1.REASON_TEXT.get(v1.redeem_reason(p, rules), ""),
                    "accrual": v1.REASON_TEXT.get(v1.accrual_reason(p, rules), "")}
                   for p in qs]
    check_raw = (request.GET.get("check") or "").strip()
    explain, check_missing = None, False
    if check_raw:
        from django.db.models import Q

        product = (Product.objects.filter(pk=check_raw).first()
                   or Product.objects.filter(Q(article=check_raw)).first()
                   or Product.objects.filter(name__icontains=check_raw).order_by("name").first())
        if product is None:
            check_missing = True
        else:
            explain = program.explain_product(product)
    totals = program.product_totals()
    reasons = [(v1.REASON_TEXT[r], totals.get(r, 0)) for r in
               ("excluded_product", "excluded_category", "excluded_brand", "markdown")
               if totals.get(r)]
    other_lists = [(k, config.SPECS[k], show(k, config.get(k))) for k in config.SPECS
                   if config.page_of(k) == "products" and k not in (
                       "EXCLUDED_CATEGORIES_1C", "NO_ACCRUAL_CATEGORIES_1C", "EXCLUDED_BRANDS",
                       "NO_ACCRUAL_BRANDS", "EXCLUDED_PRODUCTS", "NO_ACCRUAL_PRODUCTS")]
    back = request.GET.urlencode()
    return TemplateResponse(request, "admin/loyalty_program/products.html", _ctx(
        request, "loyalty_products", "Товары в программе",
        categories=cats, brands=brands, q=q, results=results, back=back,
        excluded_products=product_rows(config.get("EXCLUDED_PRODUCTS")),
        no_accrual_products=product_rows(config.get("NO_ACCRUAL_PRODUCTS")),
        check=check_raw, explain=explain, check_missing=check_missing,
        totals=totals, reasons=reasons, other_lists=other_lists,
        hard_ceiling=round(config.HARD_REDEEM_CEILING * 100),
    ))


# ── 5. Участники ─────────────────────────────────────────────────────────────

@staff_member_required
@tab_required(TAB)
def loyalty_members(request):
    if request.method == "POST":
        _need_edit(request)
        uid = (request.POST.get("uid") or "").strip()[:40]
        action = request.POST.get("action") or ""
        comment = (request.POST.get("comment") or "").strip()[:280]
        raw = (request.POST.get("amount") or "").strip().replace(" ", "")
        from accounts.models import Account

        if not Account.objects.filter(id=uid).exists():
            _note(request, "Аккаунт не найден.", "err")
            return _back(request, "loyalty_members")
        try:
            amount = int(raw)
        except ValueError:
            amount = 0
        try:
            if action == "accrue":
                v1.manual_accrue(uid, amount, comment)
                StaffAudit.write(request, f"лояльность: ручное начисление +{amount} "
                                          f"бонусов, клиент {uid}: {comment}"[:160])
                _note(request, f"Начислено {amount} бонусов. Событие — в журнале.")
            elif action == "debit":
                v1.manual_debit(uid, amount, comment)
                StaffAudit.write(request, f"лояльность: ручное списание −{amount} "
                                          f"бонусов, клиент {uid}: {comment}"[:160])
                _note(request, f"Списано {amount} бонусов. Событие — в журнале.")
        except v1.RedeemError as e:
            _note(request, f"Не выполнено: {e}", "err")
        return _back(request, "loyalty_members", f"uid={uid}")

    q = (request.GET.get("q") or "").strip()
    uid = (request.GET.get("uid") or "").strip()[:40]
    card = program.member(uid) if uid else None
    if card is not None:
        for lot in card["lots"]:
            lot.state_title = LOT_STATES.get(lot.state, lot.state)
        for ev in card["events"]:
            ev.title = EVENT_TITLES.get(ev.type, ev.type)
    found = program.find_accounts(q) if q else []
    return TemplateResponse(request, "admin/loyalty_program/members.html", _ctx(
        request, "loyalty_members", "Участники", q=q, found=found, card=card,
        journal_url=reverse("loyalty_journal"),
    ))


# ── 6. Журнал ────────────────────────────────────────────────────────────────

def _parse_date(raw):
    try:
        return datetime.strptime((raw or "").strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def _journal_qs(request):
    qs = LoyaltyEvent.objects.all().order_by("-created_at")
    f = {
        "type": (request.GET.get("type") or "").strip(),
        "date_from": request.GET.get("date_from") or "",
        "date_to": request.GET.get("date_to") or "",
        "pseudonym": (request.GET.get("pseudonym") or "").strip(),
        "uid": (request.GET.get("uid") or "").strip(),
    }
    if f["type"]:
        qs = qs.filter(type=f["type"])
    tz = timezone.get_current_timezone()
    d_from, d_to = _parse_date(f["date_from"]), _parse_date(f["date_to"])
    if d_from:
        qs = qs.filter(created_at__gte=timezone.make_aware(datetime.combine(d_from, time.min), tz))
    if d_to:
        qs = qs.filter(created_at__lt=timezone.make_aware(
            datetime.combine(d_to + timedelta(days=1), time.min), tz))
    if f["uid"] and not f["pseudonym"]:
        from accounts.models import Account

        acc = Account.objects.filter(id=f["uid"]).only("loyalty_pseudonym").first()
        f["pseudonym"] = (acc.loyalty_pseudonym if acc else "") or "—нет—"
    if f["pseudonym"]:
        qs = qs.filter(user_pseudonym=f["pseudonym"])
    return qs, f


CSV_FIELDS = ("event_id", "created_at", "user_pseudonym", "type", "amount", "balance_after",
              "status_points_after", "level_at_event", "level_after", "lot_id",
              "lot_expires_at", "source_ref", "order_total", "eligible_total", "cash_part",
              "cogs_total", "partner_id", "rule_version", "note")


@staff_member_required
@tab_required(TAB)
def loyalty_journal(request):
    qs, f = _journal_qs(request)
    if request.GET.get("export") == "csv":
        # Только псевдонимы — без телефонов и имён (журнал обезличен).
        resp = HttpResponse(content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = (
            f'attachment; filename="loyalty_events_{timezone.localdate():%Y%m%d}.csv"')
        resp.write("﻿")
        w = csv.writer(resp, delimiter=";")
        w.writerow(CSV_FIELDS)
        for ev in qs.iterator(chunk_size=2000):
            w.writerow(["" if getattr(ev, k) is None else (
                getattr(ev, k).isoformat() if hasattr(getattr(ev, k), "isoformat")
                else getattr(ev, k)) for k in CSV_FIELDS])
        StaffAudit.write(request, "лояльность: выгрузка журнала CSV")
        return resp
    page = Paginator(qs, 100).get_page(request.GET.get("page"))
    for ev in page.object_list:
        ev.title = EVENT_TITLES.get(ev.type, ev.type)
        ev.when = _local(ev.created_at)
        ev.level_title = config.LEVEL_TITLES[min(ev.level_after, 3)]
    keep = request.GET.copy()
    keep.pop("page", None)
    keep.pop("export", None)
    return TemplateResponse(request, "admin/loyalty_program/journal.html", _ctx(
        request, "loyalty_journal", "Журнал", page=page, f=f,
        types=[(t, EVENT_TITLES.get(t, t)) for t in LoyaltyEvent.TYPES],
        keep=keep.urlencode(), total=page.paginator.count,
    ))


# ── 7. История настроек ──────────────────────────────────────────────────────

def _history_rows(rows):
    out = []
    for r in rows:
        spec = config.SPECS.get(r.key)
        out.append({"when": _local(r.changed_at), "key": r.key,
                    "title": spec.title if spec else r.key,
                    "old": (f"по ТЗ ({show(r.key, spec.default)})"
                            if r.old_value is None and spec else show(r.key, r.old_value)),
                    "new": show(r.key, r.new_value),
                    "who": r.changed_by or "—", "comment": r.comment})
    return out


@staff_member_required
@tab_required(TAB)
def loyalty_history(request):
    key = (request.GET.get("key") or "").strip()
    qs = LoyaltySettingChange.objects.all()
    if key:
        qs = qs.filter(key=key)
    page = Paginator(qs, 100).get_page(request.GET.get("page"))
    return TemplateResponse(request, "admin/loyalty_program/history.html", _ctx(
        request, "loyalty_history", "История настроек", rows=_history_rows(page.object_list),
        page=page, key=key,
        keys=[(k, s.title) for k, s in config.SPECS.items()],
    ))
