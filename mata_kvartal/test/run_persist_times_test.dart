import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:kvartal_app/features/run/data/run_provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Времена точек обязаны переживать перезапуск процесса вместе с маршрутом
/// (реальный баг: 44-минутная пробежка с погашенным экраном теряла времена —
/// молчали сплиты паспорта и тропы).
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('restore возвращает routeTimes той же длины, что маршрут', () async {
    final times = [for (var i = 0; i < 5; i++) 1757000000000 + i * 60000];
    SharedPreferences.setMockInitialValues({
      activeRunStorageKey: jsonEncode({
        'schemaVersion': activeRunSchemaVersion,
        'status': 'paused',
        'elapsedSeconds': 300,
        'distanceMeters': 555.0,
        'savedAtMs': 1757000300000,
        'route': [
          for (var i = 0; i < 5; i++) [62.0 + i * .001, 129.7],
        ],
        'routeTimes': times,
      }),
    });
    final container = ProviderContainer();
    addTearDown(container.dispose);
    container.read(runProvider.notifier);
    await pumpEventQueue(times: 20);
    final s = container.read(runProvider);
    expect(s.route.length, 5);
    expect(s.routeTimes, times);
  });

  test('битые времена (не та длина) отбрасываются, маршрут остаётся',
      () async {
    SharedPreferences.setMockInitialValues({
      activeRunStorageKey: jsonEncode({
        'schemaVersion': activeRunSchemaVersion,
        'status': 'paused',
        'elapsedSeconds': 300,
        'distanceMeters': 555.0,
        'savedAtMs': 1757000300000,
        'route': [
          for (var i = 0; i < 5; i++) [62.0 + i * .001, 129.7],
        ],
        'routeTimes': [1, 2],
      }),
    });
    final container = ProviderContainer();
    addTearDown(container.dispose);
    container.read(runProvider.notifier);
    await pumpEventQueue(times: 20);
    final s = container.read(runProvider);
    expect(s.route.length, 5);
    expect(s.routeTimes, isEmpty);
  });
}
