// Прямое подключение часов (22.11.2026): карточки Suunto и COROS. Состояние
// подменено — сеть и вход не нужны.
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:kvartal_app/features/workouts/data/watch_brand_provider.dart';
import 'package:kvartal_app/features/workouts/presentation/screens/watch_sync_screen.dart';

class _Fake extends WatchController {
  _Fake(super.ref, super.brand, WatchState initial) {
    state = initial;
  }

  int connects = 0;

  @override
  Future<void> refresh() async {}

  @override
  Future<void> connect() async => connects++;
}

final _fakes = <String, _Fake>{};

Future<void> _pump(WidgetTester tester, Map<String, WatchState> states) async {
  _fakes.clear();
  await tester.pumpWidget(ProviderScope(
    overrides: [
      watchBrandProvider.overrideWith((ref, brand) =>
          _fakes[brand.source] = _Fake(ref, brand, states[brand.source] ?? const WatchState())),
    ],
    child: const MaterialApp(
      home: Scaffold(
        body: Column(children: [
          WatchBrandCard(WatchBrand.suunto),
          WatchBrandCard(WatchBrand.coros),
        ]),
      ),
    ),
  ));
  await tester.pump();
}

void main() {
  testWidgets('обе марки доступны — две кнопки подключения', (tester) async {
    await _pump(tester, {
      'suunto': const WatchState(available: true),
      'coros': const WatchState(available: true),
    });
    expect(find.text('Подключить Suunto'), findsOneWidget);
    expect(find.text('Подключить COROS'), findsOneWidget);

    await tester.tap(find.text('Подключить').last);
    await tester.pump();
    expect(_fakes['coros']!.connects, 1);
    expect(_fakes['suunto']!.connects, 0);
  });

  testWidgets('марка не готова на сервере — её карточки нет', (tester) async {
    await _pump(tester, {'coros': const WatchState(available: true)});
    expect(find.textContaining('Suunto'), findsNothing);
    expect(find.text('Подключить COROS'), findsOneWidget);
  });

  testWidgets('подключено — видно, и видна причина ошибки', (tester) async {
    await _pump(tester, {
      'coros': const WatchState(available: true, connected: true, error: 'Не удалось отключить часы'),
    });
    expect(find.text('Часы COROS подключены'), findsOneWidget);
    expect(find.text('тренировок ещё не приходило'), findsOneWidget);
    expect(find.text('Не удалось отключить часы'), findsOneWidget);
  });
}
