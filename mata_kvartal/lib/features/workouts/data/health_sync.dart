import 'dart:io' show Platform;

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:health/health.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../../../core/api/api_config.dart';
import '../../auth/data/auth_provider.dart';

/// Тренировки с часов через Health Connect (LEAGUE_PLAN, этап 2).
///
/// Почему именно так, а не «подключить COROS». Партнёрские API выдают ключи
/// выборочно и месяцами: COROS рассматривает заявки раз в месяц, Suunto — до двух
/// недель. Health Connect — общее хранилище здоровья Android: в него пишут
/// приложения COROS, Samsung, Amazfit, Polar, Zepp и десятки других. Читая оттуда,
/// мы получаем тренировки со всех этих часов сразу и ни у кого не спрашиваем
/// разрешения, кроме самого человека.
///
/// Правило приватности: читаем только тренировки (и пульс/калории внутри них),
/// не шаги за день и не сон. Разбором занимается сервер (`POST /workouts/import`),
/// он же решает, начислять ли очки — телефон очки не считает (анти-чит S-04).

/// Типы, которые запрашиваем. Меньше просишь — охотнее разрешают.
const _types = [
  HealthDataType.WORKOUT,
  HealthDataType.HEART_RATE,
  HealthDataType.TOTAL_CALORIES_BURNED,
];

/// Как далеко назад смотреть при первом подключении.
const _firstSyncWindow = Duration(days: 30);

/// Перекрытие при повторной синхронизации: приложение часов может записать
/// тренировку в Health Connect с задержкой, уже после того как мы синхронизировались.
const _resyncOverlap = Duration(days: 2);

/// Как часто фоновая синхронизация вообще имеет смысл.
const _autoSyncGap = Duration(minutes: 15);

const _prefsLastSync = 'health_last_sync_ms';

enum HealthAvailability {
  /// Не Android — экран подключения не показываем.
  unsupported,

  /// Health Connect на телефоне не установлен или требует обновления.
  needsInstall,

  /// Всё на месте, можно просить доступ.
  ready,
}

class HealthSyncState {
  final HealthAvailability availability;
  final bool connected;
  final bool busy;
  final int? lastSyncMs;

  /// Итог последней синхронизации — чтобы человеку было что показать.
  final int lastImported;
  final int lastPoints;
  final String? error;

  const HealthSyncState({
    this.availability = HealthAvailability.unsupported,
    this.connected = false,
    this.busy = false,
    this.lastSyncMs,
    this.lastImported = 0,
    this.lastPoints = 0,
    this.error,
  });

  HealthSyncState copyWith({
    HealthAvailability? availability,
    bool? connected,
    bool? busy,
    int? lastSyncMs,
    int? lastImported,
    int? lastPoints,
    String? error,
    bool clearError = false,
  }) => HealthSyncState(
    availability: availability ?? this.availability,
    connected: connected ?? this.connected,
    busy: busy ?? this.busy,
    lastSyncMs: lastSyncMs ?? this.lastSyncMs,
    lastImported: lastImported ?? this.lastImported,
    lastPoints: lastPoints ?? this.lastPoints,
    error: clearError ? null : (error ?? this.error),
  );
}

class HealthSyncNotifier extends StateNotifier<HealthSyncState> {
  HealthSyncNotifier(this._ref) : super(const HealthSyncState()) {
    refresh();
  }

  final Ref _ref;
  final Health _health = Health();
  bool _configured = false;

  final Dio _dio = Dio(
    BaseOptions(
      baseUrl: ApiConfig.baseUrl,
      connectTimeout: ApiConfig.connectTimeout,
      receiveTimeout: ApiConfig.receiveTimeout,
      headers: {'Content-Type': 'application/json', 'Connection': 'close'},
    ),
  );

  Future<void> _configure() async {
    if (_configured) return;
    await _health.configure();
    _configured = true;
  }

  /// Есть ли Health Connect и дан ли доступ. Вызывается при открытии экрана:
  /// человек мог отозвать доступ в системных настройках, пока нас не было.
  Future<void> refresh() async {
    if (!Platform.isAndroid) {
      state = state.copyWith(availability: HealthAvailability.unsupported);
      return;
    }
    try {
      await _configure();
      final status = await _health.getHealthConnectSdkStatus();
      if (status != HealthConnectSdkStatus.sdkAvailable) {
        state = state.copyWith(
          availability: HealthAvailability.needsInstall,
          connected: false,
        );
        return;
      }
      final granted = await _health.hasPermissions(_types) ?? false;
      final prefs = await SharedPreferences.getInstance();
      state = state.copyWith(
        availability: HealthAvailability.ready,
        connected: granted,
        lastSyncMs: prefs.getInt(_prefsLastSync),
        clearError: true,
      );
    } catch (_) {
      // Health Connect недоступен на части прошивок — это не ошибка приложения,
      // просто источник не работает.
      state = state.copyWith(availability: HealthAvailability.needsInstall);
    }
  }

  /// Открыть магазин на странице Health Connect.
  Future<void> install() async {
    try {
      await _health.installHealthConnect();
    } catch (_) {
      // магазина может не быть — молчим
    }
  }

  /// Спросить доступ. Диалог показывает сам Android, мы только получаем ответ.
  Future<bool> connect() async {
    state = state.copyWith(busy: true, clearError: true);
    try {
      await _configure();
      final ok = await _health.requestAuthorization(_types);
      state = state.copyWith(connected: ok, busy: false);
      if (ok) await sync();
      return ok;
    } catch (_) {
      state = state.copyWith(busy: false, error: 'Не удалось получить доступ');
      return false;
    }
  }

  /// Отключить источник: отзываем доступ и просим сервер стереть импорт.
  Future<void> disconnect() async {
    state = state.copyWith(busy: true, clearError: true);
    try {
      await _health.revokePermissions();
    } catch (_) {
      // на части прошивок отзыв недоступен — не страшно
    }
    final token = _ref.read(authProvider).token;
    if (token != null && token.isNotEmpty) {
      try {
        await _dio.delete<Map<String, dynamic>>(
          '/workouts/source/healthconnect',
          options: Options(headers: {'Authorization': 'Bearer $token'}),
        );
      } catch (_) {
        // сеть подождёт: доступ уже отозван
      }
    }
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_prefsLastSync);
    state = const HealthSyncState(
      availability: HealthAvailability.ready,
      connected: false,
    );
  }

  /// Тихая синхронизация в фоне (открыли профиль, вернулись в приложение).
  /// Ничего не показывает и не беспокоит Health Connect чаще, чем нужно:
  /// тренировка с часов приезжает в хранилище не мгновенно, и разница между
  /// «через минуту» и «через четверть часа» человеку не видна.
  Future<void> autoSync() async {
    if (state.busy) return;
    if (state.availability != HealthAvailability.ready || !state.connected) {
      await refresh();
    }
    if (!state.connected) return;
    final last = state.lastSyncMs;
    if (last != null &&
        DateTime.now().millisecondsSinceEpoch - last < _autoSyncGap.inMilliseconds) {
      return;
    }
    await sync();
  }

  /// Забрать тренировки и отдать серверу. Очки считает он.
  Future<void> sync() async {
    final token = _ref.read(authProvider).token;
    if (token == null || token.isEmpty || !state.connected) return;
    state = state.copyWith(busy: true, clearError: true);
    try {
      await _configure();
      final prefs = await SharedPreferences.getInstance();
      final lastMs = prefs.getInt(_prefsLastSync);
      final now = DateTime.now();
      final from = lastMs == null
          ? now.subtract(_firstSyncWindow)
          : DateTime.fromMillisecondsSinceEpoch(lastMs).subtract(_resyncOverlap);

      final points = await _health.getHealthDataFromTypes(
        types: const [HealthDataType.WORKOUT],
        startTime: from,
        endTime: now,
      );
      // Пульс лежит отдельными записями, не внутри тренировки. Забираем его за то
      // же окно ОДНИМ запросом и раскладываем по тренировкам сами: запрашивать
      // пульс на каждую тренировку отдельно — десятки обращений на первой синхронизации.
      final hr = await _heartRate(from, now);
      final items = points
          .map((p) => _toItem(p, hr))
          .whereType<Map<String, dynamic>>()
          .toList();
      if (items.isEmpty) {
        await prefs.setInt(_prefsLastSync, now.millisecondsSinceEpoch);
        state = state.copyWith(
          busy: false,
          lastSyncMs: now.millisecondsSinceEpoch,
          lastImported: 0,
          lastPoints: 0,
        );
        return;
      }

      final res = await _dio.post<Map<String, dynamic>>(
        '/workouts/import',
        data: {'source': 'healthconnect', 'items': items},
        options: Options(headers: {'Authorization': 'Bearer $token'}),
      );
      final body = res.data ?? const <String, dynamic>{};
      // Отметку времени двигаем только после успешного ответа: иначе при обрыве
      // сети тренировки остались бы за окном и не приехали никогда.
      await prefs.setInt(_prefsLastSync, now.millisecondsSinceEpoch);
      state = state.copyWith(
        busy: false,
        lastSyncMs: now.millisecondsSinceEpoch,
        lastImported: (body['imported'] as num?)?.toInt() ?? 0,
        lastPoints: (body['points'] as num?)?.toInt() ?? 0,
      );
    } catch (_) {
      state = state.copyWith(busy: false, error: 'Не удалось синхронизировать');
    }
  }

  /// Удары пульса за окно: (момент, значение). Пустой список, если пульса нет —
  /// на телефоне без часов его и не будет, это не ошибка.
  Future<List<(DateTime, int)>> _heartRate(DateTime from, DateTime to) async {
    try {
      final points = await _health.getHealthDataFromTypes(
        types: const [HealthDataType.HEART_RATE],
        startTime: from,
        endTime: to,
      );
      final out = <(DateTime, int)>[];
      for (final p in points) {
        final v = p.value;
        if (v is NumericHealthValue) {
          out.add((p.dateFrom, v.numericValue.round()));
        }
      }
      return out;
    } catch (_) {
      // Доступ к пульсу могли не дать — тренировки от этого не пропадают.
      return const [];
    }
  }

  /// Одна тренировка Health Connect → элемент для `POST /workouts/import`.
  /// Тренировки без дистанции (силовая, йога) пропускаем: считать в них нечего.
  Map<String, dynamic>? _toItem(HealthDataPoint p, List<(DateTime, int)> hr) {
    final value = p.value;
    if (value is! WorkoutHealthValue) return null;
    final distance =
        value.totalDistance ?? p.workoutSummary?.totalDistance.toInt() ?? 0;
    if (distance <= 0) return null;
    final duration = p.dateTo.difference(p.dateFrom).inSeconds;
    if (duration <= 0) return null;
    final beats = [
      for (final (at, bpm) in hr)
        if (!at.isBefore(p.dateFrom) && !at.isAfter(p.dateTo)) bpm,
    ];
    return {
      // uuid Health Connect стабилен: та же тренировка не приедет дважды.
      'sourceId': p.uuid,
      'startedAtMs': p.dateFrom.millisecondsSinceEpoch,
      'durationS': duration,
      'distanceM': distance,
      'sport': _sport(value.workoutActivityType),
      if (value.totalEnergyBurned != null) 'calories': value.totalEnergyBurned,
      if (beats.isNotEmpty)
        'avgHr': (beats.reduce((a, b) => a + b) / beats.length).round(),
      if (beats.isNotEmpty) 'maxHr': beats.reduce((a, b) => a > b ? a : b),
    };
  }

  /// Вид спорта в словарь сервера. Всё незнакомое отдаём как есть в нижнем
  /// регистре — сервер сам решит, беговое это или нет.
  String _sport(HealthWorkoutActivityType type) => switch (type) {
    HealthWorkoutActivityType.RUNNING => 'run',
    HealthWorkoutActivityType.RUNNING_TREADMILL => 'treadmill',
    HealthWorkoutActivityType.WALKING => 'walking',
    HealthWorkoutActivityType.WALKING_TREADMILL => 'walking',
    HealthWorkoutActivityType.HIKING => 'hiking',
    _ => type.name.toLowerCase(),
  };
}

final healthSyncProvider =
    StateNotifierProvider<HealthSyncNotifier, HealthSyncState>(
      (ref) => HealthSyncNotifier(ref),
    );
