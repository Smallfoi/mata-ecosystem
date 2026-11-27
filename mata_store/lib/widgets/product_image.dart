import 'package:flutter/material.dart';
import 'package:cached_network_image/cached_network_image.dart';

import '../data/api/api_config.dart';
import '../models/photo_fit.dart';
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

  /// Разметка снимка: есть — товар ставится целиком в центр рамки с полями
  /// цвета фона (владелец 27.11.2026), иначе — как задано в [fit].
  final PhotoFit? layout;

  const ProductImage({
    super.key,
    required this.path,
    this.fit = BoxFit.cover,
    this.iconSize = 28,
    this.layout,
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
      final lay = layout;
      if (lay != null && _isNetwork && c.hasBoundedWidth && c.hasBoundedHeight &&
          c.maxWidth > 0 && c.maxHeight > 0) {
        return _placed(lay, c.maxWidth, c.maxHeight, dpr);
      }
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

  /// Снимок по разметке: рамка цвета фона, снимок — где сказал [PhotoFit.place].
  Widget _placed(PhotoFit lay, double w, double h, double dpr) {
    final r = lay.place(w, h);
    Widget image = CachedNetworkImage(
      imageUrl: _url,
      fit: BoxFit.fill,
      memCacheWidth: (r.w * dpr).round(),
      placeholder: (_, __) => const SizedBox.shrink(),
      errorWidget: (_, __, ___) => _error(),
    );
    // Фон снимка бывает с лёгким градиентом — край фото внутри рамки виден
    // полосой. Растворяем только видимые края (у края рамки — не трогаем).
    const fade = 0.06;
    final l = r.x > 0.5, t = r.y > 0.5;
    final rr = r.x + r.w < w - 0.5, b = r.y + r.h < h - 0.5;
    Widget mask(Widget child, Alignment from, Alignment to, bool a, bool z) {
      if (!a && !z) return child;
      return ShaderMask(
        blendMode: BlendMode.dstIn,
        shaderCallback: (rect) => LinearGradient(
          begin: from,
          end: to,
          colors: [
            a ? const Color(0x00000000) : const Color(0xFF000000),
            const Color(0xFF000000),
            const Color(0xFF000000),
            z ? const Color(0x00000000) : const Color(0xFF000000),
          ],
          stops: const [0, fade, 1 - fade, 1],
        ).createShader(rect),
        child: child,
      );
    }
    image = mask(image, Alignment.centerLeft, Alignment.centerRight, l, rr);
    image = mask(image, Alignment.topCenter, Alignment.bottomCenter, t, b);
    return ClipRect(
      child: ColoredBox(
        color: Color(lay.bg),
        child: Stack(children: [
          Positioned(left: r.x, top: r.y, width: r.w, height: r.h, child: image),
        ]),
      ),
    );
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
