import 'package:flutter_test/flutter_test.dart';
import 'package:kvartal_app/features/club/presentation/screens/club_screen.dart';

/// Шапка клуба писала «1 участников» (телефон владельца, 22.11.2026).
void main() {
  test('склонение «участник»', () {
    expect(membersWord(1), 'участник');
    expect(membersWord(21), 'участник');
    expect(membersWord(3), 'участника');
    expect(membersWord(5), 'участников');
    expect(membersWord(11), 'участников');
    expect(membersWord(12), 'участников');
    expect(membersWord(0), 'участников');
  });
}
