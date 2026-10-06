import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:latlong2/latlong.dart' show LatLng;
import 'package:kvartal_app/features/loyalty/data/loyalty_provider.dart';
import 'package:kvartal_app/features/run/data/completed_runs_provider.dart';
import 'package:kvartal_app/features/run/data/run_bonus.dart';
import 'package:kvartal_app/features/profile/presentation/screens/profile_screen.dart';
import 'package:kvartal_app/features/run/presentation/screens/run_passport_screen.dart';
import 'package:shared_preferences/shared_preferences.dart';

// Программа лояльности v1 (ТЗ 30.09.2026), этап 3 — клиент Квартала:
// кошелёк по ответу /v1/loyalty/account и бонусы за пробежку из ответа /v1/runs.

Map<String, dynamic> _account({bool v1 = true}) => {
      'balance': 250,
      'total': 625,
      'pending': 375,
      'level': 'gold',
      'code': '123456',
      'transactions': [],
      if (v1) 'programV1': true,
      if (v1)
        'v1': {
          'available': 250, 'redeemable': 250, 'held': 375,
          'statusPoints': 3200, 'purchases365': 12300, 'level': 'gold',
          'levelIndex': 2, 'nextLevelThreshold': 5000,
          'platinumMinSpend': 60000, 'redeemMin': 300, 'redeemCeiling': 0.25,
          'heldNextAt': '2026-10-20T12:00:00+09:00', 'heldNextAmount': 375,
          'expiringAt': '2027-03-01T12:00:00+09:00', 'expiringAmount': 250,
          'levels': [
            {'key': 'gold', 'title': 'Золото', 'threshold': 2000,
             'purchaseRate': 0.07, 'redeemCeiling': 0.25, 'expiryMonths': 12},
          ],
          'lots': [
            {'id': 7, 'amount': 300, 'remaining': 250, 'state': 'available',
             'source': 'legacy_activity',
             'expiresAt': '2027-03-01T12:00:00+09:00'},
          ],
        },
    };

CompletedRun _run() {
  final route = <LatLng>[];
  final times = <int>[];
  for (var i = 0; i <= 40; i++) {
    route.add(LatLng(62.0 + i * 0.001, 129.7));
    times.add(1757000000000 + i * 60000);
  }
  return CompletedRun(
    id: 'r1',
    finishedAt: DateTime.fromMillisecondsSinceEpoch(times.last),
    route: route,
    routeTimes: times,
    elapsed: const Duration(minutes: 40),
    distanceMeters: 4452,
    capturedZones: 0,
    capturedTerritory: false,
  );
}

class _FakeLoyalty extends LoyaltyNotifier {
  _FakeLoyalty(super.ref, LoyaltyState s) {
    state = s;
  }

  @override
  Future<void> refresh() async {}
}

void main() {
  testWidgets('кошелёк v1: уровень, шкалы, бонусы на счёте', (tester) async {
    tester.view.physicalSize = const Size(900, 4000);
    tester.view.devicePixelRatio = 2;
    addTearDown(tester.view.reset);
    SharedPreferences.setMockInitialValues({});
    final st = LoyaltyState(
      balance: 250, level: 'gold', loaded: true,
      v1: LoyaltyV1.fromAccount(_account()),
    );
    await tester.pumpWidget(ProviderScope(
      overrides: [
        loyaltyProvider.overrideWith((ref) => _FakeLoyalty(ref, st)),
      ],
      child: const MaterialApp(home: PointsHistoryScreen()),
    ));
    await tester.pump(const Duration(milliseconds: 300));
    expect(find.text('Уровень: Золото'), findsOneWidget);
    expect(find.text('Доступно 250 бонусов'), findsOneWidget);
    expect(find.text('до Платины: 3 200 из 5 000 статусных'),
        findsOneWidget);
    expect(find.text('покупки за год: 12 300 из 60 000 ₽'),
        findsOneWidget);
    expect(find.text('БОНУСЫ НА СЧЁТЕ'), findsOneWidget);
    expect(find.text('сгорят 01.03.2027 · из 300'), findsOneWidget);
    expect(find.textContaining('баллов за бег'), findsNothing);
    expect(tester.takeException(), isNull);
  });

  group('кошелёк v1', () {
    test('новые поля: доступно, уровень, две шкалы к Платине, лоты', () {
      final v = LoyaltyV1.fromAccount(_account())!;
      expect(v.level, LoyaltyLevel.gold);
      expect(v.availableText, 'Доступно 250 бонусов');
      expect(v.belowRedeemMin, isTrue);
      expect(v.redeemMinText, 'Списание от 300: накоплено 250 из 300');
      expect(v.levelScaleText, 'до Платины: 3 200 из 5 000 статусных');
      expect(v.showSpendScale, isTrue);
      expect(v.spendScaleText, 'покупки за год: 12 300 из 60 000 ₽');
      expect(v.perkText, '7% бонусами с покупок · оплата бонусами до 25% заказа');
      expect(v.heldLine, 'ещё 375 бонусов станут доступны 20.10');
      expect(v.expiringLine, '250 бонусов сгорят 01.03.2027');
      expect(v.lots.single.sourceLabel, 'Бег и захваты');
      expect(v.lots.single.dateLine, 'сгорят 01.03.2027');
    });

    test('прежний сервер — блока нет, экран как раньше', () {
      expect(LoyaltyV1.fromAccount(_account(v1: false)), isNull);
      expect(const LoyaltyState(balance: 500).programV1, isFalse);
    });
  });

  group('бонусы за пробежку', () {
    test('плоские поля: начислено и остаток лимита', () {
      final b = RunBonusInfo.fromRunResponse('r1', {
        'ok': true, 'pointsAwarded': 45,
        'bonusAwarded': 10, 'bonusMonthLeft': 250,
      })!;
      expect(b.headline, '+10 бонусов');
      expect(b.limitLine, 'ещё 250 бонусов в лимите этого месяца');
    });

    test('вложенный объект и кап — «лимит исчерпан, обновится 1 числа»', () {
      final b = RunBonusInfo.fromRunResponse('r1', {
        'ok': true,
        'loyalty': {'awarded': 0, 'monthLeft': 0, 'capped': true},
      })!;
      expect(b.headline, isNull);
      expect(b.limitLine,
          'Лимит бонусов за месяц исчерпан — обновится 1 числа');
    });

    test('текст сервера при капе важнее нашего', () {
      final b = RunBonusInfo.fromRunResponse('r1', {
        'bonusAwarded': 0, 'monthCapReached': true,
        'bonusText': 'Лимит месяца исчерпан, обновится 1 ноября',
      })!;
      expect(b.limitLine, 'Лимит месяца исчерпан, обновится 1 ноября');
    });

    test('старый ответ сервера — бонусной информации нет', () {
      expect(
        RunBonusInfo.fromRunResponse('r1', {
          'ok': true, 'pointsAwarded': 45, 'dailyCapReached': false,
        }),
        isNull,
      );
      expect(RunBonusInfo.fromRunResponse('r1', null), isNull);
    });
  });

  group('паспорт пробежки', () {
    Future<void> pump(WidgetTester tester, List<Override> overrides) async {
      SharedPreferences.setMockInitialValues({});
      await tester.pumpWidget(ProviderScope(
        overrides: overrides,
        child: MaterialApp(home: RunPassportScreen(run: _run())),
      ));
      await tester.pump(const Duration(milliseconds: 100));
    }

    testWidgets('v1: «+10» и остаток лимита месяца', (tester) async {
      await pump(tester, [
        lastRunBonusProvider.overrideWith((_) => const RunBonusInfo(
            runId: 'r1', awarded: 10, monthLeft: 250)),
      ]);
      await tester.scrollUntilVisible(find.text('+10'), 200);
      expect(find.text('+10'), findsOneWidget);
      expect(find.textContaining('ещё 250 бонусов в лимите этого месяца'),
          findsOneWidget);
      expect(tester.takeException(), isNull);
    });

    testWidgets('прежний сервер: «+45» баллов экосистемы', (tester) async {
      await pump(tester, [
        lastRunPointsProvider.overrideWith((_) => (runId: 'r1', points: 45)),
      ]);
      await tester.scrollUntilVisible(find.text('+45'), 200);
      expect(find.text('+45'), findsOneWidget);
      expect(find.textContaining('баллы экосистемы за бег'), findsOneWidget);
      expect(find.textContaining('лимите'), findsNothing);
    });
  });
}
