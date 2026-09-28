import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:sport_store/data/repositories/loyalty_repository.dart';
import 'package:sport_store/models/loyalty.dart';
import 'package:sport_store/providers/loyalty_provider.dart';

// Сервер с 28.09.2026: баллы за бег созревают 3 дня (и замораживаются на время
// проверки аккаунта). `balance` — тратимые, остальное — в `pending`.
class _Repo implements LoyaltyRepository {
  LoyaltyAccount account = const LoyaltyAccount();

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
}

LoyaltyTransaction _tx(int amount) => LoyaltyTransaction(
      id: 't$amount',
      amount: amount,
      source: LoyaltySource.runnerRun,
      description: 'Пробежка',
      createdAt: DateTime(2026, 9, 28),
    );

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  Future<LoyaltyProvider> load(LoyaltyAccount acc) async {
    final repo = _Repo()..account = acc;
    final p = LoyaltyProvider(
      await SharedPreferences.getInstance(),
      repo,
      serverBacked: true,
    );
    await p.syncAuth(true, userId: 'u1');
    return p;
  }

  test('тратим только доступное, уровень — по всему накопленному', () async {
    final p = await load(LoyaltyAccount(
      balance: 100,
      total: 400,
      pending: 300,
      pendingNextAmount: 300,
      pendingNextAt: DateTime(2026, 10, 1),
      transactions: [_tx(400)],
    ));
    expect(p.balance, 100);
    expect(p.level, LoyaltyLevel.silver);
    expect(p.maxRedeemable(10000), 100);
    expect(p.pendingLine, 'ещё 300 баллов станут доступны 01.10');
  });

  test('заморозка на время проверки', () async {
    final p = await load(LoyaltyAccount(
      balance: 0,
      total: 150,
      pending: 150,
      frozen: true,
      transactions: [_tx(150)],
    ));
    expect(p.balance, 0);
    expect(p.maxRedeemable(10000), 0);
    expect(p.pendingLine, '150 баллов за бег заморожены до проверки аккаунта');
  });

  test('старый сервер без новых полей — как раньше, по истории', () async {
    final p = await load(LoyaltyAccount(balance: 250, transactions: [_tx(250)]));
    expect(p.balance, 250);
    expect(p.pendingLine, isNull);
  });
}
