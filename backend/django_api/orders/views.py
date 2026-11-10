"""Заказы Store (D-13). POST — сохранить заказ пользователя (идемпотентно по id),
GET — список заказов пользователя (новые сверху). Требуется Bearer-токен."""
from decimal import Decimal

from django.db import transaction
from rest_framework.decorators import api_view
from rest_framework.response import Response

from common.security import user_id_from_request

from .awards import redeem_for_order
from .lifecycle import AWAITING, apply_payment_info, mark_paid, payment_started
from .models import Order
from .money import kop_to_float, kop_to_rub, to_kop
from .money import money
from .pricing import (
    CartError,
    normalize_items,
    parse_quantity,
    redeemed_rub,
    total_is_acceptable,
)
from . import shipping
from .payment import (
    PaymentError,
    create_payment,
    fetch_payment,
    payment_enabled,
    payment_reference,
)
from .receipt import build_receipt

# Расхождение клиентской суммы с серверной, которое ещё считаем округлением.
_TOLERANCE = Decimal("1")

# Что из ответа провайдера отдаём клиентам — прежний контракт, без служебных полей
# сверки (сумма/валюта/reference).
_PAY_FIELDS = ("status", "paymentId", "confirmationUrl", "method")


def _kop(value):
    try:
        return to_kop(value)
    except ValueError:
        return str(value)


def _billable(payload, total, points) -> tuple:
    """Всё, за что берём деньги: сумма, баллы и позиции (товар, размер, цвет,
    количество, цена) в исходном порядке — по нему строятся строки чека.

    Имя товара, картинка, контакты сюда не входят: от них сумма не зависит.
    """
    items = []
    raw = (payload or {}).get("items") if isinstance(payload, dict) else None
    for it in raw or []:
        if not isinstance(it, dict):
            items.append(repr(it))
            continue
        try:
            qty = int(it.get("quantity") or 1)
        except (TypeError, ValueError):
            qty = str(it.get("quantity"))
        items.append((
            str(it.get("productId") or ""), str(it.get("size") or ""),
            str(it.get("color") or ""), qty, _kop(it.get("price")),
        ))
    try:
        points = int(points or 0)
    except (TypeError, ValueError):
        points = str(points)
    return (_kop(total), points, tuple(items))


def _order_billable(order) -> tuple:
    return _billable(order.payload, kop_to_rub(order.amount_kop), order.points_redeemed)


def _qty_key(raw):
    try:
        return parse_quantity(raw)
    except CartError:
        return str(raw)


def _shape(payload, total, points) -> tuple:
    """Что покупатель заказал: сумма, баллы и строки (товар, размер, цвет, количество).

    Для повтора уже оплачиваемого заказа (аудит B01). Цену строки не сравниваем:
    её берёт сервер из каталога (аудит B09), а ретрай офлайн-очереди шлёт
    клиентскую — это тот же заказ, а не попытка его изменить.
    """
    total_kop, points, items = _billable(payload, total, points)
    raw = (payload or {}).get("items") if isinstance(payload, dict) else None
    lines = []
    for it, line in zip(raw or [], items):
        if isinstance(line, tuple):
            line = line[:3] + (_qty_key(it.get("quantity")),)
        lines.append(line)
    return (total_kop, points, tuple(lines))


def _order_shape(order) -> tuple:
    return _shape(order.payload, kop_to_rub(order.amount_kop), order.points_redeemed)


def _test_payer(uid: str) -> bool:
    """Разрешена ли этому аккаунту оплата без денег (D-97)."""
    from accounts.models import Account

    return Account.objects.filter(id=uid, test_payment=True).exists()


@api_view(["POST"])
def pay_order(request, order_id):
    """Инициировать оплату заказа (D-13). Dev (без провайдера) — сразу «оплачено»;
    с ЮKassa — вернуть confirmationUrl для редиректа покупателя на страницу оплаты."""
    uid = user_id_from_request(request)
    if not uid:
        return Response({"detail": "Нет токена"}, status=401)
    order = Order.objects.filter(user_id=uid, order_id=order_id).first()
    if not order:
        return Response({"detail": "Заказ не найден"}, status=404)
    if order.payment_status == "paid":
        # Уже оплачен — второй платёж не создаём.
        return Response({"status": "paid", "paymentId": order.payment_id,
                         "confirmationUrl": ""})
    if order.payment_status in ("canceled", "refunded", "partially_refunded"):
        return Response(
            {"detail": "Время на оплату истекло — оформите заказ заново"}, status=409
        )

    # Тестовая оплата: аккаунту с этим правом «платим» без денег, чтобы пройти
    # весь путь — заказ, выгрузка в 1С, статусы. Нужно для проверки обмена со
    # стороны 1С (D-97). Заказ помечается тестовым: и у нас, и в выгрузке.
    if _test_payer(uid):
        order.is_test = True
        order.payment_id = f"TEST-{order.order_id}"
        order.payment_status = "pending"
        order.save(update_fields=["is_test", "payment_id", "payment_status"])
        mark_paid(order)
        order.refresh_from_db()
        return Response({
            "status": "paid",
            "paymentId": order.payment_id,
            "confirmationUrl": "",
            "test": True,
            "note": "Тестовая оплата: деньги не списаны, заказ уйдёт в 1С с пометкой «тест».",
        })
    # Снимок того, что уходит в оплату: за время запроса к провайдеру заказ не
    # должен поменяться (аудит B01) — проверим после ответа.
    snapshot = _order_billable(order)
    try:
        # Сумма платежа и чек — из одних и тех же копеек (аудит B09): сумма строк
        # чека обязана совпасть с платежом до копейки.
        amount = kop_to_rub(order.amount_kop)
        receipt = build_receipt(order.payload, amount)
    except ValueError as e:
        # Фискализация включена, а чек собрать не из чего. Платить без чека нельзя:
        # это нарушение 54-ФЗ, и касса всё равно откажет.
        return Response({"detail": f"Не удалось собрать чек: {e}"}, status=400)
    try:
        result = create_payment(
            order_id,
            amount,
            request.data.get("returnUrl") or "",
            # Номер заказа уникален только в паре с пользователем, провайдеру нужен
            # глобально уникальный — иначе два покупателя с одинаковым SS-… и равной
            # суммой получат один платёж на двоих (см. orders/payment.py).
            reference=payment_reference(order),
            receipt=receipt,
        )
    except PaymentError as e:
        # Провайдер отказал/недоступен — НЕ трогаем статус заказа. Отдать «оплачено»
        # или молча «pending» с пустой ссылкой значит потерять покупателя и деньги.
        return Response({"detail": f"Оплата недоступна: {e}"}, status=502)
    if not payment_enabled():
        # Разработка без провайдера (create_payment вернул «оплачено» сам): сверять
        # не с чем — ни суммы, ни номера платежа нет.
        mark_paid(order)
        return Response({k: result[k] for k in _PAY_FIELDS if k in result})

    with transaction.atomic():
        locked = Order.objects.select_for_update().get(pk=order.pk)
        if _order_billable(locked) != snapshot:
            # Заказ переоформили, пока создавался платёж. Этот платёж не привязываем
            # и ссылку не отдаём — без оплаты он истечёт у провайдера сам.
            return Response(
                {"detail": "Заказ изменился во время оплаты — повторите оплату"},
                status=409,
            )
        if locked.payment_status not in AWAITING:
            # Параллельно пришёл окончательный исход (оплачен/отменён) — не затираем.
            if locked.payment_status == "paid":
                return Response({"status": "paid", "paymentId": locked.payment_id,
                                 "confirmationUrl": ""})
            return Response(
                {"detail": "Время на оплату истекло — оформите заказ заново"}, status=409
            )
        locked.payment_status = "pending"
        locked.payment_id = result.get("paymentId") or ""
        locked.save(update_fields=["payment_status", "payment_id"])
    # Провайдер мог сразу ответить «оплачен» или «отменён» — тот же путь, что у
    # вебхука: «оплачено» только при совпадении суммы, валюты и reference.
    apply_payment_info(locked, result)
    out = {k: result[k] for k in _PAY_FIELDS if k in result}
    out["status"] = locked.payment_status
    return Response(out)


@api_view(["GET"])
def payment_state(request, order_id):
    """Статус оплаты заказа — с перепроверкой у провайдера.

    Нужен по двум причинам. Первая: вебхук может не дойти (сеть, наш деплой,
    5xx) — тогда без этого запроса заказ навсегда останется «ждёт оплаты», хотя
    деньги списаны. Вторая: покупатель возвращается со страницы оплаты в
    приложение и хочет видеть результат сразу, а не «когда-нибудь придёт».
    """
    uid = user_id_from_request(request)
    if not uid:
        return Response({"detail": "Нет токена"}, status=401)
    order = Order.objects.filter(user_id=uid, order_id=order_id).first()
    if not order:
        return Response({"detail": "Заказ не найден"}, status=404)

    # Спрашиваем провайдера, только пока исход неизвестен: у оплаченного и
    # отменённого заказа статус уже окончательный.
    if order.payment_id and order.payment_status == "pending":
        try:
            info = fetch_payment(order.payment_id)
        except PaymentError:
            # Провайдер недоступен — отдаём, что знаем; это не ошибка заказа.
            info = None
        if info:
            apply_payment_info(order, info)
    order.refresh_from_db()
    return Response({
        "orderId": order.order_id,
        "status": order.payment_status,
        "paymentId": order.payment_id,
    })


@api_view(["POST"])
def payment_webhook(request):
    """Уведомление ЮKassa об изменении статуса платежа.

    Эндпоинт публичный (адрес прописывается в личном кабинете ЮKassa), а тело
    уведомления НЕ подписано — поэтому телу не верим: берём из него только id
    платежа и перезапрашиваем настоящий статус по API своими ключами. Подделать
    уведомление и «оплатить» заказ бесплатно так нельзя.
    """
    obj = (request.data or {}).get("object") or {}
    event = str((request.data or {}).get("event") or "")
    if event.startswith("refund.") or "payment_id" in obj:
        # Уведомление о ВОЗВРАТЕ (у объекта возврата есть payment_id, у платежа —
        # нет). Его id — номер возврата, не платежа: спрашивать о нём как о
        # платеже бессмысленно (аудит B04).
        return _refund_webhook(obj)
    payment_id = str(obj.get("id") or "").strip()
    if not payment_id:
        return Response({"detail": "Нет id платежа"}, status=400)

    try:
        info = fetch_payment(payment_id)
    except PaymentError as e:
        # Не подтвердили статус — отвечаем ошибкой, ЮKassa повторит доставку позже.
        return Response({"detail": str(e)}, status=502)

    order = Order.objects.filter(payment_id=payment_id).first()
    if not order:
        # Незнакомый платёж: возможна гонка с сохранением payment_id — пусть повторит.
        return Response({"detail": "Заказ по платежу не найден"}, status=404)

    problem = apply_payment_info(order, info)
    if problem:
        # Платёж не совпал с заказом — «оплачено» не ставим. Отвечаем 200: повтор
        # доставки ничего не изменит, а расхождение уже в логе ошибок.
        return Response({"ok": False, "detail": problem, "status": order.payment_status})
    return Response({"ok": True, "status": order.payment_status})


def _refund_webhook(obj):
    """Уведомление ЮKassa о возврате: статус берём из API, не из тела."""
    import logging

    from .payment import fetch_refund
    from .returns import apply_refund_info

    refund_id = str(obj.get("id") or "").strip()
    if not refund_id:
        return Response({"detail": "Нет id возврата"}, status=400)
    try:
        info = fetch_refund(refund_id)
    except PaymentError as e:
        return Response({"detail": str(e)}, status=502)  # ЮKassa повторит позже
    ret = apply_refund_info(info)
    if ret is None:
        # Возврат сделан не через нас (например, в личном кабинете ЮKassa).
        # Повтор доставки ничего не изменит — отвечаем 200 и оставляем след в логе.
        logging.getLogger(__name__).warning(
            "Уведомление о чужом возврате %s (платёж %s)", refund_id, info.get("paymentId"))
        return Response({"ok": False, "detail": "Возврат не найден"})
    return Response({"ok": True, "status": ret.status})


@api_view(["GET", "POST"])
def orders(request):
    uid = user_id_from_request(request)
    if not uid:
        return Response({"detail": "Нет токена"}, status=401)

    if request.method == "POST":
        d = request.data
        oid = str(d.get("id") or "").strip()
        if not oid:
            return Response({"detail": "Нет id заказа"}, status=400)
        try:
            total_kop = to_kop(d.get("total"))
            total = kop_to_float(total_kop)  # float-зеркало для старых полей/API
        except ValueError:
            return Response({"detail": "Некорректная сумма заказа"}, status=400)
        try:
            points = max(0, int(d.get("pointsRedeemed") or 0))
        except (TypeError, ValueError):
            points = 0

        with transaction.atomic():
            # Блокируем заказ: иначе переоформление могло бы проскочить между
            # созданием платежа и сохранением его номера (аудит B01).
            already = (
                Order.objects.select_for_update().filter(user_id=uid, order_id=oid).first()
            )
            if already and payment_started(already):
                # Оплата начата — заказ заморожен. Повтор того же заказа (ретрай,
                # офлайн-очередь) идемпотентен: отдаём, что есть, ничего не меняя —
                # ни суммы, ни состава, ни статуса. Другой состав или сумма — отказ:
                # платёж и чек уже построены по прежнему заказу.
                if _shape(d, total, points) != _order_shape(already):
                    return Response(
                        {"detail": "Заказ уже передан в оплату — изменить его нельзя. "
                                   "Оформите новый заказ."},
                        status=409,
                    )
                return Response(already.to_json())

            # Строки заказа собирает сервер по каталогу (аудит B09): товар продаётся
            # и есть в наличии, размер и цвет существуют, количество в пределах,
            # цена и название — из каталога. По этому снимку строятся чек и 1С.
            # Приём оплаты включён — позиции не из каталога не принимаем (D-37, D-72):
            # такой заказ оплатили бы хоть рублём.
            try:
                # Под блокировкой строк товаров и с учётом резерва неоплаченных
                # заказов: последнюю вещь не оформят двое сразу.
                cart = normalize_items(d.get("items"), strict=payment_enabled(),
                                       lock=True, exclude=(uid, oid))
            except CartError as e:
                return Response(e.body(), status=e.status)

            # Способ получения и цену доставки знает сервер (D-110): клиент шлёт
            # только код способа, его `deliveryCost` больше не учитывается.
            checkout = d.get("checkoutData") if isinstance(d.get("checkoutData"), dict) else {}
            try:
                option = shipping.resolve(checkout.get("deliveryType"))
                # Курьеру нужен адрес, самовывозу — нет: лишний адрес убираем.
                checkout = shipping.checkout_for(option, checkout)
            except shipping.ShippingError as e:
                return Response({"detail": e.detail}, status=e.status)
            delivery = shipping.cost(option, cart.goods)

            if already and points != already.points_redeemed:
                # Баллы списаны при первом оформлении ровно на прежнее число.
                # Записать в заказ новое, не списав его, нельзя: заказ и реестр
                # баллов разойдутся (скидка без списания или списание без скидки).
                return Response(
                    {"detail": "Списание баллов по этому заказу уже проведено — "
                               "изменить его нельзя. Оформите новый заказ."},
                    status=409,
                )
            # Баллы списывает сервер при оформлении (D-72) — до сверки суммы: скидка
            # законно снижает порог, но только реально списанная. Не сошлось —
            # откатываем и списание.
            if not already:
                # Доля баллов считается от суммы до скидки: товары и доставка.
                order_sum = (float(cart.goods + delivery) if cart.verified
                             else float(kop_to_rub(total_kop) + points))
                problem = redeem_for_order(uid, oid, points, order_sum, items=cart.items)
                if problem:
                    return Response({"detail": problem}, status=400)
            # Итог считает сервер (D-110): товары по каталогу + доставка по способу −
            # реально списанные баллы. В оплату идёт ИМЕННО он, а не сумма клиента.
            # Отказ — только если клиент показал покупателю меньше, чем мы спишем
            # (новая платная доставка, выросшая цена): брать больше показанного нельзя.
            # Показал больше (старая цена в корзине) — спишем меньше, покупателю не
            # во вред, а старые сборки не ломаются. Заказ из позиций не из каталога
            # (оплата выключена, dev) сверяем по-старому — как минимум.
            if cart.verified:
                expected = max(Decimal(0), cart.goods + delivery - redeemed_rub(uid, oid))
                if money(kop_to_rub(total_kop)) < expected - _TOLERANCE:
                    transaction.set_rollback(True)
                    return Response({
                        "detail": "Сумма заказа не совпадает с ценами каталога — "
                                  "обновите корзину",
                        "expectedTotal": float(expected),
                        "deliveryCost": float(delivery),
                    }, status=400)
                total_kop = to_kop(expected)
                total = kop_to_float(total_kop)
            elif not total_is_acceptable(kop_to_rub(total_kop), cart, uid, oid):
                transaction.set_rollback(True)
                return Response(
                    {"detail": "Сумма заказа не совпадает с ценами каталога"}, status=400
                )
            payload = {**d, "checkoutData": checkout, "items": cart.items,
                       "deliveryCost": float(delivery),
                       "deliveryOption": {"code": option.code, "name": option.name}}
            if cart.verified:
                # Сумма товаров по ценам каталога — та же, что в строках.
                payload["subtotal"] = float(cart.goods)
                payload["total"] = total
            fields = {
                # Двойная запись: копейки — для расчётов, float — старым клиентам.
                "total": total,
                "total_kop": total_kop,
                "points_redeemed": points,
                "payload": payload,
            }
            obj, created = Order.objects.update_or_create(
                user_id=uid,
                order_id=oid,
                defaults=fields,
                # Любой заказ рождается «ждёт оплату» (D-72): «оплата не требуется»
                # не бывает. Статусы заказа и оплаты ведёт только сервер (оплата,
                # 1С, админка), клиент их не задаёт: иначе повторная отправка
                # вернула бы оплаченному или отгруженному заказу «принят».
                # Баллы за покупку — только после подтверждённой оплаты (lifecycle).
                create_defaults={**fields, "status": "pending",
                                 "payment_status": "pending"},
            )
        # Связка экосистемы: для каждой пары обуви в заказе заводим ресурс
        # «износа кроссовок» (Квартал затем убавляет километраж). Идемпотентно.
        from shoes.views import create_for_order

        create_for_order(uid, oid, cart.items)
        if created:
            # Аналитика (D-30): покупка (только на создании — повтор POST не задваивает).
            from analytics.models import E_PURCHASE, track

            track(E_PURCHASE, user_id=uid, source="store", total=total, orderId=oid)
        return Response(obj.to_json())

    # GET — заказы текущего пользователя
    rows = Order.objects.filter(user_id=uid).order_by("-created_at")[
        :200
    ]  # последние заказы (детерминированный срез, ограничение payload)
    return Response([o.to_json() for o in rows])


@api_view(["GET"])
def shipping_options(request):
    """Способы получения заказа (D-110) — публично, как каталог.

    `?goods=<сумма товаров>` — посчитать цену доставки с учётом «бесплатно от».
    """
    goods = request.query_params.get("goods")
    try:
        goods = money(goods) if goods not in (None, "") else None
    except (ArithmeticError, ValueError, TypeError):
        return Response({"detail": "Некорректная сумма товаров"}, status=400)
    return Response({"options": [shipping.to_json(o, goods) for o in shipping.active_options()]})


def _my_order(request, order_id):
    """(uid, заказ) текущего пользователя или (uid, None)."""
    uid = user_id_from_request(request)
    if not uid:
        return None, None
    return uid, Order.objects.filter(user_id=uid, order_id=order_id).first()


@api_view(["GET"])
def return_options(request, order_id):
    """Что из заказа можно вернуть, причины, сроки и адрес магазина (D-112)."""
    from .return_requests import options

    uid, order = _my_order(request, order_id)
    if not uid:
        return Response({"detail": "Нет токена"}, status=401)
    if not order:
        return Response({"detail": "Заказ не найден"}, status=404)
    return Response(options(order))


@api_view(["GET", "POST"])
def order_return_requests(request, order_id):
    """Заявки на возврат по заказу: GET — список, POST — оформить новую (D-112)."""
    from . import return_requests as rr

    uid, order = _my_order(request, order_id)
    if not uid:
        return Response({"detail": "Нет токена"}, status=401)
    if not order:
        return Response({"detail": "Заказ не найден"}, status=404)
    if request.method == "POST":
        try:
            req = rr.create(order, uid, request.data.get("lines"),
                            str(request.data.get("method") or ""))
        except rr.RequestError as e:
            return Response({"detail": e.detail}, status=e.status)
        return Response(rr.to_json(req), status=201)
    return Response([rr.to_json(r) for r in order.return_requests.all()])


@api_view(["GET"])
def my_return_requests(request):
    """Все заявки на возврат текущего пользователя (D-112)."""
    from .models import ReturnRequest
    from .return_requests import to_json

    uid = user_id_from_request(request)
    if not uid:
        return Response({"detail": "Нет токена"}, status=401)
    rows = ReturnRequest.objects.select_related("order", "order_return").filter(
        user_id=uid)[:100]
    return Response([to_json(r) for r in rows])


@api_view(["POST"])
def cancel_return_request(request, pk):
    """Покупатель передумал — пока товар не сдан (D-112)."""
    from . import return_requests as rr
    from .models import ReturnRequest

    uid = user_id_from_request(request)
    if not uid:
        return Response({"detail": "Нет токена"}, status=401)
    req = ReturnRequest.objects.filter(pk=pk, user_id=uid).first()
    if not req:
        return Response({"detail": "Заявка не найдена"}, status=404)
    try:
        req = rr.cancel(req)
    except rr.RequestError as e:
        return Response({"detail": e.detail}, status=e.status)
    return Response(rr.to_json(req))
