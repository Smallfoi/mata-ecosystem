import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../api/api_client.dart';

/// Серверные флаги видимости (D-87): что показывать в «Квартале». Меняются в
/// админке, приложение подхватывает через GET /v1/config БЕЗ пересборки.
///
/// По умолчанию периферия СКРЫТА (D-75: на старте только ядро, недоделанное не
/// показываем «дверями в никуда»). Флаг включается на сервере, когда функция
/// готова, — новый APK для этого не нужен.
class AppConfig {
  final bool showTrails;
  final bool showWatch;
  final bool showRaces;
  final bool showLeagueFull;
  final bool showSleepingMedals;

  const AppConfig({
    this.showTrails = false,
    this.showWatch = false,
    this.showRaces = false,
    this.showLeagueFull = false,
    this.showSleepingMedals = false,
  });

  factory AppConfig.fromJson(Map<String, dynamic> j) => AppConfig(
        showTrails: j['showTrails'] == true,
        showWatch: j['showWatch'] == true,
        showRaces: j['showRaces'] == true,
        showLeagueFull: j['showLeagueFull'] == true,
        showSleepingMedals: j['showSleepingMedals'] == true,
      );

  Map<String, dynamic> toJson() => {
        'showTrails': showTrails,
        'showWatch': showWatch,
        'showRaces': showRaces,
        'showLeagueFull': showLeagueFull,
        'showSleepingMedals': showSleepingMedals,
      };
}

const _configCacheKey = 'kvartal.app_config.v1';
final _configDio = ApiClient.create();

/// Флаги приложения. Последний ответ кэшируем в SharedPreferences: если сеть
/// недоступна — берём кэш, иначе дефолты (всё скрыто). Публичный эндпоинт, токен
/// не нужен. UI читает так: `ref.watch(appConfigProvider).valueOrNull ?? const AppConfig()`.
final appConfigProvider = FutureProvider<AppConfig>((ref) async {
  SharedPreferences? prefs;
  try {
    prefs = await SharedPreferences.getInstance();
  } catch (_) {}
  try {
    final res = await _configDio.get<Map<String, dynamic>>('/config');
    final cfg = AppConfig.fromJson(res.data ?? const {});
    try {
      await prefs?.setString(_configCacheKey, jsonEncode(cfg.toJson()));
    } catch (_) {}
    return cfg;
  } catch (_) {
    final raw = prefs?.getString(_configCacheKey);
    if (raw != null) {
      try {
        return AppConfig.fromJson(jsonDecode(raw) as Map<String, dynamic>);
      } catch (_) {}
    }
    return const AppConfig();
  }
});
