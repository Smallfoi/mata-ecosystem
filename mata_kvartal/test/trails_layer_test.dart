import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:kvartal_app/features/trails/data/trails_layer_provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Слой троп на карте (28.09.2026): тропы — не режим бега, а переключаемый слой.
/// По умолчанию выключен (карта чистая), выбор переживает перезапуск.
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('по умолчанию слой выключен — карта чистая', () async {
    SharedPreferences.setMockInitialValues({});
    final container = ProviderContainer();
    addTearDown(container.dispose);
    expect(container.read(trailsLayerProvider), isFalse);
    await pumpEventQueue();
    expect(container.read(trailsLayerProvider), isFalse);
  });

  test('переключение запоминается между запусками', () async {
    SharedPreferences.setMockInitialValues({});
    final container = ProviderContainer();
    await container.read(trailsLayerProvider.notifier).toggle();
    expect(container.read(trailsLayerProvider), isTrue);
    container.dispose();

    final restarted = ProviderContainer();
    addTearDown(restarted.dispose);
    restarted.read(trailsLayerProvider);
    await pumpEventQueue();
    expect(restarted.read(trailsLayerProvider), isTrue);
  });

  test('второй тап выключает слой обратно', () async {
    SharedPreferences.setMockInitialValues({'kvartal.trails_layer.v1': true});
    final container = ProviderContainer();
    addTearDown(container.dispose);
    container.read(trailsLayerProvider);
    await pumpEventQueue();
    expect(container.read(trailsLayerProvider), isTrue);
    await container.read(trailsLayerProvider.notifier).toggle();
    expect(container.read(trailsLayerProvider), isFalse);
  });
}
