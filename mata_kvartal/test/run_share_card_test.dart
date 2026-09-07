import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:kvartal_app/features/medals/data/medal_defs.dart';
import 'package:kvartal_app/features/medals/data/medals_provider.dart';
import 'package:kvartal_app/features/run/presentation/widgets/run_share.dart';
import 'package:latlong2/latlong.dart';

/// Карточка пробежки v2 «Выше Стравы» (утверждена 06.09.2026): строка стат
/// вместо чипов, погода у даты, медаль забега настоящим штампом, при захвате —
/// заголовок-вызов; пустые слоты (нет баллов/температуры) честно скрыты.
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  // Зигзаг ~4,4 км по Якутску: хватает и на км-точки росчерка.
  final route = [
    for (var i = 0; i <= 40; i++)
      LatLng(62.03 + i * .001, 129.73 + (i % 7) * .0012),
  ];

  RunShareData data({int zones = 0, int? temperatureC}) => RunShareData(
        route: route,
        elapsed: const Duration(minutes: 32, seconds: 10),
        distanceMeters: 5030,
        capturedZones: zones,
        finishedAt: DateTime(2026, 9, 6, 12, 40),
        temperatureC: temperatureC,
      );

  Widget host(Widget child) => MaterialApp(
        home: Scaffold(body: Center(child: child)),
      );

  testWidgets('свободная пробежка: км-герой, статы строкой, баллы, погода',
      (tester) async {
    await tester.pumpWidget(host(RunStoryCard(
      data: data(temperatureC: -2),
      runner: 'Михаил Татаринов',
      city: 'Якутск',
      points: 120,
    )));
    expect(find.text('5.03'), findsOneWidget);
    expect(find.text('+120'), findsOneWidget);
    expect(find.text('БАЛЛОВ'), findsOneWidget);
    expect(find.text('ВРЕМЯ'), findsOneWidget);
    expect(
        find.textContaining('-2°C', findRichText: true), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('захват: заголовок-вызов и +N кварталов лаймом', (tester) async {
    await tester.pumpWidget(host(RunStoryCard(
      data: data(zones: 3),
      runner: 'Михаил Татаринов',
      city: 'Якутск',
    )));
    expect(find.text('Забрал 3 квартала'), findsOneWidget);
    expect(find.text('+3'), findsOneWidget);
    expect(find.text('КВАРТАЛА'), findsOneWidget);
    // Баллы неизвестны — слота нет, врать нельзя.
    expect(find.text('БАЛЛОВ'), findsNothing);
    expect(tester.takeException(), isNull);
  });

  testWidgets('медаль забега — настоящим штампом на карточке', (tester) async {
    final medal = MedalFull(
      medalById('d_run_5k'),
      const MedalState(
        id: 'd_run_5k',
        available: true,
        earnedAtMs: 1757000000000,
        engraving: (v: '43:50', u: 'ЛИЧНОЕ ВРЕМЯ', sub: '05.09.2026'),
      ),
    );
    await tester.pumpWidget(host(RunStoryCard(
      data: data(),
      runner: 'Михаил Татаринов',
      medal: medal,
    )));
    expect(
      find.textContaining('МЕДАЛЬ «5 КМ» — ВЗЯТА В ЭТОМ ЗАБЕГЕ'),
      findsOneWidget,
    );
    expect(find.textContaining('личное время 43:50'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
