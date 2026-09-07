import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:geolocator/geolocator.dart';
import 'package:latlong2/latlong.dart';
import 'package:permission_handler/permission_handler.dart' as permissions;
import 'package:flutter/services.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../../shoes/data/shoes_provider.dart';
import 'completed_runs_provider.dart';
import 'gps_kalman.dart';
import 'route_cleaner.dart';

enum RunStatus { idle, active, paused }

const activeRunStorageKey = 'kvartal.active_run.v1';
const activeRunSchemaVersion = 2;
const _maxRunSpeedMs = 11.1;
const _minRoutePointDistanceMeters = 2.0;
const _maxRoutePointGapMeters = 80.0;
// Жёстче по точности — отсекаем «гуляющие» фиксы, дающие дрожь на 2–3 м.
const _maxAcceptedAccuracyMeters = 35.0;
// «Идеальный маршрут» (03.09.2026): три новых рубежа против GPS-игл.
// Телепорт: скорость МЕЖДУ фиксами (расстояние ÷ время) выше этой — выброс;
// «скорость чипа» при рикошете от зданий врёт (часто ноль), поэтому считаем сами.
const _maxJumpSpeedMs = 12.0;
// Подтверждение карантина: следующий фикс ближе этого к подозрительному —
// значит прыжок настоящий (потеря сигнала), а не одиночный выброс.
const _jumpConfirmRadiusMeters = 30.0;
// Стоп-детекция: стоим (светофор, подъезд) — качели GPS в маршрут не пишем.
const _stopSpeedMs = 0.6;
const _stopNearbyMeters = 15.0;
// Фильтр на уровне ОС: не репортим, пока реально не сдвинулись (убирает дрожь на месте).
const _locationDistanceFilterMeters = 5;
const _locationServiceChannel = MethodChannel('kvartal/location_service');

class RunState {
  final RunStatus status;
  final List<LatLng> route;

  /// Время каждой точки маршрута (мс). Идёт рядом с route, а не внутри неё,
  /// чтобы не переписывать всё, что рисует линию по `List<LatLng>`.
  /// Нужно тропам: их время считается от входа до выхода (D-60).
  final List<int> routeTimes;
  final Duration elapsed;
  final double distanceMeters;
  final bool mockDetected; // в забеге был подделанный GPS (Android mock) — анти-чит S-04

  const RunState({
    this.status = RunStatus.idle,
    this.route = const [],
    this.routeTimes = const [],
    this.elapsed = Duration.zero,
    this.distanceMeters = 0,
    this.mockDetected = false,
  });

  double get distanceKm => distanceMeters / 1000;

  int get paceSeconds {
    if (distanceKm < 0.01 || elapsed.inSeconds == 0) return 0;
    return (elapsed.inSeconds / distanceKm).round();
  }

  String get paceFormatted {
    if (paceSeconds == 0) return '--:--';
    final m = paceSeconds ~/ 60;
    final s = paceSeconds % 60;
    return '${m.toString().padLeft(2, '0')}:${s.toString().padLeft(2, '0')}';
  }

  String get elapsedFormatted {
    final h = elapsed.inHours;
    final m = elapsed.inMinutes % 60;
    final s = elapsed.inSeconds % 60;
    if (h > 0) {
      return '${h.toString().padLeft(2, '0')}:${m.toString().padLeft(2, '0')}:${s.toString().padLeft(2, '0')}';
    }
    return '${m.toString().padLeft(2, '0')}:${s.toString().padLeft(2, '0')}';
  }

  RunState copyWith({
    RunStatus? status,
    List<LatLng>? route,
    List<int>? routeTimes,
    Duration? elapsed,
    double? distanceMeters,
    bool? mockDetected,
  }) {
    return RunState(
      status: status ?? this.status,
      route: route ?? this.route,
      routeTimes: routeTimes ?? this.routeTimes,
      elapsed: elapsed ?? this.elapsed,
      distanceMeters: distanceMeters ?? this.distanceMeters,
      mockDetected: mockDetected ?? this.mockDetected,
    );
  }
}

class RunNotifier extends StateNotifier<RunState> {
  final Ref _ref;
  RunNotifier(this._ref) : super(const RunState()) {
    unawaited(_restoreSavedRun());
  }

  Timer? _timer;
  StreamSubscription<Position>? _foregroundPositionSub;

  /// Сглаживание GPS — каждый забег со своим чистым фильтром.
  final GpsKalman _kalman = GpsKalman();

  // Последний ПРИНЯТЫЙ сырой фикс — база для межточечной скорости.
  Position? _lastRawAccepted;
  // Подозрительный «телепорт» ждёт подтверждения вторым фиксом рядом.
  Position? _quarantined;
  DateTime? _quarantinedAt;
  // Подтверждённый разрыв (потеря сигнала): следующей точке разрешён
  // большой шаг — иначе маршрут навсегда упрётся в gap-фильтр.
  bool _segmentBreak = false;

  void _resetGpsGuards() {
    _kalman.reset();
    _lastRawAccepted = null;
    _quarantined = null;
    _quarantinedAt = null;
    _segmentBreak = false;
  }

  Future<void> start() async {
    debugPrint('KVARTAL_RUN_START_TAP');
    if (state.status == RunStatus.active) return;
    // Новый забег (не resume) — сбрасываем фильтр сглаживания и стражей GPS.
    if (state.status == RunStatus.idle) _resetGpsGuards();

    final canTrack = await _ensureLocationReady();
    if (!canTrack) {
      debugPrint('KVARTAL_RUN_START_LOCATION_NOT_READY');
      return;
    }

    debugPrint('KVARTAL_RUN_START_LOCATION_READY');
    state = state.copyWith(
      status: RunStatus.active,
      route: state.status == RunStatus.idle ? [] : state.route,
      distanceMeters: state.status == RunStatus.idle ? 0 : state.distanceMeters,
      elapsed: state.status == RunStatus.idle ? Duration.zero : state.elapsed,
      mockDetected: state.status == RunStatus.idle ? false : state.mockDetected,
    );

    debugPrint('KVARTAL_RUN_START_STATE_ACTIVE');
    unawaited(_seedCurrentPosition());
    unawaited(_persistRun());
    unawaited(_startNativeLocationService());
    _startTimer();
    _startForegroundTracking();
  }

  Future<void> _startNativeLocationService() async {
    if (kIsWeb || defaultTargetPlatform != TargetPlatform.android) return;
    try {
      await _locationServiceChannel.invokeMethod('startLocationService');
      debugPrint('KVARTAL_RUN_NATIVE_LOCATION_SERVICE_STARTED');
    } catch (error) {
      debugPrint('KVARTAL_RUN_NATIVE_LOCATION_SERVICE_START_ERROR: $error');
    }
  }

  Future<void> _stopNativeLocationService() async {
    if (kIsWeb || defaultTargetPlatform != TargetPlatform.android) return;
    try {
      await _locationServiceChannel.invokeMethod('stopLocationService');
      debugPrint('KVARTAL_RUN_NATIVE_LOCATION_SERVICE_STOPPED');
    } catch (error) {
      debugPrint('KVARTAL_RUN_NATIVE_LOCATION_SERVICE_STOP_ERROR: $error');
    }
  }

  Future<void> _ensureNotificationPermission() async {
    if (kIsWeb || defaultTargetPlatform != TargetPlatform.android) return;
    try {
      final status = await permissions.Permission.notification.status;
      if (status.isDenied) {
        await permissions.Permission.notification.request();
      }
    } catch (error) {
      debugPrint('KVARTAL_RUN_NOTIFICATION_PERMISSION_ERROR: $error');
    }
  }

  Future<bool> _ensureLocationReady() async {
    try {
      await _ensureNotificationPermission();

      final serviceEnabled = await Geolocator.isLocationServiceEnabled();
      if (!serviceEnabled) return false;

      var permission = await Geolocator.checkPermission();
      if (permission == LocationPermission.denied) {
        permission = await Geolocator.requestPermission();
      }

      return permission == LocationPermission.whileInUse ||
          permission == LocationPermission.always;
    } catch (error, stackTrace) {
      debugPrint('KVARTAL_RUN_LOCATION_PERMISSION_ERROR: $error');
      debugPrintStack(stackTrace: stackTrace);
      return false;
    }
  }

  Future<void> _seedCurrentPosition() async {
    try {
      // Прогрев GPS-чипа. В МАРШРУТ первую точку НЕ пишем: холодный фикс в
      // городе врёт на 50–500 м и раньше рисовал «хвост» от старта
      // («Идеальный маршрут», 03.09). Маршрут начнётся с первого потокового
      // фикса, прошедшего все фильтры; метку на карте ведёт location_provider.
      final current = await Geolocator.getCurrentPosition(
        locationSettings: _foregroundLocationSettings(),
      );
      debugPrint(
        'KVARTAL_RUN_GPS_WARMED: accuracy=${current.accuracy.toStringAsFixed(0)}m',
      );
    } catch (error) {
      debugPrint('KVARTAL_RUN_GPS_SEED_ERROR: $error');
    }
  }

  void _startForegroundTracking() {
    debugPrint('KVARTAL_RUN_FOREGROUND_STREAM_START');
    unawaited(_foregroundPositionSub?.cancel());
    _foregroundPositionSub =
        Geolocator.getPositionStream(
          locationSettings: _foregroundLocationSettings(),
        ).listen(
          (position) => unawaited(_applyPosition(position)),
          onError: (Object error, StackTrace stackTrace) {
            debugPrint('KVARTAL_RUN_FOREGROUND_STREAM_ERROR: $error');
            debugPrintStack(stackTrace: stackTrace);
          },
        );
  }

  Future<void> _applyPosition(Position position) async {
    if (state.status != RunStatus.active) return;
    // Анти-чит S-04: подделка геолокации (Android mock-provider). Фиксируем флаг
    // даже если точка дальше отфильтруется — сервер обнулит очки за такой забег.
    if (position.isMocked && !state.mockDetected) {
      debugPrint('KVARTAL_RUN_MOCK_GPS_DETECTED');
      state = state.copyWith(mockDetected: true);
    }
    if (position.accuracy > _maxAcceptedAccuracyMeters) return;
    if (position.speed > _maxRunSpeedMs) return;

    final now = DateTime.now();
    final prevRaw = _lastRawAccepted;
    final rawGap = prevRaw == null
        ? 0.0
        : Geolocator.distanceBetween(
            prevRaw.latitude,
            prevRaw.longitude,
            position.latitude,
            position.longitude,
          );

    // Стоп-детекция: стоим на месте — качели GPS (иглы у подъезда) в маршрут
    // не пишем. Если скорость чипа недостоверна (speedAccuracy ≤ 0), верим
    // ей только вблизи последней принятой точки.
    if (prevRaw != null &&
        position.speed >= 0 &&
        position.speed < _stopSpeedMs &&
        (position.speedAccuracy > 0 || rawGap < _stopNearbyMeters)) {
      return;
    }

    // Межточечная скорость: телепорт против последнего ПРИНЯТОГО сырого фикса.
    // Одиночный выброс умирает в карантине; настоящий разрыв (потеря сигнала
    // в тоннеле) подтверждается вторым фиксом рядом — тогда принимаем и
    // начинаем сглаживание заново, чтобы Кальман не размазывал скачок.
    if (prevRaw != null) {
      final dtS =
          position.timestamp.difference(prevRaw.timestamp).inMilliseconds /
              1000.0;
      final jumpSpeed = dtS > 0 ? rawGap / dtS : double.infinity;
      if (jumpSpeed > _maxJumpSpeedMs) {
        final q = _quarantined;
        final confirmed = q != null &&
            _quarantinedAt != null &&
            now.difference(_quarantinedAt!).inSeconds <= 12 &&
            Geolocator.distanceBetween(
                  q.latitude,
                  q.longitude,
                  position.latitude,
                  position.longitude,
                ) <
                _jumpConfirmRadiusMeters;
        if (!confirmed) {
          _quarantined = position;
          _quarantinedAt = now;
          debugPrint(
            'KVARTAL_RUN_GPS_JUMP_QUARANTINED: '
            '${rawGap.toStringAsFixed(0)}m @${jumpSpeed.toStringAsFixed(1)}m/s',
          );
          return;
        }
        debugPrint('KVARTAL_RUN_GPS_JUMP_CONFIRMED: сегмент начат заново');
        _kalman.reset();
        _segmentBreak = true;
      }
    }
    _quarantined = null;
    _quarantinedAt = null;
    _lastRawAccepted = position;

    // Сглаживаем фикс фильтром Калмана: метку и линию рисуем по сглаженной
    // точке, а не по «дрожащему» сырому GPS. Точность фикса = вес доверия.
    final next = _kalman.process(
      lat: position.latitude,
      lng: position.longitude,
      accuracy: position.accuracy,
      timestampMs: now.millisecondsSinceEpoch,
    );
    final route = [...state.route];
    final routeTimes = [...state.routeTimes];
    var distanceMeters = state.distanceMeters;

    if (route.isNotEmpty) {
      final last = route.last;
      final gapMeters = Geolocator.distanceBetween(
        last.latitude,
        last.longitude,
        next.latitude,
        next.longitude,
      );
      if (gapMeters < _minRoutePointDistanceMeters) return;
      if (gapMeters > _maxRoutePointGapMeters && !_segmentBreak) {
        debugPrint(
          'KVARTAL_RUN_GPS_JUMP_REJECTED: ${gapMeters.toStringAsFixed(1)}m',
        );
        return;
      }
      distanceMeters += gapMeters;
    }
    _segmentBreak = false;

    route.add(next);
    routeTimes.add(now.millisecondsSinceEpoch);
    state = state.copyWith(
      route: route,
      routeTimes: routeTimes,
      distanceMeters: distanceMeters,
    );
    await _persistRun();
  }

  void _startTimer() {
    _timer?.cancel();
    _timer = Timer.periodic(const Duration(seconds: 1), (_) {
      state = state.copyWith(
        elapsed: state.elapsed + const Duration(seconds: 1),
      );
      if (state.elapsed.inSeconds % 5 == 0) {
        unawaited(_persistRun());
      }
    });
  }

  void pause() {
    if (state.status != RunStatus.active) return;
    _timer?.cancel();
    unawaited(_foregroundPositionSub?.cancel());
    unawaited(_stopNativeLocationService());
    _foregroundPositionSub = null;
    state = state.copyWith(status: RunStatus.paused);
    unawaited(_persistRun());
  }

  void resume() {
    if (state.status != RunStatus.paused) return;
    unawaited(start());
  }

  void stop({int capturedZones = 0, bool capturedTerritory = false}) {
    final completed = state;
    _timer?.cancel();
    unawaited(_foregroundPositionSub?.cancel());
    unawaited(_stopNativeLocationService());
    _foregroundPositionSub = null;
    if (completed.route.length > 1 || completed.distanceMeters > 0) {
      unawaited(_saveCompletedRun(completed, capturedZones, capturedTerritory));
    }
    state = const RunState();
    unawaited(_clearSavedRun());
  }

  void reset() {
    _timer?.cancel();
    unawaited(_foregroundPositionSub?.cancel());
    unawaited(_stopNativeLocationService());
    _foregroundPositionSub = null;
    state = const RunState();
    unawaited(_clearSavedRun());
  }

  Future<void> _saveCompletedRun(
    RunState completed,
    int capturedZones,
    bool capturedTerritory,
  ) async {
    // Финальная чистка трека: срез шипов + Дуглас-Пекер («Идеальный маршрут»).
    // По индексам, чтобы времена точек (тропы, D-60) остались согласованными.
    final kept = cleanRouteKeepIndices(completed.route);
    final cleanedRoute = [for (final i in kept) completed.route[i]];
    final cleanedTimes = completed.routeTimes.length == completed.route.length
        ? [for (final i in kept) completed.routeTimes[i]]
        : completed.routeTimes;
    final run = CompletedRun(
      id: DateTime.now().microsecondsSinceEpoch.toString(),
      finishedAt: DateTime.now(),
      route: cleanedRoute,
      routeTimes: cleanedTimes,
      elapsed: completed.elapsed,
      distanceMeters: completed.distanceMeters,
      capturedZones: capturedZones,
      capturedTerritory: capturedTerritory,
      mockDetected: completed.mockDetected,
    );
    await _ref.read(completedRunsProvider.notifier).add(run);
    await _applyShoeWear(run);
  }

  /// Списать пробег с активной пары кроссовок (связка Store↔Квартал).
  /// Идемпотентно по runId; офлайн уходит в очередь и долетит позже.
  Future<void> _applyShoeWear(CompletedRun run) async {
    if (run.distanceKm <= 0) return;
    await _ref.read(shoesProvider.notifier).applyRunDistance(
          km: run.distanceKm,
          runId: run.id,
        );
  }

  // Очки за бег и за захват территории теперь начисляет СЕРВЕР (анти-чит S-04):
  // бег — при синке забега (POST /runs), территория — при захвате
  // (POST /territories/capture). Клиент их больше не шлёт; баланс обновляется
  // после соответствующего сетевого вызова (completed_runs / territory_provider).

  Future<void> _restoreSavedRun() async {
    try {
      final restored = await _readSavedRun(applyElapsedDelta: true);
      if (restored == null || restored.status == RunStatus.idle) {
        await _clearSavedRun();
        return;
      }

      state = restored;
      if (restored.status == RunStatus.active) {
        unawaited(_startNativeLocationService());
        _startTimer();
        _startForegroundTracking();
      }
    } catch (error) {
      debugPrint('KVARTAL_RUN_RESTORE_ERROR: $error');
      await _clearSavedRun();
    }
  }

  Future<RunState?> _readSavedRun({required bool applyElapsedDelta}) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.reload();
    final raw = prefs.getString(activeRunStorageKey);
    if (raw == null) return null;

    final data = jsonDecode(raw) as Map<String, dynamic>;
    if (data['schemaVersion'] != activeRunSchemaVersion) return null;

    final statusName = data['status'] as String? ?? RunStatus.idle.name;
    final restoredStatus = RunStatus.values.firstWhere(
      (s) => s.name == statusName,
      orElse: () => RunStatus.idle,
    );
    if (restoredStatus == RunStatus.idle) return null;

    final route = ((data['route'] as List?) ?? const [])
        .whereType<List>()
        .where((p) => p.length >= 2)
        .map((p) => LatLng((p[0] as num).toDouble(), (p[1] as num).toDouble()))
        .toList();

    if (route.isEmpty) return null;

    // Времена точек обязаны выживать вместе с маршрутом: без них молчат
    // сплиты паспорта и тропы (реальный случай — 44-минутная пробежка
    // владельца с погашенным экраном потеряла времена при восстановлении).
    var routeTimes = ((data['routeTimes'] as List?) ?? const [])
        .whereType<num>()
        .map((v) => v.toInt())
        .toList();
    if (routeTimes.length != route.length) routeTimes = const [];

    var elapsed = Duration(
      seconds: (data['elapsedSeconds'] as num? ?? 0).toInt(),
    );
    final savedAtMs = (data['savedAtMs'] as num?)?.toInt();
    if (applyElapsedDelta &&
        restoredStatus == RunStatus.active &&
        savedAtMs != null) {
      elapsed += DateTime.now().difference(
        DateTime.fromMillisecondsSinceEpoch(savedAtMs),
      );
    }

    return RunState(
      status: restoredStatus,
      route: route,
      routeTimes: routeTimes,
      elapsed: elapsed,
      distanceMeters: (data['distanceMeters'] as num? ?? 0).toDouble(),
      mockDetected: data['mockDetected'] as bool? ?? false,
    );
  }

  Future<void> _persistRun() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.reload();

    var route = state.route;
    var routeTimes = state.routeTimes;
    var distanceMeters = state.distanceMeters;
    final raw = prefs.getString(activeRunStorageKey);
    if (raw != null && state.status == RunStatus.active) {
      try {
        final saved = jsonDecode(raw) as Map<String, dynamic>;
        final savedRoute = ((saved['route'] as List?) ?? const [])
            .whereType<List>()
            .where((p) => p.length >= 2)
            .map(
              (p) => LatLng((p[0] as num).toDouble(), (p[1] as num).toDouble()),
            )
            .toList();
        if (savedRoute.length > route.length) {
          route = savedRoute;
          // Времена — той же длины, что сохранённый маршрут, иначе пусто:
          // рассинхрон хуже отсутствия (сплиты посчитаются неверно).
          final savedTimes = ((saved['routeTimes'] as List?) ?? const [])
              .whereType<num>()
              .map((v) => v.toInt())
              .toList();
          routeTimes =
              savedTimes.length == savedRoute.length ? savedTimes : const [];
          distanceMeters = (saved['distanceMeters'] as num? ?? distanceMeters)
              .toDouble();
          state = state.copyWith(
            route: route,
            routeTimes: routeTimes,
            distanceMeters: distanceMeters,
          );
        }
      } catch (_) {
        // Ignore malformed saved state; the new state below will replace it.
      }
    }

    final data = {
      'schemaVersion': activeRunSchemaVersion,
      'status': state.status.name,
      'elapsedSeconds': state.elapsed.inSeconds,
      'distanceMeters': distanceMeters,
      'mockDetected': state.mockDetected,
      'savedAtMs': DateTime.now().millisecondsSinceEpoch,
      'route': [
        for (final p in route) [p.latitude, p.longitude],
      ],
      'routeTimes': routeTimes,
    };
    await prefs.setString(activeRunStorageKey, jsonEncode(data));
  }

  Future<void> _clearSavedRun() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(activeRunStorageKey);
  }

  @override
  void dispose() {
    _timer?.cancel();
    unawaited(_foregroundPositionSub?.cancel());
    super.dispose();
  }
}

LocationSettings _foregroundLocationSettings() {
  if (!kIsWeb && defaultTargetPlatform == TargetPlatform.android) {
    return AndroidSettings(
      accuracy: LocationAccuracy.bestForNavigation,
      distanceFilter: _locationDistanceFilterMeters,
      intervalDuration: const Duration(seconds: 1),
      foregroundNotificationConfig: const ForegroundNotificationConfig(
        notificationTitle: 'КВАРТАЛ записывает пробежку',
        notificationText: 'GPS активен. Маршрут сохраняется в фоне.',
        enableWakeLock: true,
        setOngoing: true,
      ),
    );
  }

  return const LocationSettings(
    accuracy: LocationAccuracy.high,
    distanceFilter: _locationDistanceFilterMeters,
  );
}

final runProvider = StateNotifierProvider<RunNotifier, RunState>(
  (ref) => RunNotifier(ref),
);
