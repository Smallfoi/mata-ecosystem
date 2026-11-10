import 'dart:async';
import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:sentry_flutter/sentry_flutter.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../data/repositories/order_repository.dart';
import '../data/shipping_rates.dart';
import '../models/app_notification.dart';
import '../models/cart_item.dart';
import '../models/order.dart';
import 'notifications_provider.dart';

class OrderProvider extends ChangeNotifier {
  final SharedPreferences _prefs;
  final OrderRepository _repo;

  /// true → история заказов синхронизируется с общим backend (по JWT).
  final bool serverBacked;

  /// Имитация доставки таймерами (статусы «комплектуется → в доставке →
  /// доставлен» сами по себе). ТОЛЬКО для mock-режима без backend: у реального
  /// заказа статус меняет лишь сервер (аудит B07).
  final bool simulateDelivery;

  /// Старый общий ключ истории (до аудита C03) — один на всё устройство, из-за
  /// чего заказы прошлого аккаунта были видны следующему. Больше не читается.
  static const legacyKey = 'orders';

  /// История хранится отдельно для каждого аккаунта: `orders.<scope>`.
  static const keyPrefix = 'orders.';
  static const _guestScope = 'guest';

  final List<Order> _orders = [];
  final List<Timer> _timers = [];
  NotificationsProvider? _notifier;

  /// Чья история сейчас открыта: `u:<id>` — аккаунт, `me` — вошли, но id ещё
  /// неизвестен, `guest` — без входа.
  String _scope = _guestScope;
  bool _loggedIn = false;

  String get _key => '$keyPrefix$_scope';

  /// Ключ хранения истории для аккаунта (для тестов/диагностики).
  static String storageKeyFor(String? userId) =>
      '$keyPrefix${_scopeFor(true, userId)}';

  static String _scopeFor(bool loggedIn, String? userId) {
    if (!loggedIn) return _guestScope;
    return (userId != null && userId.isNotEmpty) ? 'u:$userId' : 'me';
  }

  /// Начать оплату заказа: backend создаёт платёж и отдаёт ссылку для покупателя.
  Future<PaymentStart> startPayment(String orderId) => _repo.startPayment(orderId);

  /// Статус оплаты. Backend перепроверяет его у провайдера, если уведомление
  /// о платеже потерялось, — поэтому спрашивать можно спокойно.
  Future<String> paymentStatus(String orderId) => _repo.paymentStatus(orderId);

  /// Результат последней отправки заказа на backend: true — заказ реально принят
  /// сервером (или mock-режим), false — отправка не удалась (сеть/сервер). Чекаут
  /// дожидается его: показывать «оформлен» и чистить корзину можно ТОЛЬКО при true.
  Future<bool>? lastSubmit;

  OrderProvider(this._prefs, this._repo,
      {this.serverBacked = false, bool? simulateDelivery})
      : simulateDelivery = simulateDelivery ?? !serverBacked {
    // Общая история без владельца: чья она — неизвестно, показывать нельзя.
    // Настоящие заказы живут на сервере и вернутся через refresh() после входа.
    _prefs.remove(legacyKey);
    _load();
  }

  /// Подключается из main.dart через ProxyProvider.
  void attachNotifier(NotificationsProvider notifier) {
    _notifier = notifier;
  }

  /// Вызывается из ProxyProvider при изменении авторизации. [userId] — id
  /// аккаунта: у каждого своя история. При выходе или смене аккаунта история
  /// прошлого аккаунта убирается и из памяти, и с устройства (аудит C03).
  Future<void> syncAuth(bool loggedIn, {String? userId}) async {
    final scope = _scopeFor(loggedIn, userId);
    if (scope == _scope && loggedIn == _loggedIn) return;
    final prevScope = _scope;
    final wasLoggedIn = _loggedIn;
    _scope = scope;
    _loggedIn = loggedIn;
    if (prevScope != scope) {
      _cancelTimers();
      _orders.clear();
      if (wasLoggedIn) _prefs.remove('$keyPrefix$prevScope');
      _load();
      notifyListeners();
    }
    if (loggedIn) await refresh();
  }

  /// Подтянуть историю заказов с сервера и слить с локальными.
  /// Сервер — источник правды: его версия заказа ЗАМЕНЯЕТ локальную (статус,
  /// оплата, пометки магазина меняются только там — аудит B08). Локальные заказы,
  /// которых на сервере нет (отправка ещё в пути), остаются.
  Future<void> refresh() async {
    if (!serverBacked) return;
    final scope = _scope;
    try {
      final server = await _repo.fetchOrders();
      // Пока шёл запрос, сменился аккаунт — чужой ответ не применяем.
      if (scope != _scope) return;
      final byId = <String, Order>{for (final o in _orders) o.id: o};
      for (final o in server) {
        byId[o.id] = o;
      }
      final merged = byId.values.toList()
        ..sort((a, b) => b.createdAt.compareTo(a.createdAt));
      _orders
        ..clear()
        ..addAll(merged);
      _save();
      notifyListeners();
    } catch (_) {
      // backend недоступен — остаёмся на локальной истории
    }
  }

  List<Order> get orders => List.unmodifiable(_orders);

  Order? findById(String id) {
    try {
      return _orders.firstWhere((o) => o.id == id);
    } catch (_) {
      return null;
    }
  }

  void _cancelTimers() {
    for (final t in _timers) {
      t.cancel();
    }
    _timers.clear();
  }

  @override
  void dispose() {
    _cancelTimers();
    super.dispose();
  }

  void _load() {
    final raw = _prefs.getString(_key);
    if (raw == null) return;
    try {
      final list = jsonDecode(raw) as List;
      _orders.addAll(
        list.map((j) => Order.fromJson(j as Map<String, dynamic>)),
      );
    } catch (_) {}
  }

  void _save() {
    _prefs.setString(_key, jsonEncode(_orders.map((o) => o.toJson()).toList()));
  }

  Order placeOrder(List<CartItem> cartItems, CheckoutData data,
      {int pointsRedeemed = 0}) {
    final items = cartItems
        .map((ci) => OrderItem(
              productId: ci.product.id,
              productName: ci.product.name,
              productBrand: ci.product.brand,
              imageUrl: ci.product.firstImage,
              price: ci.product.price,
              size: ci.size,
              color: ci.color,
              quantity: ci.quantity,
            ))
        .toList();

    final subtotal = cartItems.fold<double>(0, (s, i) => s + i.total);
    final deliveryCost = costFor(data.deliveryType, subtotal);
    final total = (subtotal + deliveryCost - pointsRedeemed)
        .clamp(0, subtotal + deliveryCost)
        .toDouble();

    final order = Order(
      id: 'SS-${DateTime.now().millisecondsSinceEpoch % 100000}',
      items: items,
      subtotal: subtotal,
      deliveryCost: deliveryCost,
      pointsRedeemed: pointsRedeemed,
      total: total,
      checkoutData: data,
      status: OrderStatus.pending,
      createdAt: DateTime.now(),
    );

    _orders.insert(0, order);
    _save();
    notifyListeners();

    // Отправка на backend с отслеживанием результата (в проде — реальный POST /orders).
    // Чекаут дожидается `lastSubmit`: true — заказ принят сервером, false — НЕ долетел.
    // Ошибку НЕ проглатываем: при провале заказ снимается локально (не «фантом»).
    lastSubmit = _submit(order);
    unawaited(lastSubmit!);

    return order;
  }

  /// Отправляет заказ на backend. Возвращает true при успехе (или в mock-режиме),
  /// false — если отправка не удалась. При провале заказ снимается локально, чтобы
  /// не было ситуации «заказ оформлен в приложении, но на сервере его нет».
  Future<bool> _submit(Order order) async {
    try {
      await _repo.submitOrder(order);
      _onSubmitted(order.id);
      return true;
    } catch (e, st) {
      _onSubmitFailed(order.id);
      // Важный «тихий» провал: заказ не долетел до сервера. Заказ уже откачен
      // локально (не «фантом»), но САМ факт делаем видимым в мониторинге (D-32),
      // не ломая UX. Без SENTRY_DSN (сборка без --dart-define) — безопасный no-op.
      await Sentry.captureException(
        e,
        stackTrace: st,
        withScope: (scope) {
          scope.setTag('area', 'order_submit');
          scope.setContexts('order', {
            'id': order.id,
            'total': order.total,
            'items': order.items.length,
          });
        },
      );
      return false;
    }
  }

  /// Заказ принят сервером: первое уведомление. Дальше статус приходит с
  /// сервера; имитация доставки — только в mock-режиме ([simulateDelivery]).
  void _onSubmitted(String orderId) {
    final i = _orders.indexWhere((o) => o.id == orderId);
    if (i < 0) return;
    final order = _orders[i];
    _notifier?.push(AppNotification(
      id: 'n-${DateTime.now().microsecondsSinceEpoch}',
      title: 'Заказ №${order.id} оформлен',
      body: 'Мы приняли ваш заказ на ${order.total.toInt()} ₽ и начали обработку',
      type: NotifType.order,
      orderId: order.id,
      createdAt: DateTime.now(),
    ));
    if (simulateDelivery) _scheduleStatusProgress(order.id);
  }

  /// Отправка не удалась: снимаем локальный заказ, чтобы не создавать «фантом»
  /// (показан оформленным, но на сервере его нет). Чекаут покажет ошибку и
  /// сохранит корзину/баллы для повторной попытки.
  void _onSubmitFailed(String orderId) {
    _orders.removeWhere((o) => o.id == orderId);
    _save();
    notifyListeners();
  }

  /// Имитация жизненного цикла заказа (mock-режим без backend): каждый этап
  /// шлёт уведомление. Для реальных заказов не вызывается (аудит B07).
  void _scheduleStatusProgress(String orderId) {
    final steps = <(Duration, OrderStatus, String, String)>[
      (
        const Duration(seconds: 8),
        OrderStatus.processing,
        'Заказ комплектуется',
        'Мы собираем ваш заказ на складе',
      ),
      (
        const Duration(seconds: 20),
        OrderStatus.shipped,
        'Заказ передан в доставку',
        'Курьер скоро заберёт ваш заказ',
      ),
      (
        const Duration(seconds: 40),
        OrderStatus.delivered,
        'Заказ доставлен',
        'Спасибо за покупку! Будем рады видеть вас снова',
      ),
    ];

    for (final step in steps) {
      _timers.add(Timer(step.$1, () {
        _advanceStatus(orderId, step.$2, step.$3, step.$4);
      }));
    }
  }

  void _advanceStatus(
      String orderId, OrderStatus status, String title, String body) {
    final index = _orders.indexWhere((o) => o.id == orderId);
    if (index < 0) return;
    _orders[index] = _orders[index].copyWith(status: status);
    _save();
    notifyListeners();

    _notifier?.push(AppNotification(
      id: 'n-${DateTime.now().microsecondsSinceEpoch}',
      title: '$title · №$orderId',
      body: body,
      type: NotifType.order,
      orderId: orderId,
      createdAt: DateTime.now(),
    ));
  }

  /// Цена доставки для суммы товаров [goods] — по ценам сервера (D-110):
  /// способы ведёт владелец в админке, итог заказа считает сервер.
  static double costFor(DeliveryType type, [double goods = 0]) =>
      ShippingRates.costFor(type, goods);

  static String deliveryLabel(DeliveryType type) {
    switch (type) {
      case DeliveryType.pickup:
        return 'Самовывоз';
      case DeliveryType.courier:
        return 'Курьер по Якутску';
    }
  }

  static String paymentLabel(PaymentType type) {
    switch (type) {
      case PaymentType.card:
        return 'Картой онлайн';
      case PaymentType.cash:
        return 'Наличными при получении';
      case PaymentType.sbp:
        return 'СБП';
    }
  }

  static String statusLabel(OrderStatus status) {
    switch (status) {
      case OrderStatus.pending:
        return 'Принят';
      case OrderStatus.processing:
        return 'Комплектуется';
      case OrderStatus.shipped:
        return 'В доставке';
      case OrderStatus.delivered:
        return 'Доставлен';
      case OrderStatus.cancelled:
        return 'Отменён';
    }
  }
}
