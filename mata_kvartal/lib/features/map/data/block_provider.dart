import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:latlong2/latlong.dart';

import '../../../core/api/api_client.dart';
import '../../auth/data/auth_provider.dart';
// Переиспользуем разбор GeoJSON из territory_provider — один парсер колец на
// весь проект (не дублируем): Polygon/MultiPolygon → внешние кольца LatLng.
import '../../territory/data/territory_provider.dart' show ringsFromGeoJson;

/// Отношение городского квартала к текущему пользователю (механика захвата D-74).
/// Отдельно от TerritoryRel: у кварталов есть состояние `free` (ничей),
/// которого нет у живых территорий.
enum BlockRel { mine, club, enemy, free }

BlockRel _blockRelFromString(String? s) {
  switch (s) {
    case 'mine':
      return BlockRel.mine;
    case 'club':
      return BlockRel.club;
    case 'enemy':
      return BlockRel.enemy;
    default:
      return BlockRel.free;
  }
}

/// Городской квартал (нарезка ~632 кварталов Якутска, D-74). Геометрия и
/// владение приходят с бэка (`GET /v1/blocks`). Контур(ы) — внешние кольца.
class CityBlock {
  final String blockId;

  /// Район города (например «Сайсары») — может быть null для окраинных кварталов.
  final String? district;
  final BlockRel rel;
  final String? ownerId;
  final String? ownerName;

  /// Внешние кольца полигонов (Polygon → одно, MultiPolygon → по кольцу на часть).
  final List<List<LatLng>> rings;

  const CityBlock({
    required this.blockId,
    required this.district,
    required this.rel,
    required this.ownerId,
    required this.ownerName,
    required this.rings,
  });

  factory CityBlock.fromJson(Map<String, dynamic> json) {
    final geojson = json['geojson'];
    return CityBlock(
      blockId: json['blockId']?.toString() ?? '',
      district: json['district']?.toString(),
      rel: _blockRelFromString(json['rel']?.toString()),
      ownerId: json['ownerId']?.toString(),
      ownerName: json['ownerName']?.toString(),
      rings: geojson is Map<String, dynamic>
          ? ringsFromGeoJson(geojson)
          : const [],
    );
  }
}

class BlockState {
  final List<CityBlock> blocks;
  final bool isLoading;

  const BlockState({this.blocks = const [], this.isLoading = false});

  BlockState copyWith({List<CityBlock>? blocks, bool? isLoading}) => BlockState(
    blocks: blocks ?? this.blocks,
    isLoading: isLoading ?? this.isLoading,
  );
}

/// Кварталы видимой области карты (D-74). Живёт рядом с territoryProvider и
/// грузится на тех же хуках карты (пан/зум, таймер, возврат на вкладку).
class BlockNotifier extends StateNotifier<BlockState> {
  final Ref ref;
  BlockNotifier(this.ref) : super(const BlockState());

  final Dio _dio = ApiClient.create(
    headers: {'Content-Type': 'application/json', 'Connection': 'close'},
  );

  String? get _token {
    final token = ref.read(authProvider).token;
    return (token == null || token.isEmpty) ? null : token;
  }

  /// Загрузить кварталы в видимой области карты.
  /// bbox порядок — minLng, minLat, maxLng, maxLat (как ждёт бэк).
  Future<void> loadBbox({
    required double minLng,
    required double minLat,
    required double maxLng,
    required double maxLat,
  }) async {
    final token = _token;
    if (token == null) return;
    state = state.copyWith(isLoading: true);
    try {
      final response = await _dio.get<Map<String, dynamic>>(
        '/blocks',
        queryParameters: {'bbox': '$minLng,$minLat,$maxLng,$maxLat'},
        options: Options(headers: {'Authorization': 'Bearer $token'}),
      );
      final list = (response.data?['blocks'] as List? ?? const [])
          .whereType<Map<String, dynamic>>()
          .map(CityBlock.fromJson)
          .where((b) => b.rings.isNotEmpty)
          .toList();
      state = state.copyWith(blocks: list, isLoading: false);
    } catch (_) {
      // Ошибки гасим как в territory_provider: сетка города вспомогательная,
      // её пропажа не должна ронять карту — просто не обновляем.
      state = state.copyWith(isLoading: false);
    }
  }

  /// Сброс при смене аккаунта — окраска кварталов больше не наша.
  void reset() => state = const BlockState();
}

final blockProvider = StateNotifierProvider<BlockNotifier, BlockState>((ref) {
  final notifier = BlockNotifier(ref);
  // При смене аккаунта окраска «моё/клуб/чужое» устарела — сбрасываем.
  ref.listen<AuthState>(authProvider, (prev, next) {
    if (next.token != prev?.token) {
      notifier.reset();
    }
  });
  return notifier;
});
