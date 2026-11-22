import 'package:flutter/material.dart';

import '../../core/theme/app_colors.dart';
import '../../core/theme/app_theme.dart';

/// Знак Квартала «Последний метр» (вариант А3, утверждён владельцем 2026-08-21,
/// дизайн-проект 37ed0b07; хореография запуска — Вариант 2, 2026-08-22,
/// дизайн-проект 24d1c230): жирный контур-маршрут почти обвёл квартал — внутри
/// лаймовая захваченная территория, «бегун»-точка готова замкнуть петлю.
/// Никаких пунктиров и кругов — ровно как иконка приложения.
///
/// Векторный (CustomPainter) — чёткий в любом размере; цвета параметризованы:
/// [outline] по умолчанию графит (светлые фоны), на тёмных передать светлый.
/// [animated] — цикл «замыкание периметра»: пауза → бегун дорисовывает
/// последний метр → вспышка свечения по контуру знака → петля открывается в
/// новый круг (уважает отключение анимаций в системе).
class KvartalLogoMark extends StatefulWidget {
  final double size;
  final bool animated;
  final bool glow;
  final Color? outline;
  final Color? fill;

  const KvartalLogoMark({
    super.key,
    this.size = 44,
    this.animated = true,
    this.glow = true,
    this.outline,
    this.fill,
  });

  @override
  State<KvartalLogoMark> createState() => _KvartalLogoMarkState();
}

class _KvartalLogoMarkState extends State<KvartalLogoMark>
    with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 3200),
  );

  @override
  void initState() {
    super.initState();
    if (widget.animated) _c.repeat();
  }

  @override
  void didUpdateWidget(covariant KvartalLogoMark old) {
    super.didUpdateWidget(old);
    if (widget.animated && !_c.isAnimating) _c.repeat();
    if (!widget.animated && _c.isAnimating) _c.stop();
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  /// Таймлайн цикла (как в утверждённом сценарии запуска):
  /// пауза → замыкание последнего метра → вспышка → пауза → открытие петли.
  static double _closeAt(double t) {
    if (t < 0.30) return 0;
    if (t < 0.58) {
      return Curves.easeInOutCubic.transform((t - 0.30) / 0.28);
    }
    if (t < 0.90) return 1;
    return 1 - Curves.easeInCubic.transform((t - 0.90) / 0.10);
  }

  /// Вспышка свечения по контуру в момент замыкания (0..1).
  static double _flashAt(double t) {
    if (t < 0.55 || t > 0.84) return 0;
    final x = (t - 0.55) / 0.29;
    return x < 0.28
        ? Curves.easeOut.transform(x / 0.28)
        : 1 - Curves.easeIn.transform((x - 0.28) / 0.72);
  }

  @override
  Widget build(BuildContext context) {
    final reduceMotion = MediaQuery.of(context).disableAnimations;
    final outline = widget.outline ?? AppColors.ink;
    final fill = widget.fill ?? AppColors.lime;
    final live = widget.animated && !reduceMotion;

    return AnimatedBuilder(
      animation: _c,
      builder: (_, __) {
        final t = _c.value;
        final flash = live ? _flashAt(t) : 0.0;

        final mark = CustomPaint(
          size: Size.square(widget.size),
          painter: KvartalMarkPainter(
            outline: outline,
            fill: fill,
            close: live ? _closeAt(t) : 0,
          ),
        );

        if (!widget.glow) return mark;

        // Свечение строго по форме знака (скруглённый квадрат рамки),
        // никаких кругов: базовый ореол + вспышка в момент замыкания.
        final inset = widget.size * (9 / 48);
        return SizedBox(
          width: widget.size,
          height: widget.size,
          child: Stack(
            alignment: Alignment.center,
            children: [
              Positioned.fill(
                child: Padding(
                  padding: EdgeInsets.all(inset),
                  child: DecoratedBox(
                    decoration: BoxDecoration(
                      borderRadius: BorderRadius.circular(inset),
                      boxShadow: [
                        BoxShadow(
                          color: AppColors.lime.withValues(
                            alpha: 0.26 + 0.34 * flash,
                          ),
                          blurRadius: widget.size * (0.26 + 0.18 * flash),
                          spreadRadius: widget.size * 0.02,
                        ),
                      ],
                    ),
                  ),
                ),
              ),
              mark,
            ],
          ),
        );
      },
    );
  }
}

/// Painter знака: [close] 0 — разрыв «последнего метра» (состояние иконки),
/// 1 — петля замкнута; [draw] < 1 — режим заставки, маршрут растёт с нуля;
/// [fillScale] — масштаб лаймовой территории. Без пунктиров — как иконка.
/// [runner] — рисовать ли точку-бегуна. Подложке под прогрессом бегун не нужен:
/// иначе под настоящей точкой проступает вторая, «теневая» (баг 22.11.2026).
class KvartalMarkPainter extends CustomPainter {
  final Color outline;
  final Color fill;
  final double close; // 0 — разрыв полный, 1 — петля замкнута
  final double draw; // 0..1 — сколько маршрута уже нарисовано (сплэш)
  final double fillScale; // 0..1 — масштаб заливки территории (сплэш)
  final bool runner; // точка-бегун на конце линии

  KvartalMarkPainter({
    required this.outline,
    required this.fill,
    this.close = 0,
    this.draw = 1,
    this.fillScale = 1,
    this.runner = true,
  });

  @override
  void paint(Canvas canvas, Size size) {
    final k = size.width / 48;
    canvas.scale(k);

    // Захваченная территория.
    if (fillScale > 0.01) {
      canvas.save();
      canvas.translate(24, 24);
      canvas.scale(fillScale);
      canvas.translate(-24, -24);
      canvas.drawRRect(
        RRect.fromRectAndRadius(
          const Rect.fromLTWH(15.5, 15.5, 17, 17),
          const Radius.circular(4.5),
        ),
        Paint()..color = fill,
      );
      canvas.restore();
    }

    if (draw < 1) {
      _paintDrawing(canvas);
      return;
    }

    // Контур-маршрут с разрывом «последнего метра».
    final ring = Path()
      ..addRRect(RRect.fromRectAndRadius(
        const Rect.fromLTWH(9, 9, 30, 30),
        const Radius.circular(9),
      ));
    final metric = ring.computeMetrics().first;
    final len = metric.length;

    final gapFull = len * 0.14;
    final gap = gapFull * (1 - close);
    final dotT = 5 + gapFull * close; // бегун закрывает петлю
    final solidLen = len - gap;
    final start = dotT - solidLen;

    final stroke = Paint()
      ..color = outline
      ..style = PaintingStyle.stroke
      ..strokeWidth = 4.6
      ..strokeCap = StrokeCap.round;

    if (start < 0) {
      canvas.drawPath(metric.extractPath(start + len, len), stroke);
      canvas.drawPath(metric.extractPath(0, dotT), stroke);
    } else {
      canvas.drawPath(metric.extractPath(start, dotT), stroke);
    }

    // «Бегун» на конце сплошной линии.
    if (!runner) return;
    final pos = metric.getTangentForOffset(dotT % len)!.position;
    canvas.drawCircle(pos, 5, Paint()..color = outline);
    canvas.drawCircle(pos, 2.2, Paint()..color = fill);
  }

  /// Режим заставки: сплошная линия растёт от старта, бегун ведёт линию.
  /// Без пунктирного «плана» — только жирный маршрут и точка (Вариант 2).
  void _paintDrawing(Canvas canvas) {
    final ring = Path()
      ..addRRect(RRect.fromRectAndRadius(
        const Rect.fromLTWH(9, 9, 30, 30),
        const Radius.circular(9),
      ));
    final metric = ring.computeMetrics().first;
    final len = metric.length;
    const t0 = 5.0;
    final solid = len * draw;
    final dotT = t0 + solid;

    // Нарисованный маршрут.
    if (solid > 0.5) {
      final stroke = Paint()
        ..color = outline
        ..style = PaintingStyle.stroke
        ..strokeWidth = 4.6
        ..strokeCap = StrokeCap.round;
      if (dotT <= len) {
        canvas.drawPath(metric.extractPath(t0, dotT), stroke);
      } else {
        canvas.drawPath(metric.extractPath(t0, len), stroke);
        canvas.drawPath(metric.extractPath(0, dotT - len), stroke);
      }
    }

    // Бегун.
    if (!runner) return;
    final pos = metric.getTangentForOffset(dotT % len)!.position;
    canvas.drawCircle(pos, 5, Paint()..color = outline);
    canvas.drawCircle(pos, 2.2, Paint()..color = fill);
  }

  @override
  bool shouldRepaint(KvartalMarkPainter old) =>
      old.outline != outline ||
      old.fill != fill ||
      old.close != close ||
      old.draw != draw ||
      old.fillScale != fillScale ||
      old.runner != runner;
}

class KvartalLogoBadge extends StatelessWidget {
  final double size;
  final bool showText;
  final EdgeInsetsGeometry padding;

  const KvartalLogoBadge({
    super.key,
    this.size = 34,
    this.showText = true,
    this.padding = const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
  });

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        KvartalLogoMark(size: size, glow: false, animated: false),
        if (showText) ...[
          const SizedBox(width: 8),
          Text(
            'КВАРТАЛ',
            style: Theme.of(context).textTheme.labelLarge?.copyWith(
              // Слово живёт на светлой панели — дисплейным шрифтом, как заголовки сайта.
              fontFamily: AppTheme.fontDisplay,
              color: AppColors.ink,
              fontWeight: FontWeight.w700,
              letterSpacing: 0,
            ),
          ),
        ],
      ],
    );
  }
}
