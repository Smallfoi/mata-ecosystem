import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Режим пробежки (директива владельца 05.09.2026: приложение — для всех).
///
/// «Захват» — территориальная игра: замкнул контур — забрал квартал.
/// «Свободная» — чистый бег без риторики захвата: темп, дистанция, время.
/// Километры в обоих режимах одинаково идут в дивизион, зачёты, стрик и баллы —
/// свободный режим прячет только сам захват, ничего не отнимая.
enum RunMode { capture, free }

extension RunModeLabel on RunMode {
  String get label => switch (this) {
    RunMode.capture => 'Захват',
    RunMode.free => 'Свободная',
  };
}

class RunModeController extends StateNotifier<RunMode> {
  RunModeController() : super(RunMode.capture) {
    _load();
  }

  static const _prefsKey = 'kvartal.run_mode.v1';

  Future<void> _load() async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString(_prefsKey);
    if (raw == null || !mounted) return;
    state = RunMode.values.firstWhere(
      (e) => e.name == raw,
      orElse: () => RunMode.capture,
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
