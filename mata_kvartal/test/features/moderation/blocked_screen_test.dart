import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:kvartal_app/features/moderation/data/moderation_provider.dart';
import 'package:kvartal_app/features/moderation/presentation/blocked_screen.dart';

/// §9 LAUNCH_READINESS: защита от конкретного человека. Экран обязан объяснять,
/// что блокировка делает, и честно говорить, что разблокировка дружбу не вернёт —
/// иначе человек разблокирует «чтобы написать» и удивится.

class _FakeActions extends ModerationActions {
  _FakeActions(super.ref);
  final unblocked = <String>[];

  @override
  Future<bool> unblock(String userId) async {
    unblocked.add(userId);
    return true;
  }
}

Future<_FakeActions> _pump(WidgetTester tester, List<BlockedUser> list) async {
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        blockedProvider.overrideWith((ref) async => list),
        moderationActionsProvider.overrideWith(_FakeActions.new),
      ],
      child: const MaterialApp(home: BlockedScreen()),
    ),
  );
  await tester.pumpAndSettle();
  // Provider ленивый: пока его не прочитали, подмены не существует.
  final container =
      ProviderScope.containerOf(tester.element(find.byType(BlockedScreen)));
  return container.read(moderationActionsProvider) as _FakeActions;
}

void main() {
  testWidgets('пустой список объясняет, где кнопка блокировки', (tester) async {
    await _pump(tester, const []);

    expect(find.text('Никто не заблокирован'), findsOneWidget);
    expect(find.textContaining('в его карточке'), findsOneWidget);
  });

  testWidgets('список предупреждает, что дружба не вернётся', (tester) async {
    await _pump(tester, const [BlockedUser(userId: 'u1', name: 'Борис')]);

    expect(find.text('Борис'), findsOneWidget);
    expect(find.textContaining('не дружбу'), findsOneWidget);
  });

  testWidgets('кнопка снимает блокировку именно с этого человека',
      (tester) async {
    final actions = await _pump(tester, const [
      BlockedUser(userId: 'u1', name: 'Борис'),
      BlockedUser(userId: 'u2', name: 'Виктор'),
    ]);

    await tester.tap(find.text('Разблокировать').last);
    await tester.pump();

    expect(actions.unblocked, ['u2']);
  });
}
