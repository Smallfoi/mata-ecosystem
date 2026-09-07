import 'dart:async' show unawaited;
import 'dart:convert';
import 'dart:math';
import 'package:dio/dio.dart';
import 'package:flutter/services.dart' show rootBundle;
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:latlong2/latlong.dart';
import 'package:shared_preferences/shared_preferences.dart';

enum ZoneOwner { free, mine, club, enemy }

class BlockZone {
  final String id;
  final List<LatLng> vertices;
  final LatLng centroid;
  final ZoneOwner owner;

  const BlockZone({
    required this.id,
    required this.vertices,
    required this.centroid,
    required this.owner,
  });

  BlockZone copyWith({ZoneOwner? owner}) => BlockZone(
    id: id,
    vertices: vertices,
    centroid: centroid,
    owner: owner ?? this.owner,
  );
}

class CapturedArea {
  final String id;
  final List<LatLng> vertices;
  final DateTime capturedAt;

  const CapturedArea({
    required this.id,
    required this.vertices,
    required this.capturedAt,
  });
}

class LoopClosureStatus {
  final bool hasEnoughDistance;
  final bool isClosed;
  final double distanceMeters;
  final double gapMeters;

  const LoopClosureStatus({
    required this.hasEnoughDistance,
    required this.isClosed,
    required this.distanceMeters,
    required this.gapMeters,
  });

  bool get canCapture => hasEnoughDistance && isClosed;
}

bool pointInPolygon(LatLng p, List<LatLng> poly) {
  var inside = false;
  for (int i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    final xi = poly[i].longitude, yi = poly[i].latitude;
    final xj = poly[j].longitude, yj = poly[j].latitude;
    if (((yi > p.latitude) != (yj > p.latitude)) &&
        (p.longitude < (xj - xi) * (p.latitude - yi) / (yj - yi) + xi)) {
      inside = !inside;
    }
  }
  return inside;
}

double distMeters(LatLng a, LatLng b) {
  final dlat = (b.latitude - a.latitude) * 111320.0;
  final dlng = (b.longitude - a.longitude) * 52250.0;
  return sqrt(dlat * dlat + dlng * dlng);
}

// Источник полигонов кварталов (отдельный zones-сервис, не общий API).
// Прод/иной хост: --dart-define=KVARTAL_ZONES_URL=https://.../api/zones
const _backendUrl = String.fromEnvironment(
  'KVARTAL_ZONES_URL',
  defaultValue: 'http://localhost:3000/api/zones',
);
const _capturedZoneIdsKey = 'kvartal.captured_zone_ids.v1';
const _capturedAreasKey = 'kvartal.captured_areas.v1';
const _mapCleanupOnceKey = 'kvartal.map_cleanup_2026_06_21.v2';
const _activeRunStorageKey = 'kvartal.active_run.v1';
const _completedRunsKey = 'kvartal.completed_runs.v1';
const _minCaptureLoopMeters = 50.0;
const _maxLoopGapMeters = 20.0;

ZoneOwner _ownerFromString(String s) {
  switch (s) {
    case 'mine':
      return ZoneOwner.mine;
    case 'club':
      return ZoneOwner.club;
    case 'enemy':
      return ZoneOwner.enemy;
    default:
      return ZoneOwner.free;
  }
}

Future<List<BlockZone>> _fetchFromBackend() async {
  final dio = Dio();
  final response = await dio.get<Map<String, dynamic>>(
    _backendUrl,
    options: Options(
      receiveTimeout: const Duration(seconds: 20),
      sendTimeout: const Duration(seconds: 5),
      validateStatus: (s) => s != null && s < 600,
    ),
  );
  if (response.statusCode == 503) {
    throw _BackendLoadingException();
  }
  final list = response.data?['zones'] as List? ?? [];
  return _parseZoneList(list);
}

class _BackendLoadingException implements Exception {}

Future<List<BlockZone>> _parseZoneList(List<dynamic> list) async {
  return list.map((z) {
    final rawVerts = z['vertices'] as List;
    final verts = rawVerts
        .map(
          (v) => LatLng(
            (v['lat'] as num).toDouble(),
            (v['lng'] as num).toDouble(),
          ),
        )
        .toList();
    final c = z['centroid'] as Map<String, dynamic>;
    return BlockZone(
      id: z['id'] as String,
      vertices: verts,
      centroid: LatLng(
        (c['lat'] as num).toDouble(),
        (c['lng'] as num).toDouble(),
      ),
      owner: _ownerFromString(z['owner'] as String? ?? 'free'),
    );
  }).toList();
}

Future<List<BlockZone>> _loadFromAssets() async {
  final raw = await rootBundle.loadString('assets/zones.json');
  final data = jsonDecode(raw) as Map<String, dynamic>;
  final list = data['zones'] as List;
  return _parseZoneList(list);
}

class ZoneNotifier extends StateNotifier<AsyncValue<List<BlockZone>>> {
  ZoneNotifier() : super(const AsyncValue.loading()) {
    _init();
  }

  List<BlockZone> _initialState = [];
  Set<String> _capturedZoneIds = {};
  List<CapturedArea> _capturedAreas = [];
  String? _lastCapturedAreaSignature;

  Future<void> _init() async {
    await _clearMapDataOnce();
    _capturedZoneIds = await _loadCapturedZoneIds();
    // Локальные «захваченные области» больше не живут между сессиями:
    // на карте один источник правды — серверные territories («Идеальный
    // маршрут», 03.09). Старые сохранённые контуры чистим.
    _capturedAreas = [];
    unawaited(SharedPreferences.getInstance().then(
      (p) => p.remove(_capturedAreasKey),
    ));

    for (int attempt = 1; ; attempt++) {
      try {
        final zones = await _fetchFromBackend();
        _initialState = zones;
        state = AsyncValue.data(_applyCapturedOwners(zones));
        return;
      } on _BackendLoadingException {
        await Future.delayed(const Duration(seconds: 5));
      } catch (_) {
        try {
          final zones = await _loadFromAssets();
          _initialState = zones;
          state = AsyncValue.data(_applyCapturedOwners(zones));
        } catch (e, st) {
          state = AsyncValue.error(e, st);
        }
        return;
      }
    }
  }


  Future<void> _clearMapDataOnce() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      if (prefs.getBool(_mapCleanupOnceKey) == true) return;
      await prefs.remove(_capturedZoneIdsKey);
      await prefs.remove(_capturedAreasKey);
      await prefs.remove(_activeRunStorageKey);
      await prefs.remove(_completedRunsKey);
      await prefs.setBool(_mapCleanupOnceKey, true);
      _capturedZoneIds = {};
      _capturedAreas = [];
      _lastCapturedAreaSignature = null;
    } catch (_) {
      // Cleanup is best-effort; normal loading below still keeps the map usable.
    }
  }

  List<BlockZone> get zones => state.valueOrNull ?? [];
  List<CapturedArea> get capturedAreas => List.unmodifiable(_capturedAreas);

  bool get isLoading => state is AsyncLoading;
  bool get hasError => state is AsyncError;
  String get errorMessage => state.hasError ? state.error.toString() : '';

  Future<Set<String>> _loadCapturedZoneIds() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      return (prefs.getStringList(_capturedZoneIdsKey) ?? const <String>[])
          .toSet();
    } catch (_) {
      return {};
    }
  }


  Future<void> retry() async {
    state = const AsyncValue.loading();
    await _init();
  }

  Future<void> _saveCapturedZoneIds() async {
    final prefs = await SharedPreferences.getInstance();
    final ids = _capturedZoneIds.toList()..sort();
    await prefs.setStringList(_capturedZoneIdsKey, ids);
  }

  Future<void> _saveCapturedAreas() async {
    final prefs = await SharedPreferences.getInstance();
    final data = [
      for (final area in _capturedAreas)
        {
          'id': area.id,
          'capturedAtMs': area.capturedAt.millisecondsSinceEpoch,
          'vertices': [
            for (final p in area.vertices) [p.latitude, p.longitude],
          ],
        },
    ];
    await prefs.setString(_capturedAreasKey, jsonEncode(data));
  }

  List<BlockZone> _applyCapturedOwners(List<BlockZone> source) {
    if (_capturedZoneIds.isEmpty) return source;
    return [
      for (final z in source)
        _capturedZoneIds.contains(z.id) ? z.copyWith(owner: ZoneOwner.mine) : z,
    ];
  }

  LoopClosureStatus inspectLoopClosure(List<LatLng> route) {
    if (route.length < 2) {
      return const LoopClosureStatus(
        hasEnoughDistance: false,
        isClosed: false,
        distanceMeters: 0,
        gapMeters: 0,
      );
    }

    double total = 0;
    for (int i = 1; i < route.length; i++) {
      total += distMeters(route[i - 1], route[i]);
    }
    final gap = distMeters(route.first, route.last);
    return LoopClosureStatus(
      hasEnoughDistance: total >= _minCaptureLoopMeters,
      isClosed: gap <= _maxLoopGapMeters,
      distanceMeters: total,
      gapMeters: gap,
    );
  }

  List<String> checkAndCaptureLoop(List<LatLng> route) {
    if (route.length < 4) return [];

    final closure = inspectLoopClosure(route);
    if (!closure.hasEnoughDistance) return [];
    if (!closure.isClosed) return [];

    final capturePolygon = route.last == route.first
        ? route
        : [...route, route.first];

    final current = zones;
    final captured = <String>[];
    for (final z in current) {
      if (z.owner == ZoneOwner.mine) continue;
      if (pointInPolygon(z.centroid, capturePolygon)) captured.add(z.id);
    }

    final shouldSaveArea = captured.isNotEmpty || !_isCapturedAreaKnown(capturePolygon);
    if (shouldSaveArea) {
      _saveCapturedArea(capturePolygon);
    }

    if (captured.isNotEmpty) {
      _capturedZoneIds.addAll(captured);
      unawaited(_saveCapturedZoneIds());
    }

    if (state.hasValue) {
      state = AsyncValue.data([
        for (final z in current)
          if (captured.contains(z.id)) z.copyWith(owner: ZoneOwner.mine) else z,
      ]);
    }
    return captured;
  }


  bool _isCapturedAreaKnown(List<LatLng> polygon) {
    final signature = _areaSignature(polygon);
    if (_lastCapturedAreaSignature == signature) return true;
    return _capturedAreas.any(
      (area) => _areaSignature(area.vertices) == signature,
    );
  }

  void _saveCapturedArea(List<LatLng> polygon) {
    final signature = _areaSignature(polygon);
    if (_isCapturedAreaKnown(polygon)) {
      return;
    }

    _lastCapturedAreaSignature = signature;
    final now = DateTime.now();
    _capturedAreas = [
      ..._capturedAreas,
      CapturedArea(
        id: 'area-${now.millisecondsSinceEpoch}',
        vertices: polygon,
        capturedAt: now,
      ),
    ];
    unawaited(_saveCapturedAreas());
  }

  String _areaSignature(List<LatLng> polygon) {
    if (polygon.isEmpty) return 'empty';
    final first = polygon.first;
    final middle = polygon.length > 2
        ? polygon[polygon.length ~/ 2]
        : polygon.last;
    return [
      (first.latitude * 10000).round(),
      (first.longitude * 10000).round(),
      (middle.latitude * 10000).round(),
      (middle.longitude * 10000).round(),
      polygon.length ~/ 8,
    ].join(':');
  }

  void reset() {
    if (_initialState.isNotEmpty) {
      state = AsyncValue.data(_applyCapturedOwners(_initialState));
    }
  }
}

final zoneProvider =
    StateNotifierProvider<ZoneNotifier, AsyncValue<List<BlockZone>>>(
      (_) => ZoneNotifier(),
    );

final capturedAreasProvider = Provider<List<CapturedArea>>((ref) {
  ref.watch(zoneProvider);
  return ref.read(zoneProvider.notifier).capturedAreas;
});
