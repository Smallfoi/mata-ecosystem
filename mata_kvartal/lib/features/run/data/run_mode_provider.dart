import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Режим пробежки. ОСНОВНОЙ — свободная пробежка (трекер): работает круглый год
/// везде (улица/манеж/любой регион), не зависит от уличной GPS-петли. Захват —
/// второстепенный сезонно-погодный слой (директива владельца 14.09.2026: в Якутске
/// зимой захват не работает, трекер — да, поэтому трекер берём за основу).
///
/// Четыре режима бега; под каждый перестраивается карта (вкладка «Карта»,
/// утверждено владельцем 14.09.2026):
/// - «Свободный» — чистый бег: темп, дистанция, время. Карта пустая. По
///   умолчанию и первым в выборе.
/// - «Захват» — территориальная игра поверх бега: замкнул контур — забрал
///   квартал. На карте — маршруты районов (данные троп); владение/легенда —
///   отдельная серверная фаза позже.
/// - «Тропы» — на карте маршруты-тропы, тап ведёт в детали тропы.
/// - «Исследование» — карта затемняется «туманом», ярко открыто только
///   пробеганное (footprints).
///
/// Километры во всех режимах одинаково идут в дивизион, зачёты, стрик и баллы —
/// режим меняет только карту и то, предлагаем ли захват на финише.
enum RunMode { free, capture, trails, explore }

extension RunModeLabel on RunMode {
  String get label => switch (this) {
    RunMode.free => 'Свободный',
    RunMode.capture => 'Захват',
    RunMode.trails => 'Тропы',
    RunMode.explore => 'Исследование',
  };
}

class RunModeController extends StateNotifier<RunMode> {
  RunModeController() : super(RunMode.free) {
    _load();
  }

  // v3: расширение до 4 режимов (14.09.2026) — поднимаем ключ, чтобы прежний
  // сохранённый выбор («захват»/«свободная» на v2) не мешал новому дефолту.
  static const _prefsKey = 'kvartal.run_mode.v3';

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
