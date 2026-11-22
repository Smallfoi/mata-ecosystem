import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:kvartal_app/features/run/presentation/screens/run_result_screen.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Владелец, 22.11.2026: случайно нажал «старт» и сразу «стоп» — на экране
/// «Забег завершён» смотреть нечего, а выйти можно было только «На карту»
/// после церемонии. Нужен крестик, работающий сразу.
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUp(() => SharedPreferences.setMockInitialValues({}));

  testWidgets('крестик сразу закрывает итог и ведёт на главный экран',
      (tester) async {
    final router = GoRouter(
      initialLocation: '/run/result',
      routes: [
        GoRoute(
          path: '/map',
          builder: (_, __) => const Scaffold(body: Text('главный экран')),
        ),
        GoRoute(
          path: '/run/result',
          builder: (_, __) => RunResultScreen(
            result: RunResult(
              route: const [],
              elapsed: const Duration(seconds: 2),
              distanceMeters: 0,
              capturedZones: 0,
              capturedTerritory: false,
              finishedAt: DateTime(2026, 11, 22, 17, 0),
              runId: '',
            ),
          ),
        ),
      ],
    );
    await tester.pumpWidget(
      ProviderScope(child: MaterialApp.router(routerConfig: router)),
    );
    // Церемония только началась — крестик уже должен работать.
    await tester.pump(const Duration(milliseconds: 100));

    await tester.tap(find.byTooltip('Закрыть'));
    await tester.pumpAndSettle();

    expect(find.text('главный экран'), findsOneWidget);
    expect(find.byType(RunResultScreen), findsNothing);
  });
}
