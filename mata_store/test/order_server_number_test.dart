import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:sport_store/data/mock_data.dart';
import 'package:sport_store/data/repositories/order_repository.dart';
import 'package:sport_store/models/order.dart';
import 'package:sport_store/providers/cart_provider.dart';
import 'package:sport_store/providers/order_provider.dart';

/// Сервер, как с D-120: номер заказа выдаёт сам, черновой возвращает в clientRef.
class _ServerNumberRepo implements OrderRepository {
  final List<Order> stored = [];

  Order _withNumber(Order o) => Order(
        id: 'МАТА-48271593',
        items: o.items,
        subtotal: o.subtotal,
        deliveryCost: o.deliveryCost,
        pointsRedeemed: o.pointsRedeemed,
        total: o.total,
        checkoutData: o.checkoutData,
        status: o.status,
        createdAt: o.createdAt,
        clientRef: o.id,
      );

  @override
  Future<Order> submitOrder(Order order) async {
    final saved = _withNumber(order);
    stored.add(saved);
    return saved;
  }

  @override
  Future<List<Order>> fetchOrders() async => List.of(stored);
  @override
  Future<PaymentStart> startPayment(String orderId) async =>
      const PaymentStart(status: 'paid', confirmationUrl: '', paymentId: '');
  @override
  Future<String> paymentStatus(String orderId) async => 'paid';
}

CheckoutData _data() => CheckoutData(
      name: 'Тест',
      phone: '+70000000000',
      email: 'test@example.com',
      deliveryType: DeliveryType.pickup,
      paymentType: PaymentType.card,
    );

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('Номер заказа — от сервера: черновик заменяется, дублей нет', () async {
    SharedPreferences.setMockInitialValues({});
    final prefs = await SharedPreferences.getInstance();
    final repo = _ServerNumberRepo();
    final orders = OrderProvider(prefs, repo, serverBacked: true);
    final cart = CartProvider(prefs);
    cart.add(MockData.getById('1')!, 'M', 'Чёрный');

    final draft = orders.placeOrder(cart.items.toList(), _data());
    expect(await orders.lastSubmit!, isTrue);

    expect(orders.idOf(draft.id), 'МАТА-48271593');
    expect(orders.orders.map((o) => o.id), ['МАТА-48271593'],
        reason: 'в истории — заказ с номером сервера, черновика нет');

    // Подтягиваем историю с сервера — заказ не задваивается.
    await orders.refresh();
    expect(orders.orders.map((o) => o.id), ['МАТА-48271593']);
    orders.dispose();
  });

  test('Старый черновик в истории заменяется серверным заказом при refresh',
      () async {
    SharedPreferences.setMockInitialValues({});
    final prefs = await SharedPreferences.getInstance();
    final repo = _ServerNumberRepo();
    final orders = OrderProvider(prefs, _FailingThenServer(repo),
        serverBacked: true);
    final cart = CartProvider(prefs);
    cart.add(MockData.getById('1')!, 'M', 'Чёрный');
    final draft = orders.placeOrder(cart.items.toList(), _data());
    await orders.lastSubmit;
    // Черновик остался локально (ответ сервера не дошёл), а на сервере заказ есть.
    expect(orders.orders.map((o) => o.id), [draft.id]);
    await orders.refresh();
    expect(orders.orders.map((o) => o.id), ['МАТА-48271593']);
    orders.dispose();
  });

  test('clientRef переживает сохранение и чтение', () {
    final j = {
      'id': 'МАТА-48271593',
      'clientRef': 'SS-12345',
      'items': [],
      'subtotal': 0,
      'deliveryCost': 0,
      'total': 0,
      'checkoutData': _data().toJson(),
      'status': 'pending',
      'createdAt': DateTime(2026, 11, 10).toIso8601String(),
    };
    final o = Order.fromJson(j);
    expect(o.clientRef, 'SS-12345');
    expect(Order.fromJson(o.toJson()).clientRef, 'SS-12345');
    expect(o.shortId, '48271593');
  });
}

/// Сервер заказ записал, но ответ до приложения не дошёл — а локальный
/// черновик остался (так бывало у старых сборок и при обрыве связи).
class _FailingThenServer implements OrderRepository {
  final _ServerNumberRepo inner;
  _FailingThenServer(this.inner);

  @override
  Future<Order> submitOrder(Order order) async {
    await inner.submitOrder(order);
    return order; // как старый ответ: тот же черновик
  }

  @override
  Future<List<Order>> fetchOrders() => inner.fetchOrders();
  @override
  Future<PaymentStart> startPayment(String orderId) =>
      inner.startPayment(orderId);
  @override
  Future<String> paymentStatus(String orderId) => inner.paymentStatus(orderId);
}
