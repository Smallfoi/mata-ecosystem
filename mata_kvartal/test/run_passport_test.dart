import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:latlong2/latlong.dart' show LatLng;
import 'package:kvartal_app/features/run/data/completed_runs_provider.dart';
import 'package:kvartal_app/features/run/presentation/screens/run_passport_screen.dart';
import 'package:kvartal_app/features/run/presentation/widgets/run_share.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Паспорт пробежки + Росчерк: сплиты считаются честно из времени точек;
/// карточки собираются; заголовок-вызов появляется только при захвате.
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  CompletedRun mkRun({int points = 4, bool captured = false}) {
    // Прямая «дорожка» на север: 111.32 м на 0.001° широты — точки каждые
    // ~111 м, время каждые 60 с → темп ~9:00, четыре полных км.
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
      capturedZones: captured ? 2 : 0,
      capturedTerritory: captured,
    );
  }

  test('сплиты по километрам считаются из времени точек', () {
    final splits = computeKmSplits(mkRun());
    expect(splits.length, 4);
    for (final s in splits) {
      // ~9 мин на км при шаге ~111 м/мин (гаверсин даёт 9–10 интервалов).
      expect(s, inInclusiveRange(500, 660));
    }
  });

  test('нет времени точек — нет сплитов (не фейкаем)', () {
    final r = mkRun();
    final bare = CompletedRun(
      id: r.id,
      finishedAt: r.finishedAt,
      route: r.route,
      elapsed: r.elapsed,
      distanceMeters: r.distanceMeters,
      capturedZones: 0,
      capturedTerritory: false,
    );
    expect(computeKmSplits(bare), isEmpty);
  });

  testWidgets('паспорт собирается: чипы, кнопки, сплиты', (tester) async {
    SharedPreferences.setMockInitialValues({});
    await tester.pumpWidget(ProviderScope(
      child: MaterialApp(home: RunPassportScreen(run: mkRun(captured: true))),
    ));
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.text('Поделиться пробежкой'), findsOneWidget);
    expect(find.text('Показать на карте'), findsOneWidget);
    expect(find.text('ТЕМП ПО КИЛОМЕТРАМ'), findsOneWidget);
    expect(find.text('ЗАХВАТ'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('карточка Росчерка: вызов при захвате, километры без',
      (tester) async {
    final r = mkRun(captured: true);
    final data = RunShareData(
      route: r.route,
      elapsed: r.elapsed,
      distanceMeters: r.distanceMeters,
      capturedZones: r.capturedZones,
      finishedAt: r.finishedAt,
    );
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: Center(
          child: RunStoryCard(data: data, runner: 'Тест', city: 'Якутск'),
        ),
      ),
    ));
    expect(find.textContaining('Забрал 2'), findsOneWidget);
    expect(find.textContaining('вернуть можно только бегом'), findsOneWidget);

    final free = RunShareData(
      route: r.route,
      elapsed: r.elapsed,
      distanceMeters: r.distanceMeters,
      capturedZones: 0,
      finishedAt: r.finishedAt,
    );
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: Center(
          child: RunStoryCard(data: free, runner: 'Тест', city: null),
        ),
      ),
    ));
    expect(find.text('4.45'), findsOneWidget);
    expect(find.textContaining('Забрал'), findsNothing);
    expect(tester.takeException(), isNull);
  });
}
