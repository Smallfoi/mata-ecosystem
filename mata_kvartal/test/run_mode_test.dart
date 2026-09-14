import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:kvartal_app/features/run/data/run_mode_provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Режим пробежки: четыре режима (14.09.2026), ОСНОВНОЙ — «Свободный» (трекер,
/// по умолчанию), любой другой выбирается одним тапом и переживает перезапуск
/// приложения. Ключ хранилища поднят до v3.
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('ровно четыре режима, свободный — первый', () {
    expect(RunMode.values, [
      RunMode.free,
      RunMode.capture,
      RunMode.trails,
      RunMode.explore,
    ]);
    // У каждого режима есть непустая подпись.
    for (final m in RunMode.values) {
      expect(m.label, isNotEmpty);
    }
  });

  test('по умолчанию — свободная пробежка (трекер)', () async {
    SharedPreferences.setMockInitialValues({});
    final container = ProviderContainer();
    addTearDown(container.dispose);
    expect(container.read(runModeProvider), RunMode.free);
    await pumpEventQueue();
    expect(container.read(runModeProvider), RunMode.free);
  });

  test('выбор режима переживает перезапуск (v3)', () async {
    SharedPreferences.setMockInitialValues({});
    final container = ProviderContainer();
    await container.read(runModeProvider.notifier).set(RunMode.trails);
    expect(container.read(runModeProvider), RunMode.trails);
    container.dispose();

    // «Перезапуск»: новый контейнер поднимает контроллер заново
    // и дочитывает сохранённый выбор из того же хранилища (ключ v3).
    final restarted = ProviderContainer();
    addTearDown(restarted.dispose);
    restarted.read(runModeProvider);
    await pumpEventQueue();
    expect(restarted.read(runModeProvider), RunMode.trails);
  });

  test('старый ключ v2 больше не читается — новый дефолт применяется всем',
      () async {
    // На v2 у пользователя мог остаться «захват»; на v3 это игнорируется и
    // включается новый основной режим — свободный.
    SharedPreferences.setMockInitialValues({
      'kvartal.run_mode.v2': 'capture',
    });
    final container = ProviderContainer();
    addTearDown(container.dispose);
    container.read(runModeProvider);
    await pumpEventQueue();
    expect(container.read(runModeProvider), RunMode.free);
  });

  test('мусор в хранилище не ломает режим — откат на свободный', () async {
    SharedPreferences.setMockInitialValues({
      'kvartal.run_mode.v3': 'nonsense',
    });
    final container = ProviderContainer();
    addTearDown(container.dispose);
    container.read(runModeProvider);
    await pumpEventQueue();
    expect(container.read(runModeProvider), RunMode.free);
  });
}
