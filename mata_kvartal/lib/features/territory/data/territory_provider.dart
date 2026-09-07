import 'dart:async' show unawaited;
import 'dart:convert';
import 'dart:math' show Random;

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:latlong2/latlong.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../../../core/api/api_config.dart';
import '../../auth/data/auth_provider.dart';
import '../../loyalty/data/loyalty_provider.dart';
import '../../run/data/route_cleaner.dart';

/// Отношение территории к текущему пользователю (приходит с сервера).
enum TerritoryRel { mine, club, enemy }

TerritoryRel _relFromString(String? s) {
  switch (s) {
    case 'mine':
      return TerritoryRel.mine;
    case 'club':
      return TerritoryRel.club;
    default:
      return TerritoryRel.enemy;
  }
}

/// Реальная территория с PostGIS-бэка (D-09). Контур(ы) уже сглажены сервером.
class ServerTerritory {
  final String ownerId;

  /// Имя владельца — публичная часть паспорта квартала (Ф2), как в рейтинге.
  final String ownerName;
  final String? clubId;
  final TerritoryRel rel;

  /// Когда захвачен (мс) — «держит N дней» в паспорте.
  final int capturedAtMs;

  /// Сколько часов осталось до конца 72ч-удержания (для UI «защищено ещё Nч»).
  final double? holdHoursLeft;

  /// Внешние кольца полигонов (для MultiPolygon — по кольцу на полигон).
  final List<List<LatLng>> rings;

  const ServerTerritory({
    required this.ownerId,
    this.ownerName = 'Бегун',
    required this.clubId,
    required this.rel,
    required this.rings,
    this.holdHoursLeft,
    this.capturedAtMs = 0,
  });

  factory ServerTerritory.fromJson(Map<String, dynamic> json) {
    final geojson = json['geojson'];
    return ServerTerritory(
      ownerName: json['ownerName']?.toString() ?? 'Бегун',
      capturedAtMs: (json['capturedAtMs'] as num?)?.toInt() ?? 0,
      ownerId: json['ownerId']?.toString() ?? '',
      clubId: json['clubId']?.toString(),
      rel: _relFromString(json['rel']?.toString()),
      holdHoursLeft: (json['holdHoursLeft'] as num?)?.toDouble(),
      rings: geojson is Map<String, dynamic>
          ? ringsFromGeoJson(geojson)
          : const [],
    );
  }
}

/// Разбор GeoJSON (Polygon / MultiPolygon) во внешние кольца LatLng.
/// Координаты GeoJSON идут как [lng, lat] — переворачиваем в LatLng(lat, lng).
List<List<LatLng>> ringsFromGeoJson(Map<String, dynamic> geojson) {
  final type = geojson['type']?.toString();
  final coords = geojson['coordinates'];
  final rings = <List<LatLng>>[];
  if (type == 'Polygon' && coords is List && coords.isNotEmpty) {
    rings.add(_ring(coords.first));
  } else if (type == 'MultiPolygon' && coords is List) {
    for (final polygon in coords) {
      if (polygon is List && polygon.isNotEmpty) {
        rings.add(_ring(polygon.first));
      }
    }
  }
  return rings.where((r) => r.length >= 3).toList();
}

List<LatLng> _ring(dynamic ring) {
  final out = <LatLng>[];
  if (ring is List) {
    for (final point in ring) {
      if (point is List && point.length >= 2) {
        out.add(
          LatLng((point[1] as num).toDouble(), (point[0] as num).toDouble()),
        );
      }
    }
  }
  return out;
}

class TerritoryState {
  final List<ServerTerritory> territories;
  final bool isLoading;
  final bool isCapturing;
  final String? error;
  final String? message;

  /// Площадь моей территории после последнего захвата, м².
  final double? lastAreaM2;

  const TerritoryState({
    this.territories = const [],
    this.isLoading = false,
    this.isCapturing = false,
    this.error,
    this.message,
    this.lastAreaM2,
  });

  TerritoryState copyWith({
    List<ServerTerritory>? territories,
    bool? isLoading,
    bool? isCapturing,
    String? error,
    String? message,
    double? lastAreaM2,
    bool clearError = false,
    bool clearMessage = false,
  }) => TerritoryState(
    territories: territories ?? this.territories,
    isLoading: isLoading ?? this.isLoading,
    isCapturing: isCapturing ?? this.isCapturing,
    error: clearError ? null : error ?? this.error,
    message: clearMessage ? null : message ?? this.message,
    lastAreaM2: lastAreaM2 ?? this.lastAreaM2,
  );
}

class TerritoryNotifier extends StateNotifier<TerritoryState> {
  final Ref ref;
  TerritoryNotifier(this.ref) : super(const TerritoryState());

  final Dio _dio = Dio(
    BaseOptions(
      baseUrl: ApiConfig.baseUrl,
      connectTimeout: ApiConfig.connectTimeout,
      receiveTimeout: ApiConfig.receiveTimeout,
      headers: {'Content-Type': 'application/json', 'Connection': 'close'},
    ),
  );

  String? get _token {
    final token = ref.read(authProvider).token;
    return (token == null || token.isEmpty) ? null : token;
  }

  /// Загрузить территории в видимой области карты.
  /// bbox порядок — minLng, minLat, maxLng, maxLat (как ждёт бэк).
  Future<void> loadBbox({
    required double minLng,
    required double minLat,
    required double maxLng,
    required double maxLat,
  }) async {
    final token = _token;
    if (token == null) return;
    state = state.copyWith(isLoading: true, clearError: true);
    try {
      final response = await _dio.get<Map<String, dynamic>>(
        '/territories',
        queryParameters: {'bbox': '$minLng,$minLat,$maxLng,$maxLat'},
        options: Options(headers: {'Authorization': 'Bearer $token'}),
      );
      final list = (response.data?['territories'] as List? ?? const [])
          .whereType<Map<String, dynamic>>()
          .map(ServerTerritory.fromJson)
          .where((t) => t.rings.isNotEmpty)
          .toList();
      state = state.copyWith(
        territories: list,
        isLoading: false,
        clearError: true,
      );
    } catch (e) {
      state = state.copyWith(isLoading: false, error: _errorText(e));
    }
  }

  /// Отправить замкнутый маршрут на сервер для захвата территории.
  /// distanceMeters/elapsedSeconds — для серверного античита по скорости.
  /// Возвращает площадь моей территории (м²) или null при ошибке.
  Future<double?> capture(
    List<LatLng> route, {
    double? distanceMeters,
    int? elapsedSeconds,
  }) async {
    final token = _token;
    if (token == null || route.length < 3) return null;
    // Чистим трек ЗДЕСЬ (шипы + Дуглас-Пекер): одна точка входа защищает и
    // онлайн-захват, и офлайн-очередь («Идеальный маршрут», 03.09.2026).
    final cleaned = cleanRoute(route);
    if (cleaned.length < 3) return null;
    final captureId = _newCaptureId();
    state = state.copyWith(isCapturing: true, clearError: true, clearMessage: true);
    final body = <String, dynamic>{
      'points': [
        for (final p in cleaned) [p.latitude, p.longitude],
      ],
      'captureId': captureId, // идемпотентность (S-04): ретрай не задвоит
      if (distanceMeters != null) 'distanceMeters': distanceMeters,
      if (elapsedSeconds != null) 'elapsedSeconds': elapsedSeconds,
    };
    try {
      final response = await _dio.post<Map<String, dynamic>>(
        '/territories/capture',
        data: body,
        options: Options(headers: {'Authorization': 'Bearer $token'}),
      );
      return _applyCaptureResponse(response.data ?? const <String, dynamic>{});
    } on DioException catch (e) {
      if (e.response == null) {
        // Нет связи (улица/сбой сети): сохраняем в офлайн-очередь (S-07),
        // отправим автоматически при подключении; captureId не даст задвоить.
        await _enqueueCapture(body);
        state = state.copyWith(
          isCapturing: false,
          clearError: true,
          message: 'Нет связи — территория сохранена, отправим автоматически.',
        );
        return null;
      }
      state = state.copyWith(isCapturing: false, error: _errorText(e));
      return null;
    } catch (e) {
      state = state.copyWith(isCapturing: false, error: _errorText(e));
      return null;
    }
  }

  /// Применить ответ сервера на захват к состоянию (своя территория сразу видна).
  double? _applyCaptureResponse(Map<String, dynamic> data) {
    final area = (data['areaM2'] as num?)?.toDouble();
    // Сервер начислил очки за захват (анти-чит S-04 Phase 2) — обновляем баланс.
    if (area != null) {
      unawaited(ref.read(loyaltyProvider.notifier).refresh());
    }
    final geojson = data['geojson'];
    if (geojson is Map<String, dynamic>) {
      final mine = ServerTerritory(
        ownerId: 'me',
        clubId: null,
        rel: TerritoryRel.mine,
        holdHoursLeft: (data['holdHoursLeft'] as num?)?.toDouble(),
        rings: ringsFromGeoJson(geojson),
      );
      final others =
          state.territories.where((t) => t.rel != TerritoryRel.mine).toList();
      state = state.copyWith(
        territories: mine.rings.isEmpty ? others : [...others, mine],
        isCapturing: false,
        lastAreaM2: area,
        message: area != null
            ? 'Территория захвачена: ${formatAreaM2(area)}'
            : 'Территория захвачена',
        clearError: true,
      );
    } else {
      state = state.copyWith(isCapturing: false, lastAreaM2: area);
    }
    return area;
  }

  String _newCaptureId() =>
      'cap_${DateTime.now().microsecondsSinceEpoch}_${Random().nextInt(1 << 32)}';

  static const _captureQueueKey = 'kvartal.capture_queue.v1';

  Future<void> _enqueueCapture(Map<String, dynamic> body) async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final list = prefs.getStringList(_captureQueueKey) ?? <String>[];
      list.add(jsonEncode(body));
      await prefs.setStringList(_captureQueueKey, list);
    } catch (_) {}
  }

  /// Отправить отложенные офлайн-захваты, когда появилась связь (S-07).
  /// Идемпотентно (captureId): дубликаты сервер отсечёт. Успешные/отклонённые
  /// убираем из очереди; на сетевой ошибке — оставляем остаток на потом.
  Future<void> flushQueue() async {
    final token = _token;
    if (token == null) return;
    List<String> list;
    try {
      final prefs = await SharedPreferences.getInstance();
      list = prefs.getStringList(_captureQueueKey) ?? <String>[];
    } catch (_) {
      return;
    }
    if (list.isEmpty) return;

    final remaining = <String>[];
    var networkDown = false;
    var deliveredAny = false;
    for (final raw in list) {
      if (networkDown) {
        remaining.add(raw);
        continue;
      }
      Map<String, dynamic> body;
      try {
        body = jsonDecode(raw) as Map<String, dynamic>;
      } catch (_) {
        continue; // битая запись — выбрасываем
      }
      try {
        await _dio.post<Map<String, dynamic>>(
          '/territories/capture',
          data: body,
          options: Options(headers: {'Authorization': 'Bearer $token'}),
        );
        deliveredAny = true; // успех (в т.ч. duplicate) → убираем из очереди
      } on DioException catch (e) {
        if (e.response == null) {
          networkDown = true; // связи нет — остаток на потом
          remaining.add(raw);
        }
        // сервер 4xx (отклонён/дубликат) → разрешено, убираем
      } catch (_) {
        remaining.add(raw);
      }
    }
    try {
      final prefs = await SharedPreferences.getInstance();
      if (remaining.isEmpty) {
        await prefs.remove(_captureQueueKey);
      } else {
        await prefs.setStringList(_captureQueueKey, remaining);
      }
    } catch (_) {}
    if (deliveredAny) {
      // Сервер начислил очки за отправленные захваты — обновляем баланс.
      unawaited(ref.read(loyaltyProvider.notifier).refresh());
      if (remaining.isEmpty) {
        state = state.copyWith(message: 'Офлайн-захваты отправлены.');
      }
    }
  }

  void clearMessage() => state = state.copyWith(clearMessage: true, clearError: true);

  /// Сброс при смене аккаунта — чужие/старые территории больше не наши.
  void reset() => state = const TerritoryState();

  String _arealessFallback() => 'Не удалось обработать территорию.';

  String _errorText(Object error) {
    if (error is DioException) {
      final data = error.response?.data;
      if (data is Map && data['detail'] != null) {
        return data['detail'].toString();
      }
      if (error.type == DioExceptionType.connectionTimeout ||
          error.type == DioExceptionType.receiveTimeout ||
          error.type == DioExceptionType.connectionError) {
        return 'Нет связи с сервером территорий. Проверь backend и USB/Wi-Fi.';
      }
    }
    return _arealessFallback();
  }
}

/// Человекочитаемая площадь: м² → га → км².
String formatAreaM2(double areaM2) {
  if (areaM2 >= 1000000) {
    return '${(areaM2 / 1000000).toStringAsFixed(2)} км²';
  }
  if (areaM2 >= 10000) {
    return '${(areaM2 / 10000).toStringAsFixed(2)} га';
  }
  return '${areaM2.round()} м²';
}

final territoryProvider =
    StateNotifierProvider<TerritoryNotifier, TerritoryState>((ref) {
      final notifier = TerritoryNotifier(ref);
      // При смене аккаунта старые территории больше не наши — сбрасываем.
      ref.listen<AuthState>(authProvider, (prev, next) {
        if (next.token != prev?.token) {
          notifier.reset();
          // Появился токен (вход/восстановление) — досылаем офлайн-захваты.
          if (next.token != null && next.token!.isNotEmpty) {
            notifier.flushQueue();
          }
        }
      });
      return notifier;
    });

/// Вечный личный след: суммарная исследованная площадь (м²), не уменьшается.
/// Для профиля «исследовано N км²» (живой слой территорий — отдельно, распадается).
final footprintAreaProvider = FutureProvider.autoDispose<double>((ref) async {
  final token = ref.watch(authProvider).token;
  if (token == null || token.isEmpty) return 0;
  final dio = Dio(
    BaseOptions(
      baseUrl: ApiConfig.baseUrl,
      connectTimeout: ApiConfig.connectTimeout,
      receiveTimeout: ApiConfig.receiveTimeout,
      headers: const {'Content-Type': 'application/json', 'Connection': 'close'},
    ),
  );
  try {
    final res = await dio.get<Map<String, dynamic>>(
      '/footprint',
      options: Options(headers: {'Authorization': 'Bearer $token'}),
    );
    return (res.data?['areaM2'] as num?)?.toDouble() ?? 0;
  } catch (_) {
    return 0;
  }
});
