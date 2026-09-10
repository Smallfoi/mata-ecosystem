import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:qr_flutter/qr_flutter.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:sport_store/data/repositories/order_repository.dart';
import 'package:sport_store/models/order.dart';
import 'package:sport_store/providers/order_provider.dart';
import 'package:sport_store/providers/remote_content_provider.dart';
import 'package:sport_store/screens/checkout/payment_screen.dart';

/// Репозиторий с управляемым исходом оплаты.
class _PayRepo implements OrderRepository {
  final PaymentStart start;
  int startCalls = 0;

  _PayRepo({required this.start});

  @override
  Future<Order> submitOrder(Order order) async => order;
  @override
  Future<List<Order>> fetchOrders() async => const [];
  @override
  Future<PaymentStart> startPayment(String orderId) async {
    startCalls++;
    return start;
  }

  @override
  Future<String> paymentStatus(String orderId) async => 'pending';
}

Future<OrderProvider> _provider(OrderRepository repo) async {
  SharedPreferences.setMockInitialValues({});
  final prefs = await SharedPreferences.getInstance();
  return OrderProvider(prefs, repo, serverBacked: true);
}

Widget _app(OrderProvider orders) => MultiProvider(
      providers: [
        ChangeNotifierProvider.value(value: orders),
        // Тексты экрана редактируются в Конструкторе; без API берутся фолбэки.
        ChangeNotifierProvider(create: (_) => RemoteContentProvider(null)),
      ],
      child: const MaterialApp(home: PaymentScreen(orderId: 'SS-1')),
    );

/// Телефон: узкий экран → кнопка «Оплатить» (QR на своём же экране бесполезен).
void _phone(WidgetTester tester) {
  tester.view.physicalSize = const Size(780, 1680);
  tester.view.devicePixelRatio = 2;
  addTearDown(tester.view.reset);
}

/// Широкий экран (веб-сборка витрины) → QR, его сканируют телефоном.
void _desktop(WidgetTester tester) {
  tester.view.physicalSize = const Size(1440, 1800);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('Ожидание оплаты: показываем СБП и кнопку', (tester) async {
    final repo = _PayRepo(
      start: const PaymentStart(
        status: 'pending',
        confirmationUrl: 'https://qr.nspk.ru/test',
        paymentId: 'p1',
      ),
    );
    final orders = await _provider(repo);
    _phone(tester);

    await tester.pumpWidget(_app(orders));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 700));  // доиграть появление

    expect(repo.startCalls, 1, reason: 'оплата должна начинаться сама');
    expect(find.text('ОПЛАТА ПО СБП'), findsOneWidget);
    expect(find.text('ОПЛАТИТЬ'), findsOneWidget);
    expect(find.text('Ждём подтверждение оплаты'), findsOneWidget);

    await tester.pumpWidget(const SizedBox());  // dispose: снимает опрос статуса
    orders.dispose();
  });

  testWidgets('Широкий экран: вместо кнопки — QR-код', (tester) async {
    final repo = _PayRepo(
      start: const PaymentStart(
        status: 'pending',
        confirmationUrl: 'https://qr.nspk.ru/test',
        paymentId: 'p1',
      ),
    );
    final orders = await _provider(repo);
    _desktop(tester);

    await tester.pumpWidget(_app(orders));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 700));  // доиграть появление

    expect(find.byType(QrImageView), findsOneWidget);
    expect(find.text('ОПЛАТИТЬ'), findsNothing);

    await tester.pumpWidget(const SizedBox());  // dispose: снимает опрос статуса
    orders.dispose();
  });

  testWidgets('Провайдер отказал: понятная ошибка и повтор, а не пустой экран',
      (tester) async {
    final repo = _FailingPayRepo();
    final orders = await _provider(repo);
    _phone(tester);

    await tester.pumpWidget(_app(orders));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 700));  // доиграть появление

    expect(find.text('Не удалось начать оплату'), findsOneWidget);
    expect(find.text('ПОПРОБОВАТЬ СНОВА'), findsOneWidget);

    await tester.pumpWidget(const SizedBox());  // dispose: снимает опрос статуса
    orders.dispose();
  });
}

class _FailingPayRepo implements OrderRepository {
  @override
  Future<Order> submitOrder(Order order) async => order;
  @override
  Future<List<Order>> fetchOrders() async => const [];
  @override
  Future<PaymentStart> startPayment(String orderId) async =>
      throw Exception('Оплата недоступна');
  @override
  Future<String> paymentStatus(String orderId) async => 'pending';
}
