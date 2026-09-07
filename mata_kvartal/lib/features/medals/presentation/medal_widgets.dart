import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../../../core/theme/app_theme.dart';
import '../data/medal_defs.dart';
import '../data/medals_provider.dart';
import 'emblem_motion.dart';

/// Виджеты штампа: аверс из ассета, реверс с личной гравировкой, 3D-флип.
///
/// Ассеты выгружены из эталона попиксельно (браузерный рендер), поэтому
/// аверс — картинка. Состояния — по эталону: закрытая медаль = тот же файл
/// под обесцвечиванием на 42 % непрозрачности; «новая» — тонкий лаймовый
/// кант три дня (рисуем поверх, чтобы не двоить ассеты).
class MedalImage extends StatelessWidget {
  final MedalDef def;
  final bool earned;
  final bool isNew;
  final double size;

  const MedalImage({
    super.key,
    required this.def,
    required this.earned,
    this.isNew = false,
    required this.size,
  });

  static const _desaturate = ColorFilter.matrix(<double>[
    0.2126, 0.7152, 0.0722, 0, 0,
    0.2126, 0.7152, 0.0722, 0, 0,
    0.2126, 0.7152, 0.0722, 0, 0,
    0, 0, 0, 1, 0,
  ]);

  @override
  Widget build(BuildContext context) {
    Widget img = Image.asset(
      def.asset,
      width: size,
      height: size,
      filterQuality: FilterQuality.medium,
    );
    if (!earned) {
      img = Opacity(
        opacity: 0.42,
        child: ColorFiltered(colorFilter: _desaturate, child: img),
      );
    }
    if (earned && isNew) {
      img = CustomPaint(
        foregroundPainter: _NewRimPainter(),
        child: img,
      );
    }
    return img;
  }
}

/// Тонкий лаймовый кант «новой» медали — шестигранник вершиной вверх,
/// по контуру штампа (R=50 в системе viewBox 116).
class _NewRimPainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    final s = size.width / 116.0;
    final c = Offset(size.width / 2, size.height / 2);
    final path = Path();
    for (int k = 0; k < 6; k++) {
      final a = (-90 + k * 60) * math.pi / 180;
      final p = c + Offset(math.cos(a), math.sin(a)) * 52.6 * s;
      k == 0 ? path.moveTo(p.dx, p.dy) : path.lineTo(p.dx, p.dy);
    }
    path.close();
    canvas.drawPath(
      path,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 2.2 * s
        ..strokeJoin = StrokeJoin.round
        ..color = const Color(0xFFDFF45F)
        ..maskFilter = MaskFilter.blur(BlurStyle.solid, 1.2 * s),
    );
  }

  @override
  bool shouldRepaint(covariant _NewRimPainter oldDelegate) => false;
}

/// Гравировка обязана влезать в поле штампа (правило эталона: НИКАКИХ
/// наложений; реальный случай — «Личное время на 5 км» вылезало за рамку,
/// слово владельца 05.09). Строка шире [maxWidth] — кегль и трекинг
/// ужимаются пропорционально по честному замеру TextPainter.
TextStyle engravingFitToWidth(String text, TextStyle style, double maxWidth) {
  final tp = TextPainter(
    text: TextSpan(text: text, style: style),
    textDirection: TextDirection.ltr,
  )..layout();
  if (tp.width <= maxWidth || tp.width == 0) return style;
  final k = maxWidth / tp.width;
  return style.copyWith(
    fontSize: (style.fontSize ?? 14) * k,
    letterSpacing: (style.letterSpacing ?? 0) * k,
  );
}

/// Реверс: база металла из ассета + личная гравировка (значение · подпись ·
/// дата по нижней дуге) — рисуется здесь, потому что она у каждого своя.
class MedalReverse extends StatelessWidget {
  final MedalDef def;
  final ({String v, String u, String sub})? engraving;
  final double size;

  const MedalReverse({
    super.key,
    required this.def,
    required this.engraving,
    required this.size,
  });

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: size,
      height: size,
      child: Stack(
        fit: StackFit.expand,
        children: [
          Image.asset(def.reverseAsset, filterQuality: FilterQuality.medium),
          if (engraving != null)
            CustomPaint(
              painter: _EngravingPainter(
                tier: def.tier,
                v: engraving!.v,
                u: engraving!.u,
                sub: engraving!.sub,
              ),
            ),
        ],
      ),
    );
  }
}

class _EngravingPainter extends CustomPainter {
  final MedalTier tier;
  final String v, u, sub;

  _EngravingPainter({
    required this.tier,
    required this.v,
    required this.u,
    required this.sub,
  });

  @override
  void paint(Canvas canvas, Size size) {
    final s = size.width / 116.0;
    final c = Offset(size.width / 2, size.height / 2);
    final (hi, mid, lo) = tier.metal;
    final noble = Color.lerp(mid, lo, .35)!;

    // Значение на плашке — металлический градиент, как цифры аверса.
    final vfs = v.length <= 4 ? 16.0 : (v.length <= 7 ? 11.5 : 9.5);
    _baselineText(
      canvas,
      text: v,
      style: TextStyle(
        fontFamily: 'Unbounded',
        fontWeight: FontWeight.w800,
        fontSize: vfs * s,
        letterSpacing: -0.3 * s,
      ),
      gradient: [hi, noble],
      center: c,
      baselineY: 3.6 * s,
      maxWidth: 46 * s,
    );
    _baselineText(
      canvas,
      text: u,
      style: TextStyle(
        fontFamily: AppTheme.fontDisplay,
        fontWeight: FontWeight.w700,
        fontSize: 4.0 * s,
        letterSpacing: 1.1 * s,
      ),
      gradient: [hi.withValues(alpha: .8), noble.withValues(alpha: .8)],
      center: c,
      baselineY: 11.2 * s,
      maxWidth: 52 * s,
    );

    // Дата · город — по нижней дуге R=30, буквы макушкой к центру.
    if (sub.isNotEmpty) {
      final dark = tier == MedalTier.iridium;
      final color = (dark ? hi : const Color(0xFF232C34)).withValues(alpha: .62);
      _arcText(canvas, c, sub, 30.0 * s, 4.2 * s, 1.0 * s, color);
    }
  }

  void _baselineText(
    Canvas canvas, {
    required String text,
    required TextStyle style,
    required List<Color> gradient,
    required Offset center,
    required double baselineY,
    double? maxWidth,
  }) {
    if (text.isEmpty) return;
    if (maxWidth != null) style = engravingFitToWidth(text, style, maxWidth);
    final tp = TextPainter(
      text: TextSpan(text: text, style: style),
      textDirection: TextDirection.ltr,
    )..layout();
    final base = tp.computeDistanceToActualBaseline(TextBaseline.alphabetic);
    final top = center.dy + baselineY - base;
    final rect = Rect.fromLTWH(center.dx - tp.width / 2, top, tp.width, tp.height);
    final paint = Paint()
      ..shader = LinearGradient(
        begin: Alignment.topCenter,
        end: Alignment.bottomCenter,
        colors: gradient,
      ).createShader(rect);
    final tp2 = TextPainter(
      text: TextSpan(text: text, style: style.copyWith(foreground: paint)),
      textDirection: TextDirection.ltr,
    )..layout();
    tp2.paint(canvas, rect.topLeft);
  }

  /// Текст по нижней полуокружности (как textPath эталона): буквы идут слева
  /// направо через низ, базовая линия на дуге.
  void _arcText(
    Canvas canvas,
    Offset center,
    String text,
    double radius,
    double fontSize,
    double letterSpacing,
    Color color,
  ) {
    final style = TextStyle(
      fontFamily: AppTheme.fontDisplay,
      fontWeight: FontWeight.w700,
      fontSize: fontSize,
      color: color,
    );
    final chars = text.split('');
    final widths = <double>[];
    double total = 0;
    for (final ch in chars) {
      final tp = TextPainter(
        text: TextSpan(text: ch, style: style),
        textDirection: TextDirection.ltr,
      )..layout();
      widths.add(tp.width);
      total += tp.width + letterSpacing;
    }
    total -= letterSpacing;
    // Чтение слева направо по нижней дуге — угол φ УБЫВАЕТ (экранные
    // координаты, y вниз: 180° = левый край, 90° = низ, 0° = правый край).
    double phi = math.pi / 2 + (total / 2) / radius;
    int i = 0;
    for (final ch in chars) {
      final w = widths[i++];
      final mid = phi - (w / 2) / radius;
      final pos = center + Offset(math.cos(mid), math.sin(mid)) * radius;
      canvas.save();
      canvas.translate(pos.dx, pos.dy);
      // Базовая линия по касательной, макушка буквы — к центру медали.
      canvas.rotate(math.atan2(-math.cos(mid), math.sin(mid)));
      final tp = TextPainter(
        text: TextSpan(text: ch, style: style),
        textDirection: TextDirection.ltr,
      )..layout();
      final base = tp.computeDistanceToActualBaseline(TextBaseline.alphabetic);
      tp.paint(canvas, Offset(-w / 2, -base));
      canvas.restore();
      phi -= (w + letterSpacing) / radius;
    }
  }

  @override
  bool shouldRepaint(covariant _EngravingPainter old) =>
      old.v != v || old.u != u || old.sub != sub || old.tier != tier;
}

/// 3D-переворот аверс ↔ реверс: чистый, без подскока (правило эталона).
class MedalFlip extends StatefulWidget {
  final MedalFull medal;
  final double size;

  const MedalFlip({super.key, required this.medal, required this.size});

  @override
  State<MedalFlip> createState() => _MedalFlipState();
}

class _MedalFlipState extends State<MedalFlip>
    with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 560),
  );

  void _toggle() {
    if (!widget.medal.earned) return;
    if (_c.isAnimating) return;
    _c.value == 0 ? _c.forward() : _c.reverse();
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: _toggle,
      behavior: HitTestBehavior.opaque,
      child: AnimatedBuilder(
        animation: _c,
        builder: (context, _) {
          final t = Curves.easeInOutCubic.transform(_c.value);
          final angle = t * math.pi;
          final showBack = angle > math.pi / 2;
          return Transform(
            alignment: Alignment.center,
            transform: Matrix4.identity()
              ..setEntry(3, 2, 0.0011)
              ..rotateY(angle),
            child: showBack
                ? Transform(
                    alignment: Alignment.center,
                    transform: Matrix4.identity()..rotateY(math.pi),
                    child: MedalReverse(
                      def: widget.medal.def,
                      engraving: widget.medal.state.engraving,
                      size: widget.size,
                    ),
                  )
                // Аверс живёт своей анимацией (эмблема по эталону D-64);
                // у медалей без спецификации это тот же статичный ассет.
                : LiveMedalImage(medal: widget.medal, size: widget.size),
          );
        },
      ),
    );
  }
}
