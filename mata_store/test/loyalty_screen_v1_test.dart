import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:sport_store/data/repositories/auth_repository.dart';
import 'package:sport_store/data/repositories/loyalty_repository.dart';
import 'package:sport_store/models/loyalty.dart';
import 'package:sport_store/providers/auth_provider.dart';
import 'package:sport_store/providers/loyalty_provider.dart';
import 'package:sport_store/providers/remote_content_provider.dart';
import 'package:sport_store/screens/loyalty/loyalty_screen.dart';

class _Repo implements LoyaltyRepository {
  final LoyaltyAccount account;
  _Repo(this.account);

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
  Future<RedeemPreview?> redeemPreview(List<Map<String, dynamic>> items) async =>
      null;
}

Future<Widget> _app(LoyaltyAccount acc) async {
  SharedPreferences.setMockInitialValues({});
  final prefs = await SharedPreferences.getInstance();
  final loyalty = LoyaltyProvider(prefs, _Repo(acc), serverBacked: true);
  await loyalty.syncAuth(true, userId: 'u1');
  return MultiProvider(
    providers: [
      ChangeNotifierProvider(create: (_) => AuthProvider(prefs, MockAuthRepository())),
      ChangeNotifierProvider.value(value: loyalty),
      ChangeNotifierProvider(create: (_) => RemoteContentProvider(null)),
    ],
    child: const MaterialApp(
      home: MediaQuery(
        data: MediaQueryData(size: Size(420, 2400), disableAnimations: true),
        child: LoyaltyScreen(),
      ),
    ),
  );
}

void main() {
  testWidgets('v1: доступно, шкалы, лоты; без обещаний кэшбэка', (tester) async {
    tester.view.physicalSize = const Size(840, 4800);
    tester.view.devicePixelRatio = 2;
    addTearDown(tester.view.reset);

    final v1 = LoyaltyV1.fromAccount({
      'programV1': true,
      'balance': 250,
      'v1': {
        'available': 250, 'redeemable': 250, 'held': 375, 'statusPoints': 320,
        'level': 'basic', 'nextLevelThreshold': 500, 'platinumMinSpend': 60000,
        'redeemMin': 300, 'redeemCeiling': 0.15, 'heldNextAmount': 375,
        'heldNextAt': '2026-10-20T12:00:00+09:00',
        'levels': [
          {'key': 'basic', 'threshold': 0, 'purchaseRate': 0.05,
           'redeemCeiling': 0.15},
        ],
        'lots': [
          {'id': 1, 'amount': 250, 'remaining': 250, 'state': 'available',
           'source': 'migration', 'expiresAt': '2027-03-01T12:00:00+09:00'},
        ],
      },
    })!;
    await tester.pumpWidget(await _app(LoyaltyAccount(
        balance: 250, total: 625, pending: 375, v1: v1)));
    await tester.pump(const Duration(milliseconds: 600));

    expect(find.text('Доступно 250 бонусов'), findsOneWidget);
    expect(find.text('Списание от 300: накоплено 250 из 300'), findsOneWidget);
    expect(find.text('до Серебра: 320 из 500 статусных'), findsOneWidget);
    expect(find.text('оплата до 15%'), findsOneWidget);
    expect(find.text('Перенос баланса'), findsOneWidget);
    expect(find.text('сгорят 01.03.2027'), findsOneWidget);
    expect(find.textContaining('эшбэк'), findsNothing);
    expect(find.textContaining('доставк'), findsNothing);
    expect(find.textContaining('VIP'), findsNothing);
  });

  testWidgets('прежний сервер: экран как раньше, без обещаний кэшбэка',
      (tester) async {
    tester.view.physicalSize = const Size(840, 4800);
    tester.view.devicePixelRatio = 2;
    addTearDown(tester.view.reset);

    await tester.pumpWidget(
        await _app(const LoyaltyAccount(balance: 250, total: 250)));
    await tester.pump(const Duration(milliseconds: 600));

    expect(find.text('Уровень: Серебро'), findsOneWidget);
    expect(find.textContaining('До уровня «Золото»'), findsOneWidget);
    expect(find.textContaining('Доступно'), findsNothing);
    expect(find.textContaining('эшбэк'), findsNothing);
  });
}
