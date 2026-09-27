import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Режим пробежки. ОСНОВНОЙ — свободная пробежка (трекер): работает круглый год
/// везде (улица/манеж/любой регион), не зависит от уличной GPS-петли. Захват —
/// второстепенный сезонно-погодный слой (директива владельца 14.09.2026: в Якутске
/// зимой захват не работает, трекер — да, поэтому трекер берём за основу).
///
/// ТРИ режима бега; под каждый перестраивается карта (вкладка «Карта»):
/// - «Свободный» — чистый бег: темп, дистанция, время. Карта пустая. По
///   умолчанию и первым в выборе.
/// - «Захват» — территориальная игра поверх бега: замкнул контур — забрал
///   квартал.
/// - «Исследование» — карта затемняется «туманом», ярко открыто только
///   пробеганное (footprints).
///
/// Тропы режимом НЕ являются (решение владельца 28.09.2026, как сегменты у
/// Стравы): сверка трека с тропами идёт после КАЖДОЙ пробежки в любом режиме,
/// поэтому отдельный режим ничего не включал — только менял картинку. Тропы
/// теперь: авто-зачёт на финише, кнопка «Сделать тропой» и слой на карте.
///
/// Километры во всех режимах одинаково идут в дивизион, зачёты, стрик и баллы —
/// режим меняет только карту и то, предлагаем ли захват на финише.
enum RunMode { free, capture, explore }

extension RunModeLabel on RunMode {
  String get label => switch (this) {
    RunMode.free => 'Свободный',
    RunMode.capture => 'Захват',
    RunMode.explore => 'Исследование',
  };
}

class RunModeController extends StateNotifier<RunMode> {
  RunModeController() : super(RunMode.free) {
    _load();
  }

  // v4: «Тропы» перестали быть режимом (28.09.2026) — поднимаем ключ, чтобы
  // сохранённый выбор «trails» не читался как мусор и не тянул старый дефолт.
  static const _prefsKey = 'kvartal.run_mode.v4';

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
