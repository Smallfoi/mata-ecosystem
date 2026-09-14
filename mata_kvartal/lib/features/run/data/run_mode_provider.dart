import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Режим пробежки. ОСНОВНОЙ — свободная пробежка (трекер): работает круглый год
/// везде (улица/манеж/любой регион), не зависит от уличной GPS-петли. Захват —
/// второстепенный сезонно-погодный слой (директива владельца 14.09.2026: в Якутске
/// зимой захват не работает, трекер — да, поэтому трекер берём за основу).
///
/// «Свободная» — чистый бег: темп, дистанция, время. По умолчанию и первой в выборе.
/// «Захват» — территориальная игра поверх бега: замкнул контур — забрал квартал.
/// Километры в обоих режимах одинаково идут в дивизион, зачёты, стрик и баллы —
/// свободный режим прячет только сам захват, ничего не отнимая.
enum RunMode { free, capture }

extension RunModeLabel on RunMode {
  String get label => switch (this) {
    RunMode.free => 'Свободная',
    RunMode.capture => 'Захват',
  };
}

class RunModeController extends StateNotifier<RunMode> {
  RunModeController() : super(RunMode.free) {
    _load();
  }

  // v2: смена основного режима на «Свободную» (14.09.2026) — сбрасываем прежний
  // сохранённый выбор, чтобы новый дефолт применился ко всем.
  static const _prefsKey = 'kvartal.run_mode.v2';

  Future<void> _load() async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString(_prefsKey);
    if (raw == null || !mounted) return;
    state = RunMode.values.firstWhere(
      (e) => e.name == raw,
      orElse: () => RunMode.free,
    );
  }

  Future<void> set(RunMode mode) async {
    state = mode;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_prefsKey, mode.name);
  }
}

final runModeProvider = StateNotifierProvider<RunModeController, RunMode>(
  (ref) => RunModeController(),
);
