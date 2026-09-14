import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:kvartal_app/features/run/data/run_mode_provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Режим пробежки: ОСНОВНОЙ — «Свободная» (трекер, по умолчанию, 14.09.2026),
/// «Захват» выбирается одним тапом и переживает перезапуск приложения.
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('по умолчанию — свободная пробежка (трекер)', () async {
    SharedPreferences.setMockInitialValues({});
    final container = ProviderContainer();
    addTearDown(container.dispose);
    expect(container.read(runModeProvider), RunMode.free);
    await pumpEventQueue();
    expect(container.read(runModeProvider), RunMode.free);
  });

  test('выбор «Захват» переживает перезапуск', () async {
    SharedPreferences.setMockInitialValues({});
    final container = ProviderContainer();
    await container.read(runModeProvider.notifier).set(RunMode.capture);
    expect(container.read(runModeProvider), RunMode.capture);
    container.dispose();

    // «Перезапуск»: новый контейнер поднимает контроллер заново
    // и дочитывает сохранённый выбор из того же хранилища.
    final restarted = ProviderContainer();
    addTearDown(restarted.dispose);
    restarted.read(runModeProvider);
    await pumpEventQueue();
    expect(restarted.read(runModeProvider), RunMode.capture);
  });

  test('мусор в хранилище не ломает режим — откат на свободную', () async {
    SharedPreferences.setMockInitialValues({
      'kvartal.run_mode.v2': 'nonsense',
    });
    final container = ProviderContainer();
    addTearDown(container.dispose);
    container.read(runModeProvider);
    await pumpEventQueue();
    expect(container.read(runModeProvider), RunMode.free);
  });
}
