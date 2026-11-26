import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';

import '../providers/remote_content_provider.dart';
import '../theme/app_theme.dart';
import '../util/console_bridge.dart';
import 'remote_anim.dart';

/// Фото приложения, редактируемое из «Конструктора» (мини-CMS, ключ `app.*`).
///
/// Показывает опубликованное фото по [contentKey] (или [fallbackAsset], пока фото
/// не задано), с учётом фокус-области (`focal.<key>`) и подгона (`fit.<key>`).
/// В web-сборке конструктора (CONSOLE_EDIT=1) — кликабельно: тап открывает ту же
/// модалку фото, что и на сайте (editImage → /site-image). Публикуется под тем же
/// ключом → приложение показывает.
class RemoteImage extends StatelessWidget {
  final String contentKey;
  final String? fallbackAsset;

  /// Сетевое фото по умолчанию (фото товара), пока в Конструкторе ничего не задано.
  /// Приоритетнее [fallbackAsset].
  final String? fallbackUrl;
  final BoxFit fit;
  final double? width;
  final double? height;

  const RemoteImage(
    this.contentKey, {
    this.fallbackAsset,
    this.fallbackUrl,
    this.fit = BoxFit.cover,
    this.width,
    this.height,
    super.key,
  });

  /// "x% y%" → Alignment (50% 50% = центр, 0% 0% = верх-лево).
  Alignment _align(String focal) {
    final m = RegExp(r'^(\d{1,3})% (\d{1,3})%$').firstMatch(focal);
    if (m == null) return Alignment.center;
    final x = int.parse(m.group(1)!).clamp(0, 100);
    final y = int.parse(m.group(2)!).clamp(0, 100);
    return Alignment(x / 50 - 1, y / 50 - 1);
  }

  @override
  Widget build(BuildContext context) {
    final prov = context.watch<RemoteContentProvider>();
    final own = prov.imageUrl(contentKey);
    final url = own.isNotEmpty ? own : (fallbackUrl ?? '');
    final boxFit = prov.fit(contentKey) == 'contain' ? BoxFit.contain : fit;
    final align = _align(prov.focal(contentKey));

    Widget img;
    if (url.isEmpty) {
      img = (fallbackAsset != null)
          ? Image.asset(fallbackAsset!,
              fit: boxFit,
              alignment: align,
              width: width,
              height: height,
              errorBuilder: (_, __, ___) => _ph())
          : _ph();
    } else if (url.startsWith('data:')) {
      // свежая незагруженная картинка из конструктора (dataURL) — на web играет.
      img = Image.network(url,
          fit: boxFit,
          alignment: align,
          width: width,
          height: height,
          errorBuilder: (_, __, ___) => _ph());
    } else {
      img = CachedNetworkImage(
        imageUrl: url,
        fit: boxFit,
        alignment: align,
        width: width,
        height: height,
        placeholder: (_, __) => Container(color: AppColors.grey100),
        errorWidget: (_, __, ___) => _ph(),
      );
    }

    final aspect = (width != null && height != null && height! > 0)
        ? width! / height!
        : 0.0;
    final off = prov.posOffset(contentKey); // смещение перетаскивания (прод + правка)
    final isHidden = prov.hidden(contentKey); // скрыто в конструкторе
    final animName = prov.anim(contentKey); // анимация появления

    void editTap() => postEditImage(
          contentKey,
          url,
          focal: prov.focal(contentKey),
          fit: prov.fit(contentKey) == 'contain' ? 'contain' : 'cover',
          aspect: aspect,
        );

    return ValueListenableBuilder<bool>(
      valueListenable: consoleEditNotifier,
      builder: (context, editing, _) {
        if (!editing) {
          // «Просмотр»/прод: скрытое фото не показываем; иначе — со смещением + анимацией.
          if (isHidden) return const SizedBox.shrink();
          final positioned =
              off == Offset.zero ? img : Transform.translate(offset: off, child: img);
          return animatePreset(animName, positioned);
        }
        return _EditableImage(
          contentKey: contentKey,
          baseOffset: off,
          hidden: isHidden,
          animName: animName,
          onEdit: editTap,
          child: img,
        );
      },
    );
  }

  Widget _ph() => Container(
        width: width,
        height: height,
        color: AppColors.grey100,
        alignment: Alignment.center,
        child: Icon(Icons.image_outlined, color: AppColors.grey400, size: 28),
      );
}

/// Режим правки фото: тап = сменить фото (модалка), ПЕРЕТАСКИВАНИЕ = смещение
/// (`pos.<key>`), долгое нажатие = вернуть на место, бейдж «скрыть/вернуть» — как у текста.
class _EditableImage extends StatefulWidget {
  final String contentKey;
  final Offset baseOffset;
  final bool hidden;
  final String animName;
  final VoidCallback onEdit;
  final Widget child;

  const _EditableImage({
    required this.contentKey,
    required this.baseOffset,
    required this.hidden,
    required this.animName,
    required this.onEdit,
    required this.child,
  });

  @override
  State<_EditableImage> createState() => _EditableImageState();
}

class _EditableImageState extends State<_EditableImage> {
  Offset _drag = Offset.zero;
  bool _dragging = false;

  void _commit(Offset off) {
    final v = '${off.dx.round()},${off.dy.round()}';
    postDraft('pos.${widget.contentKey}', v);
    context.read<RemoteContentProvider>().applyDraft('pos.${widget.contentKey}', v);
  }

  void _openSheet(BuildContext context) => showElementSheet(
        context,
        contentKey: widget.contentKey,
        animName: widget.animName,
        hidden: widget.hidden,
      );

  /// Одна кнопка «⋯» ВНУТРИ границ (надёжно нажимается) → шторка действий.
  Widget _menuButton(BuildContext context, Color bg) => Positioned(
        top: 0,
        right: 0,
        child: GestureDetector(
          behavior: HitTestBehavior.opaque,
          onTap: () => _openSheet(context),
          child: Container(
            width: 24,
            height: 24,
            decoration: BoxDecoration(
              color: bg,
              shape: BoxShape.circle,
              border: Border.all(color: Colors.white, width: 1.5),
            ),
            child: const Icon(Icons.more_horiz, size: 15, color: Colors.white),
          ),
        ),
      );

  @override
  Widget build(BuildContext context) {
    final off = widget.baseOffset + _drag;
    final built = widget.hidden ? _hiddenView(context, off) : _activeView(context, off);
    return animatePreset(widget.animName, built);
  }

  Widget _hiddenView(BuildContext context, Offset off) {
    return Transform.translate(
      offset: off,
      child: GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTap: () => _openSheet(context),
        child: Stack(
          clipBehavior: Clip.none,
          children: [
            Opacity(opacity: 0.35, child: widget.child),
            _menuButton(context, const Color(0xFF16A34A)),
          ],
        ),
      ),
    );
  }

  Widget _activeView(BuildContext context, Offset off) {
    return Transform.translate(
      offset: off,
      child: GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTap: () {
          // Alt+клик = вернуть фото на место (как на сайте); обычный тап = сменить фото.
          if (HardwareKeyboard.instance.isAltPressed) {
            _commit(Offset.zero);
            setState(() => _drag = Offset.zero);
            return;
          }
          widget.onEdit();
        },
        onLongPress: () {
          _commit(Offset.zero);
          setState(() => _drag = Offset.zero);
        },
        onPanStart: (_) => setState(() => _dragging = true),
        onPanUpdate: (d) => setState(() => _drag += d.delta),
        onPanEnd: (_) {
          var f = widget.baseOffset + _drag;
          if (f.dx.abs() < 6 && f.dy.abs() < 6) f = Offset.zero;
          _commit(f);
          setState(() {
            _drag = Offset.zero;
            _dragging = false;
          });
        },
        child: Stack(
          clipBehavior: Clip.none,
          children: [
            DecoratedBox(
              decoration: BoxDecoration(
                border: Border.all(
                  color: _dragging ? const Color(0xFFFF2D9B) : const Color(0xFF0A84FF),
                  width: 2.5,
                ),
                borderRadius: BorderRadius.circular(4),
              ),
              child: widget.child,
            ),
            _menuButton(context, const Color(0xFF0A84FF)),
          ],
        ),
      ),
    );
  }
}
