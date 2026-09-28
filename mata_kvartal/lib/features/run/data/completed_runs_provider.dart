import 'dart:async' show unawaited;
import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:latlong2/latlong.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../../../core/api/api_client.dart';
import '../../../core/storage/account_scope.dart';
import '../../auth/data/auth_provider.dart';
import '../../trails/data/trails_provider.dart';
import '../../loyalty/data/loyalty_provider.dart';
import '../../notifications/data/notifications_provider.dart';

/// Старое общее хранилище (до аудита C03): один список на телефон, без владельца.
/// Читается только разовой миграцией [CompletedRunsNotifier.migrateLegacyStorage].
const legacyCompletedRunsKey = 'kvartal.completed_runs.v1';
const legacyRunsSyncedKey = 'kvartal.runs_synced.v1';

/// История забегов — отдельно на каждый аккаунт (C03).
String completedRunsKeyFor(String owner) => 'kvartal.completed_runs.v2.$owner';

const _maxStoredRuns = 50;

/// Dio для отправки забегов. Отдельный провайдер — чтобы тесты подменяли сеть.
final completedRunsDioProvider = Provider<Dio>(
  (_) => ApiClient.create(
    headers: {'Content-Type': 'application/json', 'Connection': 'close'},
  ),
);

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

  /// Забег помечен анти-читом (S-04) и баллы придержаны до разбора модератором.
  /// Приходит с сервера (POST /runs → `flagged`, GET /runs → `pendingReview`).
  final bool pendingReview;

  /// Сводка забега принята сервером (POST /runs): баллы начислены, повторно
  /// сводку не шлём (C04). Доставка сводки и трека — независимые состояния.
  final bool summarySynced;

  /// Трек ещё надо доставить (тропы, след «Исследования», резервная копия D-86).
  /// Сбой трека не трогает сводку: трек повторяется сам, без нового начисления.
  final bool trackPending;

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
    this.pendingReview = false,
    this.summarySynced = false,
    this.trackPending = false,
  });

  CompletedRun copyWith({
    bool? pendingReview,
    bool? summarySynced,
    bool? trackPending,
  }) => CompletedRun(
    id: id,
    finishedAt: finishedAt,
    route: route,
    routeTimes: routeTimes,
    elapsed: elapsed,
    distanceMeters: distanceMeters,
    capturedZones: capturedZones,
    capturedTerritory: capturedTerritory,
    mockDetected: mockDetected,
    pendingReview: pendingReview ?? this.pendingReview,
    summarySynced: summarySynced ?? this.summarySynced,
    trackPending: trackPending ?? this.trackPending,
  );

  /// Есть что отправить тропам: точки со временем. У забегов, записанных до
  /// появления троп, времени нет — такой трек не шлём.
  bool get hasSendableTrack =>
      route.length >= 2 && routeTimes.length == route.length;

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
    'pendingReview': pendingReview,
    'summarySynced': summarySynced,
    'trackPending': trackPending,
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
      pendingReview: json['pendingReview'] as bool? ?? false,
      summarySynced: json['summarySynced'] as bool? ?? false,
      trackPending: json['trackPending'] as bool? ?? false,
    );
  }
}


/// История забегов и очередь их доставки на сервер.
///
/// Аккаунты (C03). Всё хранится отдельно на каждый аккаунт
/// ([completedRunsKeyFor]); в [state] — только история вошедшего. При выходе
/// история сразу скрывается, а неотправленные забеги НЕ уходят под другим
/// аккаунтом: они ждут в хранилище своего владельца до его следующего входа.
///
/// Доставка (C04). У каждого забега два независимых флага: сводка
/// ([CompletedRun.summarySynced]) и трек ([CompletedRun.trackPending]). Сводка
/// идёт первой — за неё сервер начисляет баллы; трек — вторым. Упал трек —
/// сводка остаётся доставленной, а трек повторяется при следующей досылке
/// (возврат в приложение, вход, старт) без повторной сводки и начисления.
class CompletedRunsNotifier extends StateNotifier<List<CompletedRun>> {
  final Ref ref;
  CompletedRunsNotifier(this.ref) : super(const []) {
    unawaited(load());
  }

  late final Dio _dio = ref.read(completedRunsDioProvider);

  /// Чья история сейчас в [state] (id аккаунта), null — никто не вошёл.
  String? _owner;

  /// Забеги, которые прямо сейчас отправляются: не шлём один забег дважды
  /// параллельно (досылка на старте + отправка сразу после финиша).
  final Set<String> _inFlight = {};

  String? get _token {
    final t = ref.read(authProvider).token;
    return (t == null || t.isEmpty) ? null : t;
  }

  /// id вошедшего аккаунта (null — не вошли или id ещё неизвестен).
  String? get _accountId {
    final id = ref.read(authProvider).user?.id;
    return (id == null || id.isEmpty) ? null : id;
  }

  // ── Хранилище ────────────────────────────────────────────────────────────

  static List<CompletedRun> _decode(String? raw) {
    if (raw == null || raw.isEmpty) return [];
    try {
      return (jsonDecode(raw) as List)
          .whereType<Map>()
          .map((e) => CompletedRun.fromJson(Map<String, dynamic>.from(e)))
          .whereType<CompletedRun>()
          .toList()
        ..sort((a, b) => b.finishedAt.compareTo(a.finishedAt));
    } catch (_) {
      return [];
    }
  }

  static List<CompletedRun> _readBucket(SharedPreferences prefs, String owner) =>
      _decode(prefs.getString(completedRunsKeyFor(owner)))
          .take(_maxStoredRuns)
          .toList();

  static Future<void> _writeBucket(
    SharedPreferences prefs,
    String owner,
    List<CompletedRun> runs,
  ) async {
    // Серверные забеги без маршрута не храним (их вернёт pullFromServer).
    final keep = runs.where((r) => r.route.isNotEmpty).toList();
    if (keep.isEmpty) {
      await prefs.remove(completedRunsKeyFor(owner));
      return;
    }
    await prefs.setString(
      completedRunsKeyFor(owner),
      jsonEncode([for (final run in keep) run.toJson()]),
    );
  }

  static List<CompletedRun> _merge(
    List<CompletedRun> primary,
    List<CompletedRun> extra,
  ) {
    final ids = primary.map((r) => r.id).toSet();
    return [...primary, ...extra.where((r) => !ids.contains(r.id))]
      ..sort((a, b) => b.finishedAt.compareTo(a.finishedAt));
  }

  /// Разовая миграция старого общего списка (C03).
  ///
  /// Старые забеги лежали одним списком на телефон, без владельца. Миграция
  /// запускается при старте приложения — до того, как кто-то успеет войти, —
  /// поэтому id сессии в хранилище ([authUserIdPrefsKey]) — это тот, кто был в
  /// приложении, когда забеги копились (выход этот id стирает). Ему забеги и
  /// достаются, неотправленные уйдут под его же токеном.
  ///
  /// Если в момент обновления никто не был в приложении, владелец неизвестен:
  /// забеги откладываются в корзину [unknownOwner] — не показываются и не
  /// отправляются. Забрать их может только аккаунт, которому сервер их уже
  /// приписал (id забега есть в его GET /runs) — см. [pullFromServer].
  /// Неотправленные забеги неизвестного владельца так и остаются на телефоне:
  /// отправить их под первым вошедшим значило бы, возможно, отдать чужой бег.
  static Future<void> migrateLegacyStorage(SharedPreferences prefs) async {
    final raw = prefs.getString(legacyCompletedRunsKey);
    final synced =
        (prefs.getStringList(legacyRunsSyncedKey) ?? const <String>[]).toSet();
    if (raw != null) {
      final owner = ownerTag(prefs.getString(authUserIdPrefsKey));
      final legacy = [
        for (final r in _decode(raw))
          synced.contains(r.id)
              // Доставлена сводка — трек мог уйти, а мог и нет: считаем
              // отправленным, чтобы не заливать разом до 50 старых треков.
              ? r.copyWith(summarySynced: true, trackPending: false)
              : r.copyWith(summarySynced: false, trackPending: r.hasSendableTrack),
      ];
      final merged = _merge(_readBucket(prefs, owner), legacy);
      await _writeBucket(prefs, owner, merged.take(_maxStoredRuns).toList());
      await prefs.remove(legacyCompletedRunsKey);
    }
    if (prefs.containsKey(legacyRunsSyncedKey)) {
      await prefs.remove(legacyRunsSyncedKey);
    }
  }

  /// Изменить забег [id] аккаунта [owner]. Пишем в хранилище владельца, даже
  /// если уже вошёл другой: ответ сервера на отправку под токеном A относится к
  /// A и не должен ни потеряться, ни попасть в историю B.
  Future<void> _updateRun(
    String owner,
    String id,
    CompletedRun Function(CompletedRun) change,
  ) async {
    final prefs = await SharedPreferences.getInstance();
    if (owner == _owner) {
      state = [for (final r in state) r.id == id ? change(r) : r];
      await _writeBucket(prefs, owner, state);
    } else {
      final runs = _readBucket(prefs, owner);
      await _writeBucket(prefs, owner, [
        for (final r in runs) r.id == id ? change(r) : r,
      ]);
    }
  }

  // ── Жизненный цикл ───────────────────────────────────────────────────────

  Future<void> load() async {
    final prefs = await SharedPreferences.getInstance();
    await migrateLegacyStorage(prefs);
    final owner = _accountId;
    _owner = owner;
    state = owner == null ? const [] : _readBucket(prefs, owner);
    if (owner == null) return;
    unawaited(syncPending());
    unawaited(pullFromServer());
  }

  /// Сменилась сессия (вход, выход, другой аккаунт, новый токен).
  void onSessionChanged() {
    if (_accountId != _owner) {
      // Чужая история не должна мелькнуть ни на кадр — очищаем сразу.
      _owner = null;
      state = const [];
      unawaited(load());
      return;
    }
    if (_token != null) {
      unawaited(syncPending());
      unawaited(pullFromServer());
    }
  }

  Future<void> add(CompletedRun run) async {
    final fresh = run.copyWith(
      summarySynced: false,
      trackPending: run.hasSendableTrack,
    );
    final prefs = await SharedPreferences.getInstance();
    final owner = _accountId;
    if (owner == null) {
      // Бег за экраном входа, так что сюда не попадаем; но если сессия
      // пропала посреди забега — не кладём его в чужую историю.
      final orphans = _readBucket(prefs, unknownOwner);
      await _writeBucket(prefs, unknownOwner, _merge([fresh], orphans));
      return;
    }
    if (owner != _owner) {
      _owner = owner;
      state = _readBucket(prefs, owner);
    }
    state = _merge([fresh], state).take(_maxStoredRuns).toList();
    await _writeBucket(prefs, owner, state);
    unawaited(_syncRun(fresh));
  }

  // ── Доставка ─────────────────────────────────────────────────────────────

  Options _auth(String token) =>
      Options(headers: {'Authorization': 'Bearer $token'});

  /// Доставить забег: сводку (если ещё не принята), затем трек (если ждёт).
  Future<void> _syncRun(CompletedRun run) async {
    final owner = _owner;
    final token = _token;
    if (owner == null || token == null || owner != _accountId) return;
    if (!_inFlight.add(run.id)) return;
    try {
      // Берём свежую версию: пока ждали очереди, флаги могли измениться.
      var current = state.firstWhere((r) => r.id == run.id, orElse: () => run);
      if (!current.summarySynced) {
        if (!await _sendSummary(current, owner, token)) return;
        current = current.copyWith(summarySynced: true);
      }
      if (current.trackPending) await _sendTrack(current, owner, token);
    } finally {
      _inFlight.remove(run.id);
    }
  }

  /// Сводка забега (без сырого маршрута, приватность §2). Идемпотентно по id:
  /// повтор сервер отвечает duplicate без нового начисления. true — принята.
  Future<bool> _sendSummary(CompletedRun run, String owner, String token) async {
    final Response<dynamic> res;
    try {
      res = await _dio.post<dynamic>(
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
        options: _auth(token),
      );
    } catch (_) {
      return false; // офлайн/ошибка — досылка позже (возврат, вход, старт)
    }
    final body = res.data;
    // Анти-чит (S-04): сервер придержал баллы до разбора — карточка истории
    // покажет «на проверке» (флаг сохраняем и после перезапуска).
    final flagged =
        body is Map && (body['flagged'] == true || body['pendingReview'] == true);
    await _updateRun(
      owner,
      run.id,
      (r) => r.copyWith(summarySynced: true, pendingReview: flagged ? true : null),
    );
    if (owner == _owner) {
      // Сервер сам начислил очки за бег — сумму показываем в церемонии (Ф1).
      if (body is Map && body['pointsAwarded'] is num) {
        ref.read(lastRunPointsProvider.notifier).state = (
          runId: run.id,
          points: (body['pointsAwarded'] as num).toInt(),
        );
      }
      unawaited(ref.read(loyaltyProvider.notifier).refresh());
      // Сервер мог сказать что-то про этот забег (придержал баллы, веха, итоги
      // дивизиона) — тянем ленту сразу, а не после перезапуска.
      unawaited(ref.read(notificationsProvider.notifier).refresh());
    }
    return true;
  }

  /// Трек для троп: сервер найдёт прохождения и удалит трек через 14 дней
  /// (D-60). Идемпотентно по runId (сервер перезаписывает), баллов не начисляет.
  /// Сетевой сбой — трек остаётся в очереди и уйдёт при следующей досылке.
  Future<void> _sendTrack(CompletedRun run, String owner, String token) async {
    if (!run.hasSendableTrack) {
      await _updateRun(owner, run.id, (r) => r.copyWith(trackPending: false));
      return;
    }
    final Response<Map<String, dynamic>> res;
    try {
      res = await _dio.post<Map<String, dynamic>>(
        '/runs/track',
        data: {
          'runId': run.id,
          'points': [
            for (var i = 0; i < run.route.length; i++)
              [run.route[i].latitude, run.route[i].longitude, run.routeTimes[i]],
          ],
        },
        options: _auth(token),
      );
    } on DioException catch (e) {
      final code = e.response?.statusCode;
      final permanent = code != null &&
          code >= 400 &&
          code < 500 &&
          code != 401 &&
          code != 408 &&
          code != 429;
      if (permanent) {
        // Сервер отказал по существу (например, слишком короткий трек) —
        // повтор ничего не изменит, снимаем с очереди.
        await _updateRun(owner, run.id, (r) => r.copyWith(trackPending: false));
      }
      return;
    } catch (_) {
      return;
    }
    await _updateRun(owner, run.id, (r) => r.copyWith(trackPending: false));
    // Ответ — найденные прохождения троп: экран финиша покажет «Тропа
    // «Набережная» — 7:42». Только для последнего забега: догнавший трек
    // старого забега не должен всплыть на церемонии нового.
    final hits = ((res.data ?? const {})['attempts'] as List? ?? const [])
        .whereType<Map<String, dynamic>>()
        .map(TrailHit.fromJson)
        .toList();
    if (hits.isNotEmpty &&
        owner == _owner &&
        state.isNotEmpty &&
        state.first.id == run.id) {
      ref.read(lastTrailHitsProvider.notifier).state =
          LastTrailHits(runId: run.id, hits: hits);
    }
  }

  /// Дослать всё недоставленное вошедшего аккаунта: сводки и треки
  /// (старт приложения, вход, возврат из фона).
  Future<void> syncPending() async {
    if (_token == null) return;
    if (_accountId != _owner) {
      await load(); // сменился аккаунт — сначала его собственная история
      return;
    }
    for (final run in List<CompletedRun>.of(state)) {
      if (!run.summarySynced || run.trackPending) await _syncRun(run);
    }
  }

  /// Подтянуть забеги с сервера (кросс-девайс/после переустановки). Серверные
  /// забеги без маршрута (сырой GPS не хранится, §2) — карточки истории его и не
  /// используют (иконка + метрики). Локальные забеги (с маршрутом) в приоритете.
  Future<void> pullFromServer() async {
    final owner = _owner;
    final token = _token;
    if (owner == null || token == null || owner != _accountId) return;
    try {
      final r = await _dio.get<List<dynamic>>('/runs', options: _auth(token));
      // Пока ждали ответа, аккаунт мог смениться — не смешиваем истории.
      if (owner != _owner) return;
      final server = <CompletedRun>[];
      for (final item in (r.data ?? const [])) {
        if (item is! Map) continue;
        final m = Map<String, dynamic>.from(item);
        final id = m['id']?.toString();
        if (id == null || id.isEmpty) continue;
        server.add(CompletedRun(
          id: id,
          finishedAt: DateTime.fromMillisecondsSinceEpoch(
            (m['finishedAtMs'] as num? ?? 0).toInt(),
          ),
          route: const [], // сервер не хранит сырой маршрут (приватность §2)
          elapsed: Duration(seconds: (m['elapsedSeconds'] as num? ?? 0).toInt()),
          distanceMeters: (m['distanceMeters'] as num? ?? 0).toDouble(),
          capturedZones: (m['capturedZones'] as num? ?? 0).toInt(),
          capturedTerritory: m['capturedTerritory'] as bool? ?? false,
          pendingReview: m['pendingReview'] as bool? ?? false,
          summarySynced: true,
        ));
      }
      await _claimOrphans(owner, server.map((e) => e.id).toSet());
      if (owner != _owner) return;
      final merged = _merge(state, server);
      if (merged.length == state.length) return;
      state = merged.take(_maxStoredRuns).toList();
    } catch (_) {
      // офлайн/ошибка — покажем локальную историю
    }
  }

  /// Забрать из корзины «владелец неизвестен» забеги, которые сервер уже
  /// приписал этому аккаунту (их id есть в его GET /runs) — это доказанно его.
  Future<void> _claimOrphans(String owner, Set<String> serverIds) async {
    if (serverIds.isEmpty) return;
    final prefs = await SharedPreferences.getInstance();
    final orphans = _readBucket(prefs, unknownOwner);
    if (orphans.isEmpty) return;
    final mine = orphans.where((r) => serverIds.contains(r.id)).toList();
    if (mine.isEmpty || owner != _owner) return;
    await _writeBucket(
      prefs,
      unknownOwner,
      orphans.where((r) => !serverIds.contains(r.id)).toList(),
    );
    state = _merge(
      state,
      [for (final r in mine) r.copyWith(summarySynced: true)],
    ).take(_maxStoredRuns).toList();
    await _writeBucket(prefs, owner, state);
    // Трек, если ещё ждёт, дошлёт уже под своим токеном.
    for (final r in mine) {
      if (r.trackPending) unawaited(_syncRun(r));
    }
  }

  /// Резервная копия трека (D-86): тянем маршрут забега с сервера, когда локально
  /// его нет (переустановка/смена телефона). Работает, если у владельца включён
  /// бэкап треков. Пусто — трека на сервере нет. Точки приходят как [lat,lng,ts].
  Future<List<LatLng>> fetchTrack(String runId) async {
    final token = _token;
    if (token == null || runId.isEmpty) return const [];
    try {
      final r = await _dio.get<Map<String, dynamic>>(
        '/runs/$runId/track',
        options: _auth(token),
      );
      final pts = (r.data ?? const {})['points'] as List? ?? const [];
      return pts
          .whereType<List>()
          .where((p) => p.length >= 2)
          .map((p) => LatLng((p[0] as num).toDouble(), (p[1] as num).toDouble()))
          .toList();
    } catch (_) {
      return const [];
    }
  }
}

final completedRunsProvider =
    StateNotifierProvider<CompletedRunsNotifier, List<CompletedRun>>((ref) {
      final notifier = CompletedRunsNotifier(ref);
      // Вход / выход / другой аккаунт / новый токен: переключаем историю на
      // вошедшего и досылаем ЕГО накопленные забеги (не чужие).
      ref.listen<AuthState>(authProvider, (prev, next) {
        final prevId = prev?.user?.id ?? '';
        final nextId = next.user?.id ?? '';
        final newToken = next.token != null &&
            next.token!.isNotEmpty &&
            next.token != prev?.token;
        if (prevId != nextId || newToken) notifier.onSessionChanged();
      });
      return notifier;
    });

/// Баллы, начисленные сервером за последнюю отправленную пробежку —
/// церемония итогов (Ф1) дорисовывает «+N баллов», когда ответ долетел.
final lastRunPointsProvider =
    StateProvider<({String runId, int points})?>((_) => null);
