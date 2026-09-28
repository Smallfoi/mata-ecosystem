import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:latlong2/latlong.dart';

import '../../../core/api/api_client.dart';
import '../../auth/data/auth_provider.dart';
import '../../territory/data/territory_provider.dart' show ringsFromGeoJson;
import 'location_provider.dart';

/// Подсказка захвата: ближайший свободный квартал как готовый круг (D-74).
///
/// Владелец (27.09.2026): «при захвате должен появиться маршрут круговой». Раньше
/// человек сам угадывал, где замкнуть петлю, и узнавал результат только на финише.
/// Теперь в режиме «Захват» карта показывает конкретный контур и его длину.
class LoopSuggestion {
  final String blockId;
  final String? district;

  /// Длина круга (периметр квартала), м — это и есть дистанция забега.
  final int loopMeters;

  /// Сколько до него от текущей точки, м.
  final int distanceMeters;

  /// Контур квартала для карты (внешние кольца).
  final List<List<LatLng>> rings;

  const LoopSuggestion({
    required this.blockId,
    required this.loopMeters,
    required this.distanceMeters,
    required this.rings,
    this.district,
  });

  /// «1,2 км» / «850 м» — как человек говорит о дистанции.
  String get loopLabel => loopMeters >= 1000
      ? '${(loopMeters / 1000).toStringAsFixed(1).replaceAll('.', ',')} км'
      : '$loopMeters м';

  /// «рядом» вместо «12 м»: точности GPS всё равно не хватит на такую точность.
  String get distanceLabel {
    if (distanceMeters <= 60) return 'рядом';
    if (distanceMeters >= 1000) {
      return '${(distanceMeters / 1000).toStringAsFixed(1).replaceAll('.', ',')} км до старта';
    }
    return '$distanceMeters м до старта';
  }

  static LoopSuggestion? fromJson(Map<String, dynamic>? j) {
    if (j == null) return null;
    final geojson = j['geojson'];
    final rings = geojson is Map<String, dynamic>
        ? ringsFromGeoJson(geojson)
        : const <List<LatLng>>[];
    if (rings.isEmpty) return null;
    return LoopSuggestion(
      blockId: j['blockId']?.toString() ?? '',
      district: j['district']?.toString(),
      loopMeters: (j['loopMeters'] as num?)?.toInt() ?? 0,
      distanceMeters: (j['distanceMeters'] as num?)?.toInt() ?? 0,
      rings: rings,
    );
  }
}

final _dio = ApiClient.create(
  headers: const {'Content-Type': 'application/json', 'Connection': 'close'},
);

/// Ближайший свободный квартал к текущей позиции. Пусто — значит рядом свободных
/// нет (в лесу, в другом городе, всё вокруг занято); подсказки просто не будет.
///
/// Позицию огрубляем до ~100 м: иначе каждый GPS-фикс дёргал бы сервер, а на
/// улице связи может не быть вовсе (D-77: бег не должен зависеть от сети).
final loopSuggestionProvider =
    FutureProvider.autoDispose<LoopSuggestion?>((ref) async {
  final token = ref.watch(authProvider).token;
  if (token == null || token.isEmpty) return null;
  final pos = ref.watch(positionStreamProvider).valueOrNull;
  if (pos == null) return null;
  final lat = (pos.latitude * 1000).round() / 1000;
  final lon = (pos.longitude * 1000).round() / 1000;
  try {
    final res = await _dio.get<Map<String, dynamic>>(
      '/blocks/nearest',
      queryParameters: {'lat': lat, 'lon': lon},
      options: Options(headers: {'Authorization': 'Bearer $token'}),
    );
    return LoopSuggestion.fromJson(
      (res.data ?? const {})['block'] as Map<String, dynamic>?,
    );
  } catch (_) {
    // Нет сети — нет подсказки. Бежать это не мешает.
    return null;
  }
});
