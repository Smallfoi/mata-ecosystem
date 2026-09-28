import 'package:flutter_test/flutter_test.dart';
import 'package:kvartal_app/features/loyalty/data/loyalty_provider.dart';
import 'package:kvartal_app/features/profile/presentation/screens/profile_screen.dart';

// Строка кошелька о ещё недоступных баллах (сервер, 28.09.2026: баллы за бег
// созревают 3 дня и замораживаются на время проверки аккаунта).
void main() {
  test('нет несозревших баллов — строки нет (старый сервер)', () {
    expect(pendingPointsLine(const LoyaltyState(balance: 500)), isNull);
  });

  test('ближайшая партия с датой', () {
    final line = pendingPointsLine(
      LoyaltyState(
        pending: 120,
        pendingNextAmount: 120,
        pendingNextAt: DateTime(2026, 10, 2, 9),
      ),
    );
    expect(line, 'ещё 120 баллов станут доступны 02.10');
  });

  test('несколько партий — показываем и общий остаток', () {
    final line = pendingPointsLine(
      LoyaltyState(
        pending: 300,
        pendingNextAmount: 100,
        pendingNextAt: DateTime(2026, 10, 1),
      ),
    );
    expect(line, 'ещё 100 баллов станут доступны 01.10 · всего созревает 300');
  });

  test('аккаунт на проверке — заморозка', () {
    final line = pendingPointsLine(const LoyaltyState(pending: 80, frozen: true));
    expect(line, '80 баллов за бег заморожены до проверки аккаунта');
  });
}
