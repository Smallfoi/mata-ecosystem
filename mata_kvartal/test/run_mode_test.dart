import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:kvartal_app/features/run/data/run_mode_provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Режим пробежки: три режима (28.09.2026 «Тропы» перестали быть режимом —
/// зачёт троп идёт после любой пробежки). ОСНОВНОЙ — «Свободный» (трекер, по
/// умолчанию), любой другой выбирается одним тапом и переживает перезапуск
/// приложения. Ключ хранилища поднят до v4.
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('ровно три режима, свободный — первый', () {
    expect(RunMode.values, [RunMode.free, RunMode.capture, RunMode.explore]);
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

  test('выбор режима переживает перезапуск (v4)', () async {
    SharedPreferences.setMockInitialValues({});
    final container = ProviderContainer();
    await container.read(runModeProvider.notifier).set(RunMode.explore);
    expect(container.read(runModeProvider), RunMode.explore);
    container.dispose();

    // «Перезапуск»: новый контейнер поднимает контроллер заново
    // и дочитывает сохранённый выбор из того же хранилища (ключ v4).
    final restarted = ProviderContainer();
    addTearDown(restarted.dispose);
    restarted.read(runModeProvider);
    await pumpEventQueue();
    expect(restarted.read(runModeProvider), RunMode.explore);
  });

  test('старый ключ v3 больше не читается — новый дефолт применяется всем',
      () async {
    // На v3 у пользователя мог остаться «захват»; на v4 это игнорируется и
    // включается основной режим — свободный.
    SharedPreferences.setMockInitialValues({
      'kvartal.run_mode.v3': 'capture',
    });
    final container = ProviderContainer();
    addTearDown(container.dispose);
    container.read(runModeProvider);
    await pumpEventQueue();
    expect(container.read(runModeProvider), RunMode.free);
  });

  test('сохранённые «Тропы» не ломают приложение — откат на свободный',
      () async {
    // Ключ v4 новый, но подстрахуемся: если в него каким-то образом попал
    // упразднённый режим, приложение обязано открыться на свободном.
    SharedPreferences.setMockInitialValues({
      'kvartal.run_mode.v4': 'trails',
    });
    final container = ProviderContainer();
    addTearDown(container.dispose);
    container.read(runModeProvider);
    await pumpEventQueue();
    expect(container.read(runModeProvider), RunMode.free);
  });

  test('мусор в хранилище не ломает режим — откат на свободный', () async {
    SharedPreferences.setMockInitialValues({
      'kvartal.run_mode.v4': 'nonsense',
    });
    final container = ProviderContainer();
    addTearDown(container.dispose);
    container.read(runModeProvider);
    await pumpEventQueue();
    expect(container.read(runModeProvider), RunMode.free);
  });
}
