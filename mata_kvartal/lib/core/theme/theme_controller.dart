import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Интерьер приложения (Ф8 «Графитовый интерьер», утверждено 31.08.2026).
///
/// Графит — по умолчанию: приложение держат в руке на улице, часто в темноте.
/// Светлый — осознанный выбор. «Как в системе» следует за темой телефона.
enum Interior { graphite, light, system }

extension InteriorLabel on Interior {
  String get label => switch (this) {
    Interior.graphite => 'Графит',
    Interior.light => 'Светлая',
    Interior.system => 'Как в системе',
  };

  String get hint => switch (this) {
    Interior.graphite => 'Тёмный интерьер — не слепит на улице и в темноте',
    Interior.light => 'Светлая бумага — как сайт и Store',
    Interior.system => 'Повторяет тему телефона',
  };
}

class InteriorController extends StateNotifier<Interior> {
  InteriorController() : super(Interior.graphite) {
    _load();
  }

  static const _prefsKey = 'kvartal.interior.v1';

  Future<void> _load() async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString(_prefsKey);
    if (raw == null) return;
    state = Interior.values.firstWhere(
      (e) => e.name == raw,
      orElse: () => Interior.graphite,
    );
  }

  Future<void> set(Interior mode) async {
    state = mode;
    // Палитра живёт в геттерах AppColors: const-виджеты и sliver-делегаты
    // сами не перечитают её. Полная пересборка — надёжная смена интерьера.
    WidgetsBinding.instance.reassembleApplication();
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_prefsKey, mode.name);
  }
}

final interiorProvider = StateNotifierProvider<InteriorController, Interior>(
  (ref) => InteriorController(),
);

/// Каким интерьером рисовать при данном режиме и системной яркости.
bool resolveGraphite(Interior mode, Brightness platform) => switch (mode) {
  Interior.graphite => true,
  Interior.light => false,
  Interior.system => platform == Brightness.dark,
};
