import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Слой троп на карте: показывать линии троп или нет.
///
/// Раньше это был режим бега («Тропы»), и он ничего не включал: сверка трека с
/// тропами идёт после КАЖДОЙ пробежки в любом режиме. Решение владельца
/// (28.09.2026, по образцу сегментов Стравы): тропы — не режим, а слой карты.
/// Выбор запоминается: включил — линии на карте остаются между запусками.
class TrailsLayerController extends StateNotifier<bool> {
  TrailsLayerController() : super(false) {
    _load();
  }

  static const _prefsKey = 'kvartal.trails_layer.v1';

  Future<void> _load() async {
    final prefs = await SharedPreferences.getInstance();
    final saved = prefs.getBool(_prefsKey);
    if (saved == null || !mounted) return;
    state = saved;
  }

  Future<void> toggle() async {
    state = !state;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(_prefsKey, state);
  }
}

final trailsLayerProvider =
    StateNotifierProvider<TrailsLayerController, bool>(
      (ref) => TrailsLayerController(),
    );
