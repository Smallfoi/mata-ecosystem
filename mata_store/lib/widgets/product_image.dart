import 'package:flutter/material.dart';
import 'package:cached_network_image/cached_network_image.dart';

import '../data/api/api_config.dart';
import '../theme/app_theme.dart';

/// Универсальный загрузчик фото товара.
///
/// Путь с `http` или `/media/...` — грузит из сети через [CachedNetworkImage]
/// (так приходят загруженные в админке фото: на проде это адрес хранилища, в
/// разработке — относительный путь бэкенда). Иначе берёт локальный asset
/// (используется в прототипе, работает офлайн на любой сети).
class ProductImage extends StatelessWidget {
  final String path;
  final BoxFit fit;
  final double iconSize;

  const ProductImage({
    super.key,
    required this.path,
    this.fit = BoxFit.cover,
    this.iconSize = 28,
  });

  // `/media/...` — сетевой путь бэкенда, а не ассет приложения: так приходят
  // загруженные в админке фото, когда медиа отдаёт сам сервер (dev), а не S3.
  bool get _isNetwork => path.startsWith('http') || path.startsWith('/media');

  String get _url =>
      path.startsWith('http') ? path : ApiConfig.resolveMedia(path);

  @override
  Widget build(BuildContext context) {
    // Распаковываем фото под реальный размер плитки, а не исходные 900+ px:
    // каждая плитка каталога занимала несколько МБ памяти, кэш картинок
    // переполнялся и при прокрутке назад фото распаковывались заново — рывки
    // (аудит 21.11.2026). Ширина неизвестна (бесконечна) — как раньше, целиком.
    return LayoutBuilder(builder: (context, c) {
      final dpr = MediaQuery.devicePixelRatioOf(context);
      final px = c.maxWidth.isFinite && c.maxWidth > 0
          ? (c.maxWidth * dpr).round()
          : null;
      if (_isNetwork) {
        return CachedNetworkImage(
          imageUrl: _url,
          fit: fit,
          memCacheWidth: px,
          placeholder: (_, __) => Container(color: AppColors.grey100),
          errorWidget: (_, __, ___) => _error(),
        );
      }
      return Image.asset(
        path,
        fit: fit,
        cacheWidth: px,
        errorBuilder: (_, __, ___) => _error(),
      );
    });
  }

  Widget _error() => Container(
        color: AppColors.grey100,
        alignment: Alignment.center,
        child: Icon(
          Icons.image_outlined,
          color: AppColors.grey400,
          size: iconSize,
        ),
      );
}
