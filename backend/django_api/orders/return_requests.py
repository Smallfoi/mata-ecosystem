"""Заявки покупателей на возврат (D-112, доработка D-122).

Сценарий собран по Спортмастеру, adidas, Nike, Street Beat, Lamoda, Ozon (их
онлайн-заявка + приёмка в магазине) и по закону (ЗоЗПП ст. 18, 22, 26.1; КС РФ
7-П от 17.02.2026). Сервер МАТА — первая инстанция (решение владельца 10.11.2026):
сроки и что можно вернуть решает он, человек к заявке не нужен, пока товар не
приехал.

1. Покупатель сам оформляет заявку в приложении или на сайте: какие вещи (одну из
   пяти или все), причина по каждой, фото (обязательно при браке), способ сдачи —
   принесёт в магазин или пришлёт посылкой за свой счёт (КС 7-П: отклонять посылку
   нельзя, доставка и риск в пути — на покупателе).
2. Срок вышел — сервер отказывает сразу, со ссылкой на закон и датой.
3. На передачу вещей — BRING_DAYS. Посылка: за этот срок отправить и вписать
   трек-номер; с ним заявка «в пути» и не истекает, сколько бы посылка ни ехала.
4. Сотрудник отмечает «товар получен», осматривает и решает ПО КАЖДОЙ ВЕЩИ:
   принять или отказать (причины из REJECT_REASONS + пояснение + фото осмотра).
   Отказ по заявленному браку — только по итогам проверки качества, не из-за
   ярлыков, упаковки или кода маркировки.
5. Принятые вещи — деньги существующим возвратом по строкам чека (D-73), ЮKassa
   без своего чека: чек возврата пробивает касса магазина в 1С (решение 10.11.2026).
   Отказанные вещи покупатель забирает в магазине или получает посылкой за свой счёт.
"""
import os
from datetime import timedelta

from django.db import transaction
from django.db.models import Max, Q
from django.utils import timezone

from .models import Order, ReturnPhoto, ReturnRequest
from .returns import RETURNABLE, ReturnError, make_return, return_plan

# Срок возврата вещи без брака — со дня получения (решение владельца, D-73).
# ВНИМАНИЕ (ст. 26.1 п. 4): 7 дней законны, только если памятка о возврате вручена
# письменно при доставке; иначе срок — 3 месяца.
RETURN_DAYS = 7
# Брак — в пределах двух лет (ст. 19 ЗоЗПП, если гарантийный срок не установлен).
DEFECT_DAYS = 730
# Сколько дней даётся, чтобы принести вещи или отправить посылку (и вписать трек).
BRING_DAYS = 7
# Заказ отгружен, но 1С не прислала «доставлен»: считаем, что покупатель получил
# его не раньше, чем через столько дней, — срок возврата не сгорает, пока заказ едет.
TRANSIT_DAYS = 14
# Сколько фото можно приложить к заявке (покупатель) или к осмотру (магазин).
MAX_PHOTOS = 6

REASONS = {
    "size": "Не подошёл размер",
    "style": "Не подошёл цвет или фасон",
    "defect": "Брак или дефект",
    "not_as_described": "Не соответствует описанию",
    "wrong_item": "Пришёл не тот товар",
    "other": "Другое",
}
# Причины, по которым вещь — не товар надлежащего качества: срок как у брака.
QUALITY = {"defect", "wrong_item", "not_as_described"}

# Почему магазин отказывает по вещи после осмотра. Покупатель видит текст.
REJECT_REASONS = {
    "worn": "Есть следы носки или эксплуатации",
    "no_tags": "Нет фабричных ярлыков или бирок",
    "no_marking": "Нет кода маркировки «Честный знак» или он не совпадает с проданным",
    "no_package": "Не сохранён товарный вид или упаковка",
    "incomplete": "Неполная комплектация",
    "not_ours": "Вещь не из этого заказа",
    "damaged": "Повреждения по вине покупателя",
    "not_defect": "Проверка качества: заявленный брак не подтвердился",
    "other": "Другое",
}
# По заявленному браку ярлыки, упаковка и код маркировки основанием для отказа
# не служат — только проверка качества (ст. 18 ЗоЗПП; D-112).
NOT_FOR_DEFECT = {"no_tags", "no_marking", "no_package"}
LAW_STANDARD = "ст. 26.1 Закона «О защите прав потребителей»"


class RequestError(Exception):
    """Заявку оформить/изменить нельзя — текст для покупателя или сотрудника."""

    def __init__(self, detail, status=400):
        super().__init__(detail)
        self.detail = detail
        self.status = status


def received_at(order):
    """Когда покупатель получил заказ, или None — ещё не получил.

    «Доставлен» из 1С — точная дата. Только «отгружен» — заказ в пути: даём
    TRANSIT_DAYS сверху, чтобы срок возврата не сгорел, пока посылка едет.
    Не отгружен — это не возврат, а отмена заказа (orders/cancel.py).
    """
    when = order.onec_status_at or order.created_at
    if order.onec_status == "delivered":
        return when
    if order.onec_status == "shipped":
        return when + timedelta(days=TRANSIT_DAYS)
    if order.status in ("shipped", "delivered"):
        # Статус выставлен вручную в админке (без 1С) — считаем от него.
        return when
    return None


def _windows(order, now=None):
    now = now or timezone.now()
    got = received_at(order)
    if got is None:
        return {"received": False, "standardOpen": False, "defectOpen": False,
                "standardUntil": None, "defectUntil": None}
    return {
        "received": True,
        "standardUntil": got + timedelta(days=RETURN_DAYS),
        "defectUntil": got + timedelta(days=DEFECT_DAYS),
        "standardOpen": now <= got + timedelta(days=RETURN_DAYS),
        "defectOpen": now <= got + timedelta(days=DEFECT_DAYS),
    }


def _date(dt):
    return timezone.localtime(dt).strftime("%d.%m.%Y")


def standard_note(win) -> str:
    """Пояснение под кнопкой, когда вещь без брака вернуть уже нельзя."""
    if not win["received"] or win["standardOpen"]:
        return ""
    return (f"Срок возврата вещи надлежащего качества истёк {_date(win['standardUntil'])}: "
            f"{RETURN_DAYS} дней со дня получения ({LAW_STANDARD}). Если у вещи брак — "
            "оформите возврат с причиной «Брак или дефект».")


def _busy(order):
    """Позиции, уже заявленные в активных заявках."""
    out = set()
    for req in order.return_requests.filter(status__in=ReturnRequest.ACTIVE):
        out.update(int(line["index"]) for line in req.lines)
    return out


def options(order):
    """Что из заказа можно вернуть и до какого срока — для экрана заявки."""
    from .cancel import cancel_state

    base = {"canReturn": False, "lines": [], "reasons": REASONS,
            "returnDays": RETURN_DAYS, "bringDays": BRING_DAYS,
            "maxPhotos": MAX_PHOTOS, "standardNote": "", **cancel_state(order)}
    if order.payment_status not in RETURNABLE or not order.payment_id:
        return {**base, "reason": "Вернуть можно оплаченный заказ"}
    win = _windows(order)
    if not win["received"]:
        return {**base, "reason": "Заказ ещё не получен — пока он не передан курьеру, "
                                  "его можно отменить"}
    try:
        rows = return_plan(order)
    except ReturnError as e:
        return {**base, "reason": str(e)}
    busy = _busy(order)
    lines = [{
        "index": row["index"],
        "name": row["name"],
        "paid": row["paid"] / 100,
        "available": not row["returned"] and row["index"] not in busy,
        "status": ("returned" if row["returned"] else
                   "requested" if row["index"] in busy else "available"),
    } for row in rows if row["subject"] == "commodity"]
    can = win["defectOpen"] and any(line["available"] for line in lines)
    if can:
        reason = ""
    elif not win["defectOpen"]:
        reason = (f"Срок возврата по этому заказу истёк {_date(win['defectUntil'])}: "
                  "претензию по качеству можно предъявить в течение 2 лет со дня "
                  "получения (ст. 19 Закона «О защите прав потребителей»).")
    else:
        reason = "Все вещи из заказа уже возвращены или заявлены к возврату"
    return {
        **base,
        "canReturn": can,
        "reason": reason,
        "lines": lines,
        "standardUntil": win["standardUntil"].isoformat(),
        "standardOpen": win["standardOpen"],
        "standardNote": standard_note(win),
        "defectUntil": win["defectUntil"].isoformat(),
        "store": _store_info(),
    }


def _store_info() -> dict:
    """Куда нести: способ «самовывоз» из «Магазин → Доставка» (ведёт владелец)."""
    from .models import ShippingOption

    pickup = ShippingOption.objects.filter(kind=ShippingOption.PICKUP).first()
    return {"name": pickup.name if pickup else "Магазин МАТА",
            "description": pickup.description if pickup else ""}


def _parse_lines(raw_lines, available, win):
    lines, seen = [], set()
    for raw in raw_lines:
        if not isinstance(raw, dict):
            raise RequestError("Некорректная позиция")
        try:
            index = int(raw.get("index"))
        except (TypeError, ValueError):
            raise RequestError("Некорректная позиция") from None
        if index in seen:
            continue
        seen.add(index)
        if index not in available:
            raise RequestError("Эту вещь уже вернули или по ней есть заявка", 409)
        reason = str(raw.get("reason") or "")
        if reason not in REASONS:
            raise RequestError("Укажите причину возврата")
        comment = str(raw.get("comment") or "").strip()[:500]
        if reason in ("defect", "other") and len(comment) < 5:
            raise RequestError("Опишите, что не так с вещью")
        if reason in QUALITY:
            if not win["defectOpen"]:
                raise RequestError("Срок предъявления претензии по качеству истёк")
        elif not win["standardOpen"]:
            raise RequestError(standard_note(win))
        lines.append({"index": index, "reason": reason, "comment": comment})
    return lines


# ── Фото ──────────────────────────────────────────────────────────────────────

def upload_photo(user_id, f, *, kind=ReturnPhoto.CUSTOMER, request=None):
    """Сохранить фото (без EXIF) в приватное хранилище. Бросает RequestError."""
    from common.uploads import prepare_image

    if f is None:
        raise RequestError("Приложите фото")
    if request is not None and request.photos.filter(kind=kind).count() >= MAX_PHOTOS:
        raise RequestError(f"Не больше {MAX_PHOTOS} фото")
    if request is None and user_id:
        # Загружено, но ещё не прикреплено к заявке — не даём копить без меры.
        loose = ReturnPhoto.objects.filter(user_id=user_id, request__isnull=True).count()
        if loose >= MAX_PHOTOS * 2:
            raise RequestError("Слишком много фото без заявки — отправьте заявку")
    ext, clean, error = prepare_image(f)
    if error:
        raise RequestError(error)
    photo = ReturnPhoto(user_id=str(user_id or "")[:40], kind=kind, request=request)
    photo.image.save(f"{timezone.now():%Y%m}/{photo.user_id or 'staff'}.{ext}", clean,
                     save=False)
    photo.save()
    return photo


def _attach_photos(req, user_id, photo_ids):
    ids = []
    for raw in photo_ids or []:
        try:
            ids.append(int(raw))
        except (TypeError, ValueError):
            raise RequestError("Некорректное фото") from None
    if len(ids) > MAX_PHOTOS:
        raise RequestError(f"Не больше {MAX_PHOTOS} фото")
    if not ids:
        return 0
    # Только свои и ещё ни к чему не прикреплённые — чужое фото не подцепить по номеру.
    return ReturnPhoto.objects.filter(pk__in=ids, user_id=user_id, request__isnull=True,
                                      kind=ReturnPhoto.CUSTOMER).update(request=req)


def create(order, user_id, raw_lines, method, photo_ids=None):
    """Оформить заявку покупателя. Бросает RequestError.

    `photo_ids=None` — клиент фото не поддерживает (сборки до D-122): заявку по
    браку принимаем и без снимка, иначе такие покупатели не смогли бы заявить брак.
    Новые клиенты всегда шлют список (можно пустой) — им фото брака обязательно."""
    if method not in (ReturnRequest.STORE, ReturnRequest.PARCEL):
        raise RequestError("Выберите, как сдадите товар")
    if not isinstance(raw_lines, list) or not raw_lines:
        raise RequestError("Отметьте, что возвращаете")
    with transaction.atomic():
        # Блокировка заказа: две одновременные заявки не заявят одну вещь дважды.
        order = Order.objects.select_for_update().get(pk=order.pk)
        opts = options(order)
        if not opts["lines"]:
            raise RequestError(opts["reason"] or "Этот заказ вернуть нельзя")
        available = {line["index"] for line in opts["lines"] if line["available"]}
        lines = _parse_lines(raw_lines, available, _windows(order))
        seq = (order.return_requests.aggregate(m=Max("seq"))["m"] or 0) + 1
        req = ReturnRequest.objects.create(
            order=order, user_id=user_id, lines=lines, method=method, seq=seq,
            defect_claimed=any(line["reason"] in QUALITY for line in lines),
            bring_until=timezone.now() + timedelta(days=BRING_DAYS),
        )
        attached = _attach_photos(req, user_id, photo_ids)
        needs_photo = photo_ids is not None and any(line["reason"] == "defect"
                                                     for line in lines)
        if needs_photo and not attached:
            # Исключение откатывает транзакцию: заявки без фото брака не остаётся.
            raise RequestError("Приложите хотя бы одно фото брака")
    until = timezone.localtime(req.bring_until).strftime("%d.%m")
    if method == ReturnRequest.STORE:
        how = f"принесите вещи в магазин МАТА до {until}"
    else:
        how = (f"отправьте посылку в магазин МАТА до {until} и впишите в заявке "
               "трек-номер — с ним заявка не истечёт, пока посылка едет")
    _notify(req, "Заявка на возврат принята",
            f"Заявка {req.number}: {how}. Вещи — с ярлыками и в упаковке.")
    _alert_staff(req)
    return req


def cancel(req):
    with transaction.atomic():
        req = ReturnRequest.objects.select_for_update().get(pk=req.pk)
        if req.status != ReturnRequest.AWAITING:
            raise RequestError("Заявку уже нельзя отменить: посылка отправлена или "
                               "товар получен магазином", 409)
        req.status = ReturnRequest.CANCELED
        req.save(update_fields=["status"])
    return req


def mark_sent(req, track):
    """Покупатель отправил посылку и вписал трек-номер — заявка «в пути»."""
    track = str(track or "").strip()[:64]
    if len(track) < 5:
        raise RequestError("Впишите трек-номер посылки")
    with transaction.atomic():
        req = ReturnRequest.objects.select_for_update().get(pk=req.pk)
        if req.method != ReturnRequest.PARCEL:
            raise RequestError("Трек-номер нужен только для посылки")
        if req.status not in (ReturnRequest.AWAITING, ReturnRequest.SENT):
            raise RequestError("Посылка по этой заявке уже получена или заявка закрыта", 409)
        req.track_number = track
        if req.status == ReturnRequest.AWAITING:
            req.status = ReturnRequest.SENT
            req.sent_at = timezone.now()
        req.save(update_fields=["track_number", "status", "sent_at"])
    return req


def mark_received(req, by=""):
    with transaction.atomic():
        req = ReturnRequest.objects.select_for_update().get(pk=req.pk)
        if req.status not in (ReturnRequest.AWAITING, ReturnRequest.SENT,
                              ReturnRequest.EXPIRED):
            raise RequestError("Товар по этой заявке уже принят или решение вынесено")
        req.status = ReturnRequest.RECEIVED
        req.received_at = timezone.now()
        req.save(update_fields=["status", "received_at"])
    _notify(req, "Товар получен", f"Заявка {req.number}: вещи у нас, проверяем. "
                                  "Решение сообщим в приложении и письмом.")
    return req


def _clean_decisions(req, decisions):
    """{index: {"decision": accept|reject, "reasons": [...]}} → проверенный словарь."""
    out = {}
    claimed = {int(line["index"]): line["reason"] for line in req.lines}
    for raw_index, raw in (decisions or {}).items():
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            raise RequestError("Некорректная позиция") from None
        if index not in claimed:
            raise RequestError("Этой вещи нет в заявке")
        raw = raw or {}
        decision = str(raw.get("decision") or "")
        if decision not in ("accept", "reject"):
            raise RequestError("По каждой вещи выберите: принять или отказать")
        reasons = [str(r) for r in raw.get("reasons") or []]
        if decision == "reject":
            if not reasons:
                raise RequestError("Отметьте причину отказа по каждой отклонённой вещи")
            if any(r not in REJECT_REASONS for r in reasons):
                raise RequestError("Неизвестная причина отказа")
            if claimed[index] in QUALITY and set(reasons) & NOT_FOR_DEFECT:
                raise RequestError(
                    "По заявленному браку нельзя отказать из-за ярлыков, упаковки или кода "
                    "маркировки — только по итогам проверки качества (ст. 18 ЗоЗПП)")
        out[index] = {"decision": decision,
                      "reasons": reasons if decision == "reject" else []}
    if set(out) != set(claimed):
        raise RequestError("Примите решение по каждой вещи из заявки")
    return out


def decide(req, decisions, note="", by=""):
    """Решение магазина после осмотра — по каждой вещи. Бросает RequestError.

    Принятые вещи — деньги возвратом по строкам чека (D-73); отказанные покупатель
    забирает. Всё принято — «одобрена», всё отказано — «отказ», иначе «частично».
    """
    req = ReturnRequest.objects.select_related("order").get(pk=req.pk)
    if req.status != ReturnRequest.RECEIVED:
        raise RequestError("Решение выносится после того, как товар получен и осмотрен")
    plan = _clean_decisions(req, decisions)
    note = str(note or "").strip()[:500]
    accepted = sorted(i for i, d in plan.items() if d["decision"] == "accept")
    rejected = [i for i, d in plan.items() if d["decision"] == "reject"]
    if any("other" in d["reasons"] for d in plan.values()) and len(note) < 5:
        raise RequestError("Отмечено «Другое» — поясните покупателю причину отказа")

    ret = None
    if accepted:
        try:
            ret = make_return(req.order_id, accepted, by=by)
        except ReturnError as e:
            raise RequestError(str(e)) from e

    with transaction.atomic():
        req = ReturnRequest.objects.select_for_update().get(pk=req.pk)
        req.lines = [{**line, "decision": plan[int(line["index"])]["decision"],
                      "rejectReasons": plan[int(line["index"])]["reasons"]}
                     for line in req.lines]
        req.status = (ReturnRequest.APPROVED if not rejected else
                      ReturnRequest.REJECTED if not accepted else ReturnRequest.PARTIAL)
        req.order_return = ret
        req.decision_note = note
        req.decided_at = timezone.now()
        req.decided_by = by[:150]
        req.save(update_fields=["lines", "status", "order_return", "decision_note",
                                "decided_at", "decided_by"])
    _notify_decision(req, ret)
    return req


def approve(req, by=""):
    """Принять все вещи заявки (короткий путь)."""
    req = ReturnRequest.objects.get(pk=req.pk)
    return decide(req, {line["index"]: {"decision": "accept"} for line in req.lines}, by=by)


def reject(req, note, by="", reasons=("other",)):
    """Отказать по всем вещам (короткий путь; причина — текстом покупателю)."""
    req = ReturnRequest.objects.get(pk=req.pk)
    note = str(note or "").strip()
    if len(note) < 5:
        raise RequestError("Напишите покупателю причину отказа")
    return decide(req, {line["index"]: {"decision": "reject", "reasons": list(reasons)}
                        for line in req.lines}, note=note, by=by)


def _reject_text(req) -> str:
    names = _names(req.order)
    parts = []
    for line in req.rejected_lines():
        why = "; ".join(REJECT_REASONS.get(r, r) for r in line.get("rejectReasons") or [])
        parts.append(f"{names.get(int(line['index']), 'вещь')} — {why}")
    return ". ".join(parts)


def _notify_decision(req, ret):
    back = ("Вещи, по которым отказано, можно забрать в магазине МАТА или получить "
            "посылкой за свой счёт — выберите в заявке.")
    note = f" Комментарий магазина: {req.decision_note}" if req.decision_note else ""
    money = ""
    if ret is not None:
        money = (f"вернём {ret.amount_kop / 100:.2f} ₽ тем же способом, которым платили, — "
                 "обычно за 1–3 дня, по закону до 10 дней.")
        if req.defect_confirmed and req.customer_shipping_kop:
            money += (f" Расходы на доставку {req.customer_shipping_kop / 100:.2f} ₽ "
                      "компенсируем отдельно.")
    if req.status == ReturnRequest.APPROVED:
        _notify(req, "Возврат одобрен", f"Заявка {req.number} одобрена: {money}{note}")
    elif req.status == ReturnRequest.REJECTED:
        _notify(req, "В возврате отказано",
                f"Заявка {req.number}: {_reject_text(req)}.{note} {back}")
    else:
        _notify(req, "Возврат одобрен частично",
                f"Заявка {req.number}: {money} Отказано: {_reject_text(req)}.{note} {back}")


def choose_goods_back(req, way):
    """Покупатель выбирает, как забрать вещи, по которым отказано."""
    if way not in (ReturnRequest.BACK_PICKUP, ReturnRequest.BACK_SHIP):
        raise RequestError("Выберите: заберёте в магазине или отправить посылкой")
    with transaction.atomic():
        req = ReturnRequest.objects.select_for_update().get(pk=req.pk)
        if req.status not in (ReturnRequest.REJECTED, ReturnRequest.PARTIAL):
            raise RequestError("По этой заявке нет вещей к выдаче", 409)
        if req.goods_back_done:
            raise RequestError("Вещи уже выданы или отправлены", 409)
        req.goods_back = way
        req.save(update_fields=["goods_back"])
    _alert_staff(req, goods_back=True)
    return req


def mark_goods_back_done(req, by=""):
    with transaction.atomic():
        req = ReturnRequest.objects.select_for_update().get(pk=req.pk)
        if req.status not in (ReturnRequest.REJECTED, ReturnRequest.PARTIAL):
            raise RequestError("По этой заявке нет вещей к выдаче")
        req.goods_back_done = True
        req.save(update_fields=["goods_back_done"])
    return req


def expire_stale(now=None):
    """Заявки, по которым товар так и не сдали, — в «истекла» (beat).

    Посылка с трек-номером («в пути») не истекает: срок соблюдён в день отправки.
    Заодно убираем фото, загруженные к так и не отправленной заявке."""
    now = now or timezone.now()
    stale = list(ReturnRequest.objects.select_related("order").filter(
        status=ReturnRequest.AWAITING, bring_until__lt=now))
    for req in stale:
        req.status = ReturnRequest.EXPIRED
        req.save(update_fields=["status"])
        _notify(req, "Заявка на возврат истекла",
                f"Заявка {req.number}: товар не сдан в срок. Если срок возврата ещё "
                "не прошёл, оформите новую заявку.")
    # Файл удаляет сигнал post_delete (orders/models.py).
    ReturnPhoto.objects.filter(request__isnull=True,
                               created_at__lt=now - timedelta(days=1)).delete()
    return len(stale)


def needs_attention() -> int:
    """Сколько заявок ждут магазин: вещи несут/едут, на осмотре, к выдаче обратно."""
    return ReturnRequest.objects.filter(
        Q(status__in=ReturnRequest.ACTIVE)
        | Q(status__in=(ReturnRequest.REJECTED, ReturnRequest.PARTIAL),
            goods_back_done=False)).count()


def sidebar_badge(request):
    """Счётчик у пункта «Заявки на возврат» в меню админки; ноль — без значка."""
    try:
        n = needs_attention()
    except Exception:  # меню не должно падать из-за счётчика
        return None
    return n or None


def _names(order) -> dict:
    try:
        return {row["index"]: row["name"] for row in return_plan(order)}
    except ReturnError:
        return {}


def photo_urls(req, kind=ReturnPhoto.CUSTOMER) -> list:
    out = []
    for photo in req.photos.filter(kind=kind):
        try:
            out.append({"id": photo.pk, "url": photo.image.url})
        except Exception:  # хранилище недоступно — заявку всё равно показываем
            continue
    return out


def to_json(req) -> dict:
    names = _names(req.order)
    lines = [{
        **line,
        "name": names.get(int(line["index"]), ""),
        "reasonLabel": REASONS.get(line.get("reason"), ""),
        "rejectReasonLabels": [REJECT_REASONS.get(r, r) for r in line.get("rejectReasons") or []],
    } for line in req.lines]
    decided = req.status in ReturnRequest.DECIDED
    return {
        "id": req.pk,
        "number": req.number,
        "orderId": req.order.order_id,
        "status": req.status,
        "statusLabel": req.get_status_display(),
        "method": req.method,
        "lines": lines,
        "bringUntil": req.bring_until.isoformat(),
        "trackNumber": req.track_number,
        "canCancel": req.status == ReturnRequest.AWAITING,
        "needsTrack": (req.method == ReturnRequest.PARCEL
                       and req.status in (ReturnRequest.AWAITING, ReturnRequest.SENT)),
        "decisionNote": req.decision_note,
        "goodsBack": req.goods_back,
        "goodsBackDone": req.goods_back_done,
        "needsGoodsBack": (req.status in (ReturnRequest.REJECTED, ReturnRequest.PARTIAL)
                           and not req.goods_back and not req.goods_back_done),
        "refundRub": (req.order_return.amount_kop / 100) if req.order_return else None,
        "photos": photo_urls(req),
        "inspectionPhotos": photo_urls(req, ReturnPhoto.INSPECTION) if decided else [],
        "createdAt": req.created_at.isoformat(),
    }


def _notify(req, title, body):
    try:
        from notifications.email import recipient_for
        from notifications.models import create_notification

        # Ход возврата — и письмом (D-111): покупатель хранит его как документ.
        create_notification(req.user_id, title, body, "order", req.order.order_id,
                            email_to=recipient_for(req.user_id, req.order))
    except Exception:
        # Уведомление — не часть заявки: решение уже записано.
        pass


def staff_recipients() -> list:
    """Кому из магазина писать о заявках: RETURNS_ALERT_EMAILS, иначе — всем
    действующим сотрудникам с доступом к вкладке «Заказы» и адресом почты."""
    from notifications.email import real_address

    listed = [real_address(a) for a in (os.environ.get("RETURNS_ALERT_EMAILS") or "").split(",")]
    listed = [a for a in listed if a]
    if listed:
        return listed
    from django.contrib.auth import get_user_model

    from staff.access import can

    out = {real_address(u.email) for u in
           get_user_model().objects.filter(is_active=True, is_staff=True)
           if can(u, "orders")}
    return sorted(a for a in out if a)


def _alert_staff(req, *, goods_back=False):
    """Письмо в магазин: новая заявка (товар скоро привезут) или выбор покупателя."""
    try:
        from notifications.email import send_email

        names = _names(req.order)
        items = "\n".join(
            f"— {names.get(int(line['index']), 'позиция ' + str(line['index']))}: "
            f"{REASONS.get(line['reason'], line['reason'])}"
            + (f" ({line['comment']})" if line.get("comment") else "")
            for line in req.lines)
        if goods_back:
            subject = f"Возврат {req.number}: покупатель выбрал, как забрать вещи"
            text = (f"По заявке {req.number} (заказ {req.order.order_id}) покупатель "
                    f"выбрал: {req.get_goods_back_display()}.\n\n{items}")
        else:
            subject = f"Новая заявка на возврат {req.number}"
            text = (f"Заказ {req.order.order_id}. Покупатель "
                    f"{req.get_method_display().lower()} до {_date(req.bring_until)}.\n\n"
                    f"{items}\n\nЗаявка — в админке: Заказы → Заявки на возврат.")
        for to in staff_recipients():
            send_email(to, subject, text)
    except Exception:
        # Письмо магазину — подсказка, не часть заявки: она уже записана.
        pass
