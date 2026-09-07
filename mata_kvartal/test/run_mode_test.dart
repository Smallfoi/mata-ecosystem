import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:kvartal_app/features/run/data/run_mode_provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Режим пробежки: «Захват» по умолчанию (поведение до фичи не меняется),
/// «Свободная» выбирается одним тапом и переживает перезапуск приложения.
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('по умолчанию — режим захвата', () async {
    SharedPreferences.setMockInitialValues({});
    final container = ProviderContainer();
    addTearDown(container.dispose);
    expect(container.read(runModeProvider), RunMode.capture);
    await pumpEventQueue();
    expect(container.read(runModeProvider), RunMode.capture);
  });

  test('выбор «Свободная» переживает перезапуск', () async {
    SharedPreferences.setMockInitialValues({});
    final container = ProviderContainer();
    await container.read(runModeProvider.notifier).set(RunMode.free);
    expect(container.read(runModeProvider), RunMode.free);
    container.dispose();

    // «Перезапуск»: новый контейнер поднимает контроллер заново
    // и дочитывает сохранённый выбор из того же хранилища.
    final restarted = ProviderContainer();
    addTearDown(restarted.dispose);
    restarted.read(runModeProvider);
    await pumpEventQueue();
    expect(restarted.read(runModeProvider), RunMode.free);
  });

  test('мусор в хранилище не ломает режим — откат на захват', () async {
    SharedPreferences.setMockInitialValues({
      'kvartal.run_mode.v1': 'nonsense',
    });
    final container = ProviderContainer();
    addTearDown(container.dispose);
    container.read(runModeProvider);
    await pumpEventQueue();
    expect(container.read(runModeProvider), RunMode.capture);
  });
}
