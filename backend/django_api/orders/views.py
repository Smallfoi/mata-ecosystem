"""Заказы Store (D-13). POST — сохранить заказ пользователя (идемпотентно по id),
GET — список заказов пользователя (новые сверху). Требуется Bearer-токен."""
from django.db import transaction
from rest_framework.decorators import api_view
from rest_framework.response import Response

from common.security import user_id_from_request

from .awards import redeem_for_order
from .lifecycle import mark_canceled, mark_paid
from .models import Order
from .pricing import all_items_known, total_is_acceptable
from .payment import PaymentError, create_payment, fetch_payment, payment_enabled
from .receipt import build_receipt


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
    if order.payment_status in ("canceled", "refunded"):
        return Response(
            {"detail": "Время на оплату истекло — оформите заказ заново"}, status=409
        )
    try:
        receipt = build_receipt(order.payload, order.total)
    except ValueError as e:
        # Фискализация включена, а чек собрать не из чего. Платить без чека нельзя:
        # это нарушение 54-ФЗ, и касса всё равно откажет.
        return Response({"detail": f"Не удалось собрать чек: {e}"}, status=400)
    try:
        result = create_payment(
            order_id,
            order.total,
            request.data.get("returnUrl") or "",
            # Номер заказа уникален только в паре с пользователем, провайдеру нужен
            # глобально уникальный — иначе два покупателя с одинаковым SS-… и равной
            # суммой получат один платёж на двоих (см. orders/payment.py).
            reference=f"{order.order_id}-{order.pk}",
            receipt=receipt,
        )
    except PaymentError as e:
        # Провайдер отказал/недоступен — НЕ трогаем статус заказа. Отдать «оплачено»
        # или молча «pending» с пустой ссылкой значит потерять покупателя и деньги.
        return Response({"detail": f"Оплата недоступна: {e}"}, status=502)
    order.payment_status = result["status"]
    order.payment_id = result.get("paymentId") or ""
    order.save(update_fields=["payment_status", "payment_id"])
    if result["status"] == "paid":
        order.refresh_from_db()
        mark_paid(order)
    return Response(result)


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
        if info and info["status"] == "paid":
            mark_paid(order)
        elif info and info["status"] == "canceled":
            mark_canceled(order)
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

    if info["status"] == "paid":
        mark_paid(order)
    elif info["status"] == "canceled":
        mark_canceled(order)
    return Response({"ok": True, "status": order.payment_status})


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
        total = float(d.get("total") or 0)
        try:
            points = max(0, int(d.get("pointsRedeemed") or 0))
        except (TypeError, ValueError):
            points = 0
        items = d.get("items")
        # Приём оплаты включён — сумму обязаны сверить с каталогом (D-37, D-72).
        # Позиции не из каталога сверить нельзя: такой заказ оплатили бы хоть рублём.
        if payment_enabled() and not all_items_known(items):
            return Response(
                {"detail": "Не удалось сверить заказ с каталогом"}, status=400
            )
        already = Order.objects.filter(user_id=uid, order_id=oid).first()

        with transaction.atomic():
            # Баллы списывает сервер при оформлении (D-72) — до сверки суммы: скидка
            # законно снижает порог, но только реально списанная. Не сошлось —
            # откатываем и списание.
            if not already:
                problem = redeem_for_order(uid, oid, points, total + points)
                if problem:
                    return Response({"detail": problem}, status=400)
            # Сумму присылает клиент — сверяем её с ценами каталога (D-37). Иначе
            # корзину на 50 000 ₽ можно оформить с total: 1 и заплатить рубль.
            if not total_is_acceptable(total, items, uid, oid):
                transaction.set_rollback(True)
                return Response(
                    {"detail": "Сумма заказа не совпадает с ценами каталога"}, status=400
                )
            # Оплаченный заказ переоформить нельзя — иначе сумму меняют задним числом.
            if already and already.payment_status == "paid" and float(already.total) != total:
                transaction.set_rollback(True)
                return Response({"detail": "Заказ уже оплачен"}, status=409)
            fields = {
                "total": total,
                "status": (d.get("status") or "pending"),
                "points_redeemed": points,
                "payload": d,
            }
            obj, created = Order.objects.update_or_create(
                user_id=uid,
                order_id=oid,
                defaults=fields,
                # Любой заказ рождается «ждёт оплату» (D-72): «оплата не требуется»
                # не бывает. Статус оплаты — только при создании: повторная отправка
                # (ретрай, офлайн-очередь) не вернёт оплаченному «ждёт оплату».
                # Баллы за покупку — только после подтверждённой оплаты (lifecycle).
                create_defaults={**fields, "payment_status": "pending"},
            )
        # Связка экосистемы: для каждой пары обуви в заказе заводим ресурс
        # «износа кроссовок» (Квартал затем убавляет километраж). Идемпотентно.
        from shoes.views import create_for_order

        create_for_order(uid, oid, d.get("items") or [])
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
