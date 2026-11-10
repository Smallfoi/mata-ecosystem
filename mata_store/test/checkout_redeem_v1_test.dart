import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:sport_store/data/repositories/auth_repository.dart';
import 'package:sport_store/data/repositories/loyalty_repository.dart';
import 'package:sport_store/data/repositories/order_repository.dart';
import 'package:sport_store/models/loyalty.dart';
import 'package:sport_store/models/product.dart';
import 'package:sport_store/providers/auth_provider.dart';
import 'package:sport_store/providers/cart_provider.dart';
import 'package:sport_store/providers/loyalty_provider.dart';
import 'package:sport_store/providers/order_provider.dart';
import 'package:sport_store/providers/remote_content_provider.dart';
import 'package:sport_store/screens/checkout/checkout_screen.dart';

// Касса программы v1: максимум списания — из POST /v1/loyalty/redeem-preview
// по корзине, ползунок, недопущенные позиции помечены; без превью — как раньше.

class _Repo implements LoyaltyRepository {
  final LoyaltyAccount account;
  final RedeemPreview? preview;
  List<Map<String, dynamic>>? sent;
  _Repo(this.account, this.preview);

  @override
  Future<LoyaltyAccount> fetchAccount() async => account;
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
  Future<RedeemPreview?> redeemPreview(List<Map<String, dynamic>> items) async {
    sent = items;
    return preview;
  }
}

Product _p(String id, double price) => Product(
      id: id,
      name: 'Товар $id',
      brand: 'МАТА',
      categoryId: 'c',
      price: price,
      imageUrls: const [],
      description: '',
      sizes: const ['M'],
      colors: const ['Чёрный'],
    );

Future<void> _toReview(WidgetTester tester, _Repo repo) async {
  tester.view.physicalSize = const Size(900, 2400);
  tester.view.devicePixelRatio = 2;
  addTearDown(tester.view.reset);
  SharedPreferences.setMockInitialValues({});
  final prefs = await SharedPreferences.getInstance();
  final cart = CartProvider(prefs)
    ..add(_p('shoe', 7000), 'M', 'Чёрный')
    ..add(_p('gel', 500), 'M', 'Чёрный');
  final loyalty = LoyaltyProvider(prefs, repo, serverBacked: true);
  await loyalty.syncAuth(true, userId: 'u1');
  await tester.pumpWidget(MultiProvider(
    providers: [
      ChangeNotifierProvider(
          create: (_) => AuthProvider(prefs, MockAuthRepository())),
      ChangeNotifierProvider.value(value: cart),
      ChangeNotifierProvider.value(value: loyalty),
      ChangeNotifierProvider(
          create: (_) => OrderProvider(prefs, MockOrderRepository())),
      ChangeNotifierProvider(create: (_) => RemoteContentProvider(null)),
    ],
    child: const MaterialApp(home: CheckoutScreen()),
  ));
  await tester.pump();
  final fields = find.byType(TextField);
  await tester.enterText(fields.at(0), 'Тест');
  await tester.enterText(fields.at(1), '+79990000000');
  await tester.enterText(fields.at(2), 't@example.com');
  await tester.tap(find.text('ДАЛЕЕ'));
  await tester.pumpAndSettle();
  final f2 = find.byType(TextField).hitTestable();
  await tester.enterText(f2.at(0), 'Якутск');
  await tester.enterText(f2.at(1), 'Ленина');
  await tester.enterText(f2.at(2), '1');
  await tester.tap(find.text('ДАЛЕЕ'));
  await tester.pumpAndSettle();
  await tester.tap(find.text('ДАЛЕЕ'));
  await tester.pumpAndSettle();
}

void main() {
  final v1Account = LoyaltyAccount(
    balance: 5000,
    total: 5000,
    v1: LoyaltyV1.fromAccount({
      'programV1': true,
      'v1': {'available': 5000, 'redeemable': 5000, 'level': 'platinum',
             'redeemMin': 300, 'redeemCeiling': 0.3},
    }),
  );

  testWidgets('v1: ползунок до redeemMax, позиция без бонусов помечена',
      (tester) async {
    final repo = _Repo(
      v1Account,
      RedeemPreview.fromJson({
        'programV1': true, 'available': 5000, 'eligibleTotal': 7000.0,
        'ceiling': 0.3, 'redeemMax': 2100, 'redeemMin': 300, 'canRedeem': true,
        'reason': '',
        'lines': [
          {'index': 0, 'productId': 'shoe', 'eligible': true, 'reason': ''},
          {'index': 1, 'productId': 'gel', 'eligible': false,
           'reason': 'excluded_category'},
        ],
      }),
    );
    await _toReview(tester, repo);

    expect(repo.sent, [
      {'productId': 'shoe', 'quantity': 1},
      {'productId': 'gel', 'quantity': 1},
    ]);
    expect(find.byType(Slider), findsOneWidget);
    expect(find.text('не оплачивается бонусами'), findsOneWidget);
    expect(find.text('от 300 до 2100 · доступно 5000'), findsOneWidget);

    // Ползунок до упора вправо — списываем максимум, цена «₽ + бонусы».
    await tester.drag(find.byType(Slider), const Offset(2000, 0));
    await tester.pumpAndSettle();
    expect(find.text('Списать 2100 бонусов'), findsOneWidget);
    expect(find.text('5 400 ₽ + 2 100 бонусов'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('v1: redeemMax меньше минимума — неактивно с пояснением',
      (tester) async {
    final repo = _Repo(
      v1Account,
      RedeemPreview.fromJson({
        'programV1': true, 'available': 250, 'redeemMax': 250,
        'redeemMin': 300, 'canRedeem': false,
        'reason': 'Списать бонусы можно от 300: сейчас доступно 250',
        'lines': [],
      }),
    );
    await _toReview(tester, repo);
    expect(find.byType(Slider), findsNothing);
    expect(find.text('Списать бонусы можно от 300: сейчас доступно 250'),
        findsOneWidget);
  });

  testWidgets('прежний сервер: без превью — переключатель как раньше',
      (tester) async {
    final repo = _Repo(const LoyaltyAccount(balance: 400, total: 400), null);
    await _toReview(tester, repo);
    expect(find.byType(Slider), findsNothing);
    expect(find.text('Списать 400 баллов'), findsOneWidget);
  });
}
