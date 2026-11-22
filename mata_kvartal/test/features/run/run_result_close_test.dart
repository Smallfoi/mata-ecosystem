import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:latlong2/latlong.dart' show LatLng;
import 'package:kvartal_app/features/run/data/completed_runs_provider.dart';
import 'package:kvartal_app/features/run/presentation/screens/run_result_screen.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Экран «Забег завершён» (владелец, 22.11.2026): случайный старт-стоп —
/// крестик сразу, «Пробежки не было» вместо «засчитана», и «Подробнее» не
/// открывает чужую (прошлую) пробежку из истории.
class _Runs extends CompletedRunsNotifier {
  _Runs(super.ref, List<CompletedRun> runs) {
    state = runs;
  }

  @override
  Future<void> load() async {}
}

final _old = CompletedRun(
  id: 'old',
  finishedAt: DateTime(2026, 9, 11, 8, 0),
  route: const [LatLng(62.03, 129.73), LatLng(62.04, 129.74)],
  elapsed: const Duration(minutes: 30),
  distanceMeters: 5000,
  capturedZones: 0,
  capturedTerritory: false,
);

RunResult _result(double meters) => RunResult(
      route: const [],
      elapsed: const Duration(seconds: 5),
      distanceMeters: meters,
      capturedZones: 0,
      capturedTerritory: false,
      finishedAt: DateTime(2026, 11, 22, 17, 0),
      runId: '',
    );

Future<void> _open(WidgetTester tester, RunResult result) async {
  final router = GoRouter(
    initialLocation: '/run/result',
    routes: [
      GoRoute(
        path: '/map',
        builder: (_, __) => const Scaffold(body: Text('главный экран')),
      ),
      GoRoute(
        path: '/run/result',
        builder: (_, __) => RunResultScreen(result: result),
      ),
    ],
  );
  await tester.pumpWidget(ProviderScope(
    overrides: [
      completedRunsProvider.overrideWith((ref) => _Runs(ref, [_old])),
    ],
    child: MaterialApp.router(routerConfig: router),
  ));
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUp(() => SharedPreferences.setMockInitialValues({}));

  testWidgets('крестик сразу закрывает итог и ведёт на главный экран',
      (tester) async {
    await _open(tester, _result(0));
    // Церемония только началась — крестик уже должен работать.
    await tester.pump(const Duration(milliseconds: 100));

    await tester.tap(find.byTooltip('Закрыть'));
    await tester.pumpAndSettle();

    expect(find.text('главный экран'), findsOneWidget);
    expect(find.byType(RunResultScreen), findsNothing);
  });

  testWidgets('старт-стоп за секунды — «Пробежки не было», без лишних кнопок',
      (tester) async {
    await _open(tester, _result(3));
    await tester.pump(const Duration(seconds: 6)); // церемония до конца

    expect(find.text('Пробежки не было'), findsOneWidget);
    expect(find.text('Запись остановлена'), findsOneWidget);
    expect(find.text('Забег завершён'), findsNothing);
    expect(find.text('Пробежка засчитана'), findsNothing);
    expect(find.text('Поделиться'), findsNothing);
    expect(find.text('Подробнее о пробежке'), findsNothing,
        reason: 'нельзя открывать прошлую пробежку вместо несостоявшейся');
    expect(find.text('На карту'), findsOneWidget);
  });

  testWidgets('настоящая пробежка, ещё не в истории — не подсовываем прошлую',
      (tester) async {
    await _open(tester, _result(1200));
    await tester.pump(const Duration(seconds: 6));

    expect(find.text('Пробежка засчитана'), findsOneWidget);
    expect(find.text('Поделиться'), findsOneWidget);
    expect(find.text('Забег завершён'), findsOneWidget);
    expect(find.text('Подробнее о пробежке'), findsNothing);
  });
}
