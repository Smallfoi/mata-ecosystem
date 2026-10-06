import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:sport_store/data/api/api_client.dart';
import 'package:sport_store/data/repositories/loyalty_repository.dart';
import 'package:sport_store/models/app_notification.dart';
import 'package:sport_store/models/loyalty.dart';
import 'package:sport_store/providers/loyalty_provider.dart';

// Программа лояльности v1 (ТЗ 30.09.2026), этап 3 — клиент Store.
// Ответы — в том виде, как их отдаёт сервер (loyalty/views.py).

const _levels = [
  {'key': 'basic', 'title': 'Базовый', 'threshold': 0, 'minSpend': 0,
   'purchaseRate': 0.05, 'redeemCeiling': 0.15, 'expiryMonths': 6},
  {'key': 'silver', 'title': 'Серебро', 'threshold': 500, 'minSpend': 0,
   'purchaseRate': 0.06, 'redeemCeiling': 0.2, 'expiryMonths': 12},
  {'key': 'gold', 'title': 'Золото', 'threshold': 2000, 'minSpend': 0,
   'purchaseRate': 0.07, 'redeemCeiling': 0.25, 'expiryMonths': 12},
  {'key': 'platinum', 'title': 'Платина', 'threshold': 5000, 'minSpend': 60000,
   'purchaseRate': 0.09, 'redeemCeiling': 0.3, 'expiryMonths': 18},
];

Map<String, dynamic> _v1Account({
  int available = 250,
  int redeemable = 250,
  int held = 375,
  int status = 320,
  int purchases = 7500,
  String level = 'basic',
  int levelIndex = 0,
  int? next = 500,
  double ceiling = 0.15,
  bool withLevels = true,
}) =>
    {
      'balance': redeemable,
      'total': available + held,
      'pending': held,
      'level': level,
      'code': '123456',
      'transactions': [],
      'programV1': true,
      'v1': {
        'available': available,
        'redeemable': redeemable,
        'held': held,
        'statusPoints': status,
        'purchases365': purchases,
        'level': level,
        'levelIndex': levelIndex,
        'levelUntil': '2027-10-01T00:00:00+09:00',
        'nextLevelThreshold': next,
        'platinumMinSpend': 60000,
        'redeemMin': 300,
        'redeemCeiling': ceiling,
        'heldNextAt': '2026-10-20T12:00:00+09:00',
        'heldNextAmount': 375,
        'expiringAt': '2027-03-01T00:00:00+09:00',
        'expiringAmount': 250,
        if (withLevels) 'levels': _levels,
        'lots': [
          {'id': 1, 'amount': 250, 'remaining': 250, 'state': 'available',
           'source': 'migration', 'accruedAt': '2026-09-01T00:00:00+09:00',
           'availableAt': null, 'expiresAt': '2027-03-01T00:00:00+09:00'},
          {'id': 2, 'amount': 375, 'remaining': 375, 'state': 'held',
           'source': 'purchase', 'accruedAt': '2026-10-06T00:00:00+09:00',
           'availableAt': '2026-10-20T12:00:00+09:00',
           'expiresAt': '2027-04-06T00:00:00+09:00'},
        ],
      },
    };

ApiLoyaltyRepository _repo(Map<String, Object> routes) {
  final client = MockClient((req) async {
    final body = routes[req.url.path.replaceFirst(RegExp(r'^/v1'), '')];
    if (body == null) return http.Response('{"detail":"нет"}', 404);
    return http.Response.bytes(utf8.encode(jsonEncode(body)), 200,
        headers: {'content-type': 'application/json; charset=utf-8'});
  });
  return ApiLoyaltyRepository(ApiClient(client: client));
}

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  group('аккаунт v1', () {
    test('парсинг новых полей: доступно, уровень, шкалы, лоты', () async {
      final acc = await _repo({'/loyalty/account': _v1Account()}).fetchAccount();
      final v = acc.v1!;
      expect(acc.programV1, isTrue);
      expect(acc.level, LoyaltyLevel.basic);
      expect(v.availableText, 'Доступно 250 бонусов');
      expect(v.belowRedeemMin, isTrue);
      expect(v.redeemMinText, 'Списание от 300: накоплено 250 из 300');
      expect(v.levelScaleText, 'до Серебра: 320 из 500 статусных');
      expect(v.levelProgress, closeTo(0.64, 1e-9));
      expect(v.showSpendScale, isFalse);
      expect(v.perkText, '5% бонусами с покупок · оплата бонусами до 15% заказа');
      expect(v.ceilingChip, 'оплата до 15%');
      expect(v.heldLine, 'ещё 375 бонусов станут доступны 20.10');
      expect(v.expiringLine, '250 бонусов сгорят 01.03.2027');
      expect(v.debtLine, isNull);
      expect(v.lots, hasLength(2));
      expect(v.lots[0].sourceLabel, 'Перенос баланса');
      expect(v.lots[0].dateLine, 'сгорят 01.03.2027');
      expect(v.lots[1].dateLine, 'ожидает · доступно с 20.10.2026');
    });

    test('пороги — с сервера, не из сборки', () async {
      final data = _v1Account(status: 1200, next: 1500); // владелец сменил порог
      final v = (await _repo({'/loyalty/account': data}).fetchAccount()).v1!;
      expect(v.levelScaleText, 'до Серебра: 1 200 из 1 500 статусных');
    });

    test('Золото → на пути к Платине две шкалы', () async {
      final v = (await _repo({
        '/loyalty/account': _v1Account(
            level: 'gold', levelIndex: 2, status: 3200, next: 5000,
            purchases: 12300, ceiling: 0.25, redeemable: 900, available: 900),
      }).fetchAccount())
          .v1!;
      expect(v.belowRedeemMin, isFalse);
      expect(v.levelScaleText, 'до Платины: 3 200 из 5 000 статусных');
      expect(v.showSpendScale, isTrue);
      expect(v.spendScaleText, 'покупки за год: 12 300 из 60 000 ₽');
      expect(v.spendProgress, closeTo(0.205, 1e-9));
    });

    test('Платина — максимальный уровень со сроком', () async {
      final v = (await _repo({
        '/loyalty/account': _v1Account(
            level: 'platinum', levelIndex: 3, status: 5100, next: null,
            ceiling: 0.3),
      }).fetchAccount())
          .v1!;
      expect(v.nextLevel, isNull);
      expect(v.levelScaleText, 'Максимальный уровень · до 01.10.2027');
      expect(v.showSpendScale, isFalse);
    });

    test('без таблицы уровней — привилегия только из потолка', () async {
      final v = (await _repo({
        '/loyalty/account': _v1Account(withLevels: false, ceiling: 0.2),
      }).fetchAccount())
          .v1!;
      expect(v.perkText, 'оплата бонусами до 20% заказа');
    });

    test('долг после возврата', () async {
      final v = (await _repo({
        '/loyalty/account': _v1Account(available: -120, redeemable: 0),
      }).fetchAccount())
          .v1!;
      expect(v.spendable, 0);
      expect(v.debtLine,
          'Долг 120 бонусов — погасится следующими начислениями');
    });

    test('провайдер: уровень и строка удержания из v1', () async {
      final p = LoyaltyProvider(await SharedPreferences.getInstance(),
          _repo({'/loyalty/account': _v1Account()}),
          serverBacked: true);
      await p.syncAuth(true, userId: 'u1');
      expect(p.programV1, isTrue);
      expect(p.balance, 250);
      expect(p.level, LoyaltyLevel.basic);
      expect(p.pendingLine, 'ещё 375 бонусов станут доступны 20.10');
    });
  });

  group('прежний сервер (новых полей нет)', () {
    test('аккаунт без programV1 — как раньше', () async {
      final acc = await _repo({
        '/loyalty/account': {
          'balance': 600, 'total': 600, 'level': 'gold', 'code': '1',
          'transactions': [],
        },
      }).fetchAccount();
      expect(acc.v1, isNull);
      expect(acc.programV1, isFalse);
      expect(acc.level, LoyaltyLevel.gold); // прежние пороги 200/500/1000
      expect(acc.maxRedeemable(1000), 300); // 30%
    });

    test('programV1: false — блок v1 игнорируется', () async {
      final data = _v1Account()..['programV1'] = false;
      final acc = await _repo({'/loyalty/account': data}).fetchAccount();
      expect(acc.v1, isNull);
    });

    test('превью кассы: 404 у старого сервера → null (прежние правила)', () async {
      final pv = await _repo({}).redeemPreview([
        {'productId': 'x', 'quantity': 1},
      ]);
      expect(pv, isNull);
    });

    test('превью при выключенной программе — programV1 false', () async {
      final pv = await _repo({
        '/loyalty/redeem-preview': {
          'programV1': false, 'available': 400, 'redeemMin': 50, 'maxPercent': 30,
        },
      }).redeemPreview([]);
      expect(pv!.programV1, isFalse);
    });
  });

  group('превью кассы v1', () {
    RedeemPreview pv(Map<String, dynamic> j) => RedeemPreview.fromJson(j);

    final ok = {
      'programV1': true, 'level': 'platinum', 'available': 5000,
      'eligibleTotal': 7000.0, 'ceiling': 0.3, 'redeemMax': 2100,
      'redeemMin': 300, 'canRedeem': true, 'reason': '',
      'lines': [
        {'index': 0, 'productId': 'shoe', 'eligible': true, 'reason': ''},
        {'index': 1, 'productId': 'gel', 'eligible': false,
         'reason': 'excluded_category'},
        {'index': 2, 'productId': 'old', 'eligible': false, 'reason': 'markdown'},
      ],
    };

    test('максимум, недопущенные позиции, цена с бонусами', () {
      final p = pv(ok);
      expect(p.programV1, isTrue);
      expect(p.redeemMax, 2100);
      expect(p.lineNote(0), isNull);
      expect(p.lineNote(1), 'не оплачивается бонусами');
      expect(p.lineNote(2), 'уценка — без оплаты бонусами');
      expect(priceWithBonuses(5250, 2250), '5 250 ₽ + 2 250 бонусов');
      expect(priceWithBonuses(5250, 0), '5 250 ₽');
    });

    test('ползунок: 0..redeemMax, меньше минимума нельзя', () {
      final p = pv(ok);
      expect(p.snap(0), 0);
      expect(p.snap(100), 0);
      expect(p.snap(200), 300);
      expect(p.snap(1000), 1000);
      expect(p.snap(99999), 2100);
    });

    test('redeemMax < минимума — неактивно с пояснением сервера', () {
      final p = pv({
        'programV1': true, 'available': 250, 'eligibleTotal': 3000.0,
        'ceiling': 0.2, 'redeemMax': 250, 'redeemMin': 300, 'canRedeem': false,
        'reason': 'Списать бонусы можно от 300: сейчас доступно 250',
        'lines': [],
      });
      expect(p.canRedeem, isFalse);
      expect(p.snap(250), 0);
      expect(p.disabledText, 'Списать бонусы можно от 300: сейчас доступно 250');
    });
  });

  test('уведомления лояльности (level/system) попадают в ленту', () {
    for (final type in ['level', 'system']) {
      final n = AppNotification.fromJson({
        'id': '5', 'title': 'Бонусы доступны', 'body': '375 бонусов за покупку',
        'type': type, 'orderId': null, 'read': false,
        'createdAt': '2026-10-20T12:00:00+09:00',
      });
      expect(n.type, NotifType.system);
      expect(n.title, 'Бонусы доступны');
    }
  });
}
