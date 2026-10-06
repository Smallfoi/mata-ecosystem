import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:sport_store/data/mock_data.dart';
import 'package:sport_store/data/repositories/loyalty_repository.dart';
import 'package:sport_store/data/repositories/order_repository.dart';
import 'package:sport_store/models/loyalty.dart';
import 'package:sport_store/models/order.dart';
import 'package:sport_store/providers/cart_provider.dart';
import 'package:sport_store/providers/loyalty_provider.dart';
import 'package:sport_store/providers/order_provider.dart';

/// Сервер заказов «по аккаунтам»: что вернёт GET /orders, зависит от того,
/// кто сейчас вошёл ([current]).
class _ServerRepo implements OrderRepository {
  final Map<String, List<Map<String, dynamic>>> byUser = {};
  String current = '';

  @override
  Future<Order> submitOrder(Order order) async => order;
  @override
  Future<List<Order>> fetchOrders() async =>
      (byUser[current] ?? const []).map(Order.fromJson).toList();
  @override
  Future<PaymentStart> startPayment(String orderId) async =>
      const PaymentStart(status: 'paid', confirmationUrl: '', paymentId: '');
  @override
  Future<String> paymentStatus(String orderId) async => 'paid';
}

class _LoyaltyRepo implements LoyaltyRepository {
  final Map<String, LoyaltyAccount> byUser = {};
  String current = '';

  @override
  Future<LoyaltyAccount> fetchAccount() async =>
      byUser[current] ?? const LoyaltyAccount();
  @override
  Future<void> postTransaction(LoyaltyTransaction tx) async {}
  @override
  Future<int> redeem({
    required int points,
    required String orderId,
    String description = '',
  }) async =>
      0;
  @override
  Future<RedeemPreview?> redeemPreview(List<Map<String, dynamic>> items) async =>
      null;
}

CheckoutData _data() => const CheckoutData(
      name: 'Тест',
      phone: '+70000000000',
      email: 'test@example.com',
      deliveryType: DeliveryType.pickup,
      paymentType: PaymentType.sbp,
    );

/// Заказ в том виде, как его отдаёт backend (payload + серверные поля #805).
Map<String, dynamic> _serverOrder(
  String id, {
  String status = 'pending',
  Map<String, dynamic> extra = const {},
}) =>
    {
      'id': id,
      'items': [
        {
          'productId': '1',
          'productName': 'Кроссовки',
          'productBrand': 'МАТА',
          'imageUrl': '',
          'price': 1000,
          'size': 'M',
          'color': 'Чёрный',
          'quantity': 1,
        }
      ],
      'subtotal': 1000,
      'deliveryCost': 0,
      'pointsRedeemed': 0,
      'total': 1000,
      'checkoutData': _data().toJson(),
      'status': status,
      'createdAt': '2026-09-20T10:00:00.000',
      ...extra,
    };

Future<SharedPreferences> _prefs([Map<String, Object> init = const {}]) async {
  SharedPreferences.setMockInitialValues(init);
  return SharedPreferences.getInstance();
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('B07 — статус реального заказа меняет только сервер', () {
    testWidgets('serverBacked: время идёт — статус не меняется', (tester) async {
      final prefs = await _prefs();
      final orders = OrderProvider(prefs, _ServerRepo(), serverBacked: true);
      final cart = CartProvider(prefs);
      cart.add(MockData.getById('1')!, 'M', 'Чёрный');

      final order = orders.placeOrder(cart.items.toList(), _data());
      expect(await orders.lastSubmit!, isTrue);

      await tester.pump(const Duration(minutes: 5));
      expect(orders.findById(order.id)!.status, OrderStatus.pending,
          reason: 'без ответа сервера заказ не «доставляется» сам');
      orders.dispose();
    });

    testWidgets('mock-режим: имитация доставки осталась', (tester) async {
      final prefs = await _prefs();
      final orders = OrderProvider(prefs, MockOrderRepository());
      final cart = CartProvider(prefs);
      cart.add(MockData.getById('1')!, 'M', 'Чёрный');

      final order = orders.placeOrder(cart.items.toList(), _data());
      await tester.pump(const Duration(milliseconds: 400)); // mock-отправка
      expect(await orders.lastSubmit!, isTrue);
      await tester.pump(const Duration(minutes: 1));
      expect(orders.findById(order.id)!.status, OrderStatus.delivered);
      orders.dispose();
    });
  });

  group('B08 — серверная версия заказа главнее локальной', () {
    test('статус с сервера обновляет сохранённый локально заказ', () async {
      final repo = _ServerRepo()..current = 'A';
      final prefs = await _prefs({
        OrderProvider.storageKeyFor('A'):
            '[${_jsonOf(_serverOrder('SS-1', status: 'pending'))}]',
      });
      repo.byUser['A'] = [
        _serverOrder('SS-1', status: 'shipped', extra: {
          'serverId': 7,
          'serverStatus': 'shipped',
          'paymentStatus': 'paid',
          'onecStatus': 'shipped',
          'courierNote': 'Курьер Иван, до 18:00',
        }),
      ];
      final orders = OrderProvider(prefs, repo, serverBacked: true);
      await orders.syncAuth(true, userId: 'A');

      final o = orders.findById('SS-1')!;
      expect(o.status, OrderStatus.shipped);
      expect(o.paymentStatus, 'paid');
      expect(o.courierNote, 'Курьер Иван, до 18:00');
      expect(orders.orders.length, 1);
      // И сохранено локально — после перезапуска офлайн виден свежий статус.
      final again = OrderProvider(prefs, _FailingFetchRepo(), serverBacked: true);
      await again.syncAuth(true, userId: 'A');
      expect(again.findById('SS-1')!.status, OrderStatus.shipped);
    });

    test('старый сервер без новых полей: заказ читается, статусы понятны', () {
      final o = Order.fromJson(_serverOrder('SS-2', status: 'paid'));
      expect(o.status, OrderStatus.processing);
      expect(o.paymentStatus, isNull);
      expect(Order.parseStatus('canceled'), OrderStatus.cancelled);
      expect(Order.parseStatus('что-то новое'), OrderStatus.pending);
      // В POST при оформлении серверных полей нет.
      expect(o.toJson().containsKey('paymentStatus'), isFalse);
    });
  });

  group('C03 — история заказов своя у каждого аккаунта', () {
    test('A → выход → B: заказов A не видно и на устройстве их нет', () async {
      final repo = _ServerRepo();
      repo.byUser['A'] = [_serverOrder('SS-A')];
      repo.byUser['B'] = [_serverOrder('SS-B')];
      final prefs = await _prefs();
      final orders = OrderProvider(prefs, repo, serverBacked: true);

      repo.current = 'A';
      await orders.syncAuth(true, userId: 'A');
      expect(orders.orders.map((o) => o.id), ['SS-A']);

      repo.current = '';
      await orders.syncAuth(false);
      expect(orders.orders, isEmpty);
      expect(prefs.getString(OrderProvider.storageKeyFor('A')), isNull,
          reason: 'история A стёрта с устройства при выходе');

      repo.current = 'B';
      await orders.syncAuth(true, userId: 'B');
      expect(orders.orders.map((o) => o.id), ['SS-B']);
    });

    test('смена аккаунта без выхода (A → B) тоже не показывает A', () async {
      final repo = _ServerRepo();
      repo.byUser['A'] = [_serverOrder('SS-A')];
      final prefs = await _prefs();
      final orders = OrderProvider(prefs, repo, serverBacked: true);
      repo.current = 'A';
      await orders.syncAuth(true, userId: 'A');

      repo.current = 'B';
      await orders.syncAuth(true, userId: 'B');
      expect(orders.orders, isEmpty);
      expect(prefs.getString(OrderProvider.storageKeyFor('A')), isNull);
    });

    test('офлайн: B не видит сохранённую историю A', () async {
      final prefs = await _prefs({
        OrderProvider.storageKeyFor('A'): '[${_jsonOf(_serverOrder('SS-A'))}]',
        OrderProvider.legacyKey: '[${_jsonOf(_serverOrder('SS-OLD'))}]',
      });
      final orders =
          OrderProvider(prefs, _FailingFetchRepo(), serverBacked: true);
      expect(orders.orders, isEmpty,
          reason: 'старый общий ключ без владельца не показывается');
      expect(prefs.getString(OrderProvider.legacyKey), isNull);

      await orders.syncAuth(true, userId: 'B');
      expect(orders.orders, isEmpty);

      final forA =
          OrderProvider(prefs, _FailingFetchRepo(), serverBacked: true);
      await forA.syncAuth(true, userId: 'A');
      expect(forA.orders.map((o) => o.id), ['SS-A'],
          reason: 'своя история A доступна ему офлайн');
    });

    test('баллы: A → B без выхода — баллы A не видны', () async {
      final repo = _LoyaltyRepo();
      repo.byUser['A'] = LoyaltyAccount(code: '111111', transactions: [
        LoyaltyTransaction(
          id: 't1',
          amount: 500,
          source: LoyaltySource.runnerRun,
          description: 'Пробежка',
          createdAt: DateTime(2026, 9, 1),
        ),
      ]);
      final prefs = await _prefs();
      final loyalty = LoyaltyProvider(prefs, repo, serverBacked: true);
      repo.current = 'A';
      await loyalty.syncAuth(true, userId: 'A');
      expect(loyalty.balance, 500);

      repo.current = 'B';
      await loyalty.syncAuth(true, userId: 'B');
      expect(loyalty.balance, 0);
      expect(loyalty.code, isEmpty);

      await loyalty.syncAuth(false);
      expect(loyalty.balance, 0);
    });
  });
}

/// GET /orders недоступен (офлайн).
class _FailingFetchRepo extends _ServerRepo {
  @override
  Future<List<Order>> fetchOrders() async => throw Exception('offline');
}

String _jsonOf(Map<String, dynamic> m) =>
    jsonEncode(Order.fromJson(m).toJson());
