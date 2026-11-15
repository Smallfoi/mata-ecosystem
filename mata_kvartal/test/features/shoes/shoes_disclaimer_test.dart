import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:kvartal_app/features/shoes/data/shoes_provider.dart';
import 'package:kvartal_app/features/shoes/presentation/screens/shoes_screen.dart';

/// §11 `docs/LAUNCH_READINESS.md`: цифра износа — ориентировочная подсказка,
/// а не заключение о состоянии обуви и не медицинский совет. Экран обязан
/// говорить это вслух рядом с цифрами, иначе «Осталось 340 из 800 км» читается
/// как факт.

ShoeAsset _shoe({bool retired = false}) => ShoeAsset(
      id: '1',
      productId: 'p1',
      orderId: 'o1',
      model: 'МАТА Run',
      imageUrl: '',
      status: 'active',
      totalKm: retired ? 620 : 260,
      maxKm: 600,
      remainingKm: retired ? 0 : 340,
      wearPercent: retired ? 100 : 43,
      retired: retired,
    );

/// Подменяем загрузку: настоящая пошла бы в сеть и затёрла бы подготовленное
/// состояние пустым списком (нет токена — нет кроссовок).
class _FixedShoes extends ShoesNotifier {
  _FixedShoes(super.ref, ShoesState initial) {
    state = initial;
  }

  @override
  Future<void> refresh() async {}
}

Future<void> _pumpScreen(WidgetTester tester, ShoesState st) async {
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        shoesProvider.overrideWith((ref) => _FixedShoes(ref, st)),
      ],
      child: const MaterialApp(home: ShoesScreen()),
    ),
  );
  await tester.pump();
}

void main() {
  testWidgets('рядом с цифрами износа стоит оговорка про ориентировочность',
      (tester) async {
    await _pumpScreen(tester, ShoesState(shoes: [_shoe()], loaded: true));

    expect(find.text('Расчёт ориентировочный'), findsOneWidget);
    expect(find.textContaining('от веса, техники бега'), findsOneWidget);
    expect(find.textContaining('не медицинский совет'), findsOneWidget);
  });

  testWidgets('исчерпанный ресурс описан как наш расчёт, а не как износ пары',
      (tester) async {
    await _pumpScreen(
        tester, ShoesState(shoes: [_shoe(retired: true)], loaded: true));

    // «Ресурс исчерпан» — утверждение о самой обуви, которого мы не делали:
    // считали только километры.
    expect(find.textContaining('Ресурс исчерпан'), findsNothing);
    expect(find.textContaining('Ресурс пройден'), findsOneWidget);
    // Замена — решение человека, приложение зовёт посмотреть.
    expect(find.text('Заменить'), findsNothing);
    expect(find.text('Проверить'), findsOneWidget);
  });

  testWidgets('без кроссовок оговорка не маячит — цифр ещё нет',
      (tester) async {
    await _pumpScreen(tester, const ShoesState(loaded: true));

    expect(find.text('Расчёт ориентировочный'), findsNothing);
    expect(find.text('Пока нет кроссовок'), findsOneWidget);
  });
}
