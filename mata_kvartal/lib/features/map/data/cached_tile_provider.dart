import 'dart:async';
import 'dart:ui' as ui;

import 'package:flutter/foundation.dart';
import 'package:flutter/painting.dart';
import 'package:flutter_cache_manager/flutter_cache_manager.dart';
import 'package:flutter_map/flutter_map.dart';

/// Тайлы подложки с кэшем на диске телефона (этап 4 оптимизации, 21.11.2026).
///
/// flutter_map 7 по умолчанию держит тайлы только в памяти: после перезапуска
/// приложения карта скачивалась заново — на телефоне владельца серые квадраты
/// висели до ~5,8 с после старта. Теперь уже виденные тайлы берутся с диска
/// мгновенно, а сеть нужна только для новых мест.
///
/// Кэш живёт 30 дней и ограничен числом тайлов — это примерно десятки мегабайт,
/// город и окрестности. Тайлы CARTO и OSM разрешают обычное клиентское
/// кэширование (как браузер кэширует картинки).
class CachedTileProvider extends TileProvider {
  CachedTileProvider({super.headers});

  static final CacheManager _cache = CacheManager(
    Config(
      'kvartal_map_tiles',
      stalePeriod: const Duration(days: 30),
      maxNrOfCacheObjects: 6000,
    ),
  );

  @override
  ImageProvider getImage(TileCoordinates coordinates, TileLayer options) =>
      _CachedTileImage(getTileUrl(coordinates, options), headers);
}

@immutable
class _CachedTileImage extends ImageProvider<_CachedTileImage> {
  const _CachedTileImage(this.url, this.headers);

  final String url;
  final Map<String, String> headers;

  @override
  Future<_CachedTileImage> obtainKey(ImageConfiguration configuration) =>
      SynchronousFuture<_CachedTileImage>(this);

  @override
  ImageStreamCompleter loadImage(_CachedTileImage key, ImageDecoderCallback decode) =>
      MultiFrameImageStreamCompleter(
        codec: _load(decode),
        scale: 1,
        debugLabel: url,
      );

  Future<ui.Codec> _load(ImageDecoderCallback decode) async {
    final file = await CachedTileProvider._cache.getSingleFile(url, headers: headers);
    final bytes = await file.readAsBytes();
    return decode(await ui.ImmutableBuffer.fromUint8List(bytes));
  }

  @override
  bool operator ==(Object other) => other is _CachedTileImage && other.url == url;

  @override
  int get hashCode => url.hashCode;
}
