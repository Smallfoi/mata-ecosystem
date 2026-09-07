import 'dart:async' show unawaited;
import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:latlong2/latlong.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../../../core/api/api_config.dart';
import '../../auth/data/auth_provider.dart';
import '../../loyalty/data/loyalty_provider.dart';
import '../../notifications/data/notifications_provider.dart';

const _completedRunsKey = 'kvartal.completed_runs.v1';
const _runsSyncedKey = 'kvartal.runs_synced.v1';
const _maxStoredRuns = 50;

class CompletedRun {
  final String id;
  final DateTime finishedAt;
  final List<LatLng> route;

  /// Время точек маршрута (мс) — нужно тропам, чтобы посчитать время
  /// прохождения от входа до выхода (D-60). У старых сохранённых забегов пусто.
  final List<int> routeTimes;
  final Duration elapsed;
  final double distanceMeters;
  final int capturedZones;
  final bool capturedTerritory;
  final bool mockDetected; // подделка геолокации (Android mock-GPS) — анти-чит S-04

  const CompletedRun({
    required this.id,
    required this.finishedAt,
    required this.route,
    this.routeTimes = const [],
    required this.elapsed,
    required this.distanceMeters,
    required this.capturedZones,
    required this.capturedTerritory,
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

  String get dateLabel {
    final now = DateTime.now();
    final today = DateTime(now.year, now.month, now.day);
    final date = DateTime(finishedAt.year, finishedAt.month, finishedAt.day);
    final days = today.difference(date).inDays;
    if (days == 0) return 'Сегодня';
    if (days == 1) return 'Вчера';
    return '${finishedAt.day.toString().padLeft(2, '0')}.${finishedAt.month.toString().padLeft(2, '0')}';
  }

  Map<String, dynamic> toJson() => {
    'id': id,
    'finishedAtMs': finishedAt.millisecondsSinceEpoch,
    'elapsedSeconds': elapsed.inSeconds,
    'distanceMeters': distanceMeters,
    'capturedZones': capturedZones,
    'capturedTerritory': capturedTerritory,
    'mockDetected': mockDetected,
    'routeTimes': routeTimes,
    'route': [
      for (final p in route) [p.latitude, p.longitude],
    ],
  };

  static CompletedRun? fromJson(Map<String, dynamic> json) {
    final route = ((json['route'] as List?) ?? const [])
        .whereType<List>()
        .where((p) => p.length >= 2)
        .map((p) => LatLng((p[0] as num).toDouble(), (p[1] as num).toDouble()))
        .toList();
    if (route.isEmpty) return null;

    return CompletedRun(
      id:
          json['id'] as String? ??
          '${json['finishedAtMs'] ?? DateTime.now().millisecondsSinceEpoch}',
      finishedAt: DateTime.fromMillisecondsSinceEpoch(
        (json['finishedAtMs'] as num? ?? DateTime.now().millisecondsSinceEpoch)
            .toInt(),
      ),
      route: route,
      routeTimes: ((json['routeTimes'] as List?) ?? const [])
          .whereType<num>()
          .map((v) => v.toInt())
          .toList(),
      elapsed: Duration(seconds: (json['elapsedSeconds'] as num? ?? 0).toInt()),
      distanceMeters: (json['distanceMeters'] as num? ?? 0).toDouble(),
      capturedZones: (json['capturedZones'] as num? ?? 0).toInt(),
      capturedTerritory: json['capturedTerritory'] as bool? ?? false,
      mockDetected: json['mockDetected'] as bool? ?? false,
    );
  }
}

class CompletedRunsNotifier extends StateNotifier<List<CompletedRun>> {
  final Ref ref;
  CompletedRunsNotifier(this.ref) : super(const []) {
    unawaited(load());
  }

  /// id забегов, уже доставленных на бэк (чтобы не слать повторно).
  Set<String> _synced = {};

  final Dio _dio = Dio(
    BaseOptions(
      baseUrl: ApiConfig.baseUrl,
      connectTimeout: ApiConfig.connectTimeout,
      receiveTimeout: ApiConfig.receiveTimeout,
      headers: {'Content-Type': 'application/json', 'Connection': 'close'},
    ),
  );

  String? get _token {
    final t = ref.read(authProvider).token;
    return (t == null || t.isEmpty) ? null : t;
  }

  Future<void> load() async {
    final prefs = await SharedPreferences.getInstance();
    _synced = (prefs.getStringList(_runsSyncedKey) ?? const <String>[]).toSet();
    final raw = prefs.getString(_completedRunsKey);
    if (raw != null) {
      final data = jsonDecode(raw) as List;
      final runs =
          data
              .whereType<Map>()
              .map((e) => CompletedRun.fromJson(Map<String, dynamic>.from(e)))
              .whereType<CompletedRun>()
              .toList()
            ..sort((a, b) => b.finishedAt.compareTo(a.finishedAt));
      state = runs.take(_maxStoredRuns).toList();
    }
    unawaited(syncPending());
    unawaited(pullFromServer());
  }

  Future<void> add(CompletedRun run) async {
    final next = [run, ...state]
      ..sort((a, b) => b.finishedAt.compareTo(a.finishedAt));
    state = next.take(_maxStoredRuns).toList();
    await _save();
    unawaited(_syncRun(run));
  }

  Future<void> _save() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(
      _completedRunsKey,
      jsonEncode([for (final run in state) run.toJson()]),
    );
  }

  /// Отправить сводку забега на бэк (без сырого маршрута, приватность §2).
  /// Идемпотентно по id; офлайн — отметится при следующем `syncPending`.
  Future<void> _syncRun(CompletedRun run) async {
    final token = _token;
    if (token == null || _synced.contains(run.id)) return;
    try {
      final res = await _dio.post<dynamic>(
        '/runs',
        data: {
          'id': run.id,
          'distanceMeters': run.distanceMeters,
          'elapsedSeconds': run.elapsed.inSeconds,
          'finishedAtMs': run.finishedAt.millisecondsSinceEpoch,
          'capturedTerritory': run.capturedTerritory,
          'capturedZones': run.capturedZones,
          'mockDetected': run.mockDetected,
        },
        options: Options(headers: {'Authorization': 'Bearer $token'}),
      );
      _synced.add(run.id);
      final prefs = await SharedPreferences.getInstance();
      await prefs.setStringList(_runsSyncedKey, _synced.toList());
      // Сервер сам начислил очки за бег (анти-чит S-04) — обновляем баланс.
      // Сумму показываем в церемонии итогов (Ф1): «+N баллов».
      final body = res.data;
      if (body is Map && body['pointsAwarded'] is num) {
        ref.read(lastRunPointsProvider.notifier).state = (
          runId: run.id,
          points: (body['pointsAwarded'] as num).toInt(),
        );
      }
      unawaited(ref.read(loyaltyProvider.notifier).refresh());
      // Сервер мог сказать что-то про этот забег: придержал баллы до проверки,
      // засчитал веху или итоги дивизиона. Тянем ленту сразу, иначе колокольчик
      // узнает об этом только после перезапуска приложения.
      unawaited(ref.read(notificationsProvider.notifier).refresh());
      unawaited(_sendTrack(run, token));
    } catch (_) {
      // офлайн/ошибка — синхронизируем позже (старт/вход)
    }
  }

  /// Отправить трек тропам: сервер найдёт в нём прохождения и УДАЛИТ трек через
  /// 14 дней (D-60). Отдельным запросом от сводки забега — сводка нужна всегда,
  /// а трек только для троп, и человек может их выключить.
  Future<void> _sendTrack(CompletedRun run, String token) async {
    // Без времени точек тропу не засчитать: у забегов, записанных до появления
    // троп, его нет — такие пропускаем молча.
    if (run.route.length < 2 || run.routeTimes.length != run.route.length) return;
    try {
      await _dio.post<dynamic>(
        '/runs/track',
        data: {
          'runId': run.id,
          'points': [
            for (var i = 0; i < run.route.length; i++)
              [run.route[i].latitude, run.route[i].longitude, run.routeTimes[i]],
          ],
        },
        options: Options(headers: {'Authorization': 'Bearer $token'}),
      );
    } catch (_) {
      // Тропы — не то, ради чего стоит держать забег неотправленным.
    }
  }

  /// Досинхронизировать все ещё не отправленные забеги (старт приложения / вход).
  Future<void> syncPending() async {
    if (_token == null) return;
    for (final run in state) {
      if (!_synced.contains(run.id)) await _syncRun(run);
    }
  }

  /// Подтянуть забеги с сервера (кросс-девайс/после переустановки). Серверные
  /// забеги без маршрута (сырой GPS не хранится, §2) — карточки истории его и не
  /// используют (иконка + метрики). Локальные забеги (с маршрутом) в приоритете.
  Future<void> pullFromServer() async {
    final token = _token;
    if (token == null) return;
    try {
      final r = await _dio.get<List<dynamic>>(
        '/runs',
        options: Options(headers: {'Authorization': 'Bearer $token'}),
      );
      final localIds = state.map((e) => e.id).toSet();
      final serverOnly = <CompletedRun>[];
      for (final item in (r.data ?? const [])) {
        if (item is! Map) continue;
        final m = Map<String, dynamic>.from(item);
        final id = m['id']?.toString();
        if (id == null || id.isEmpty || localIds.contains(id)) continue;
        serverOnly.add(CompletedRun(
          id: id,
          finishedAt: DateTime.fromMillisecondsSinceEpoch(
            (m['finishedAtMs'] as num? ?? 0).toInt(),
          ),
          route: const [], // сервер не хранит сырой маршрут (приватность §2)
          elapsed: Duration(seconds: (m['elapsedSeconds'] as num? ?? 0).toInt()),
          distanceMeters: (m['distanceMeters'] as num? ?? 0).toDouble(),
          capturedZones: (m['capturedZones'] as num? ?? 0).toInt(),
          capturedTerritory: m['capturedTerritory'] as bool? ?? false,
        ));
      }
      if (serverOnly.isEmpty) return;
      final merged = [...state, ...serverOnly]
        ..sort((a, b) => b.finishedAt.compareTo(a.finishedAt));
      state = merged.take(_maxStoredRuns).toList();
    } catch (_) {
      // офлайн/ошибка — покажем локальную историю
    }
  }
}

final completedRunsProvider =
    StateNotifierProvider<CompletedRunsNotifier, List<CompletedRun>>((ref) {
      final notifier = CompletedRunsNotifier(ref);
      // Появился токен (вход/восстановление) — досылаем накопленные забеги.
      ref.listen<AuthState>(authProvider, (prev, next) {
        if (next.token != null &&
            next.token!.isNotEmpty &&
            next.token != prev?.token) {
          notifier.syncPending();
          notifier.pullFromServer();
        }
      });
      return notifier;
    });


/// Баллы, начисленные сервером за последнюю отправленную пробежку —
/// церемония итогов (Ф1) дорисовывает «+N баллов», когда ответ долетел.
final lastRunPointsProvider =
    StateProvider<({String runId, int points})?>((_) => null);
