import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../core/theme/app_theme.dart';
import '../../shared/widgets/kvartal_logo.dart';
import '../league/data/division_provider.dart';

/// Церемония итогов сезона (Ф5, утверждено 31.08.2026).
///
/// Адаптация утверждённого языка Варианта A под масштаб события: плита-кубок
/// падает ЛИЦОМ вверх со squash-посадкой, один радостный прыжок, двойная
/// вспышка по контуру, звёзды и осколки (без кругов), тексты с перелётом.
/// 5.2 с — сезон больше медали, дыхание длиннее.
Future<void> showSeasonCeremony(
  BuildContext context, {
  required SeasonResultData result,
}) {
  return showGeneralDialog<void>(
    context: context,
    barrierDismissible: false,
    barrierColor: const Color(0xF220252B),
    barrierLabel: 'Сезон',
    transitionDuration: const Duration(milliseconds: 220),
    pageBuilder: (_, __, ___) => _SeasonCeremony(result: result),
    transitionBuilder: (_, anim, __, child) =>
        FadeTransition(opacity: anim, child: child),
  );
}

const _monthNames = [
  '', 'ЯНВ', 'ФЕВ', 'МАР', 'АПР', 'МАЙ', 'ИЮН',
  'ИЮЛ', 'АВГ', 'СЕН', 'ОКТ', 'НОЯ', 'ДЕК',
];

String seasonLabel(String month) {
  final parts = month.split('-');
  if (parts.length != 2) return month;
  final m = int.tryParse(parts[1]) ?? 0;
  final name = (m >= 1 && m <= 12) ? _monthNames[m] : '';
  return 'СЕЗОН · $name ${parts[0]}';
}

class _SeasonCeremony extends StatefulWidget {
  final SeasonResultData result;

  const _SeasonCeremony({required this.result});

  @override
  State<_SeasonCeremony> createState() => _SeasonCeremonyState();
}

class _SeasonCeremonyState extends State<_SeasonCeremony>
    with SingleTickerProviderStateMixin {
  late final AnimationController _c;
  final _haptics = <double>{};

  static const _lime = Color(0xFFDFF45F);
  static const _ink = Color(0xFF171C19);
  static const _light = Color(0xFFEDEFE8);
  static const _dim = Color(0xFF9AA59D);

  @override
  void initState() {
    super.initState();
    _c = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 5200),
    );
    _c.addListener(_onTick);
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      if (MediaQuery.of(context).disableAnimations) {
        _c.value = 1;
      } else {
        _c.forward();
      }
    });
  }

  void _onTick() {
    void once(double at, VoidCallback fn) {
      if (_c.value >= at && !_haptics.contains(at)) {
        _haptics.add(at);
        fn();
      }
    }

    once(.14, HapticFeedback.heavyImpact); // посадка кубка
    once(.34, HapticFeedback.lightImpact); // прыжок
    once(.46, HapticFeedback.mediumImpact); // вспышка 1
    once(.56, HapticFeedback.heavyImpact); // вспышка 2 + звёзды

  }

  @override
  void dispose() {
    _c.removeListener(_onTick);
    _c.dispose();
    super.dispose();
  }

  double _p(double t, double a, double b, [Curve curve = Curves.easeOut]) {
    if (t <= a) return 0;
    if (t >= b) return 1;
    return curve.transform((t - a) / (b - a));
  }

  double _hop(double t, double a, double b) {
    if (t <= a || t >= b) return 0;
    final x = (t - a) / (b - a);
    return 4 * x * (1 - x);
  }

  @override
  Widget build(BuildContext context) {
    final r = widget.result;
    final champion = r.place == 1;
    final title = champion
        ? 'Чемпион сезона'
        : r.place <= 3
            ? 'Подиум сезона'
            : 'Сезон закрыт';

    return Scaffold(
      backgroundColor: Colors.transparent,
      body: GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTap: () {
          if (_c.isAnimating) {
            _c.animateTo(1, duration: const Duration(milliseconds: 240));
          }
        },
        child: AnimatedBuilder(
          animation: _c,
          builder: (context, _) {
            final t = _c.value;
            final drop = _p(t, 0, .14, Curves.easeInQuad);
            final squash = _hop(t, .14, .2);
            final wobble = t < .2 || t > .3
                ? 0.0
                : math.sin((t - .2) / .1 * math.pi * 2.2) *
                      (1 - _p(t, .2, .3, Curves.linear)) *
                      .05;
            final joy = _hop(t, .32, .42);
            final flash1 = _hop(t, .44, .52);
            final flash2 = _hop(t, .54, .64);
            final glow = (flash1 * .8 + flash2).clamp(0.0, 1.0) *
                (1 - _p(t, .8, 1) * .5);
            final burst = _p(t, .54, .8, Curves.easeOut);
            final titleIn = _p(t, .5, .6, Curves.easeOutBack);
            final rowsIn = [
              _p(t, .62, .7, Curves.easeOutBack),
              _p(t, .68, .76, Curves.easeOutBack),
              _p(t, .74, .82, Curves.easeOutBack),
            ];
            final buttonIn = _p(t, .86, .97);

            final dy = -420 * (1 - drop) - joy * 26;
            final sx = 1 + squash * .09;
            final sy = 1 - squash * .09;

            return Stack(
              alignment: Alignment.center,
              fit: StackFit.expand,
              children: [
                if (burst > 0 && burst < 1)
                  Positioned.fill(
                    child: IgnorePointer(
                      child: CustomPaint(
                        painter: _SeasonBurstPainter(progress: burst),
                      ),
                    ),
                  ),
                Column(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    // Кубок-плита: знак + гравировка сезона, лицом вверх.
                    Transform.translate(
                      offset: Offset(0, dy),
                      child: Transform.rotate(
                        angle: wobble,
                        child: Transform(
                          alignment: Alignment.center,
                          transform: Matrix4.identity()..scale(sx, sy),
                          child: Container(
                            width: 150,
                            height: 150,
                            decoration: BoxDecoration(
                              color: _lime,
                              borderRadius: BorderRadius.circular(32),
                              boxShadow: glow > .01
                                  ? [
                                      BoxShadow(
                                        color: _lime.withValues(
                                          alpha: .6 * glow,
                                        ),
                                        blurRadius: 30 * glow,
                                        spreadRadius: 1,
                                      ),
                                    ]
                                  : null,
                            ),
                            child: Column(
                              mainAxisAlignment: MainAxisAlignment.center,
                              children: [
                                CustomPaint(
                                  size: const Size(64, 64),
                                  painter: KvartalMarkPainter(
                                    outline: _ink,
                                    fill: Colors.transparent,
                                    close: 1,
                                  ),
                                ),
                                const SizedBox(height: 8),
                                Text(
                                  seasonLabel(r.month),
                                  style: const TextStyle(
                                    fontFamily: AppTheme.fontDisplay,
                                    fontSize: 10.5,
                                    fontWeight: FontWeight.w800,
                                    letterSpacing: 1.4,
                                    color: _ink,
                                  ),
                                ),
                              ],
                            ),
                          ),
                        ),
                      ),
                    ),
                    const SizedBox(height: 30),
                    Transform.translate(
                      offset: Offset(0, 16 * (1 - titleIn)),
                      child: Opacity(
                        opacity: titleIn.clamp(0, 1),
                        child: Text(
                          title,
                          style: const TextStyle(
                            fontFamily: AppTheme.fontDisplay,
                            fontSize: 27,
                            fontWeight: FontWeight.w800,
                            color: _light,
                          ),
                        ),
                      ),
                    ),
                    const SizedBox(height: 16),
                    for (final (i, line) in [
                      '#${r.place} из ${r.of} за месяц',
                      '${r.km.toStringAsFixed(1)} км · ${r.runs} пробежек',
                      'Уровень и медали остаются с тобой',
                    ].indexed)
                      Transform.translate(
                        offset: Offset(0, 10 * (1 - rowsIn[i])),
                        child: Opacity(
                          opacity: rowsIn[i].clamp(0, 1),
                          child: Padding(
                            padding: const EdgeInsets.only(bottom: 7),
                            child: Text(
                              line,
                              style: TextStyle(
                                fontSize: i == 0 ? 15 : 13,
                                fontWeight:
                                    i == 0 ? FontWeight.w800 : FontWeight.w500,
                                color: i == 0 ? _lime : _dim,
                              ),
                            ),
                          ),
                        ),
                      ),
                    const SizedBox(height: 26),
                    Opacity(
                      opacity: buttonIn.clamp(0, 1),
                      child: FilledButton(
                        style: FilledButton.styleFrom(
                          backgroundColor: _lime,
                          foregroundColor: _ink,
                          minimumSize: const Size(210, 52),
                        ),
                        onPressed: buttonIn > .5
                            ? () => Navigator.of(context).pop()
                            : null,
                        child: const Text('В новый сезон'),
                      ),
                    ),
                  ],
                ),
              ],
            );
          },
        ),
      ),
    );
  }
}

/// Звёзды и осколки сезона — чуть щедрее медальных, но тот же язык форм.
class _SeasonBurstPainter extends CustomPainter {
  final double progress;

  const _SeasonBurstPainter({required this.progress});

  static const _lime = Color(0xFFDFF45F);
  static const _light = Color(0xFFEDEFE8);

  @override
  void paint(Canvas canvas, Size size) {
    final center = Offset(size.width / 2, size.height / 2 - 110);
    for (var i = 0; i < 12; i++) {
      final angle = i * math.pi / 6 + .26;
      final dist = 92 + 132 * Curves.easeOut.transform(progress) + i % 3 * 14;
      final pos = center + Offset(math.cos(angle), math.sin(angle)) * dist;
      final r = (9.5 - i % 3 * 2.0) * (1 - progress * .35);
      final paint = Paint()
        ..color = _lime.withValues(alpha: (.95 * (1 - progress * .7)).clamp(0, 1));
      final path = Path();
      for (var k = 0; k < 8; k++) {
        final rad = k.isEven ? r : r * .38;
        final a = angle + progress * 2.2 + k * math.pi / 4;
        final p = pos + Offset(math.cos(a), math.sin(a)) * rad;
        if (k == 0) {
          path.moveTo(p.dx, p.dy);
        } else {
          path.lineTo(p.dx, p.dy);
        }
      }
      path.close();
      canvas.drawPath(path, paint);
    }
    for (var i = 0; i < 8; i++) {
      final angle = i * math.pi / 4 + 1.1;
      final dist = 76 + 150 * Curves.easeOut.transform(progress) + i % 2 * 20;
      final pos = center + Offset(math.cos(angle), math.sin(angle)) * dist;
      canvas.save();
      canvas.translate(pos.dx, pos.dy);
      canvas.rotate(angle + progress * 3.0);
      canvas.drawRRect(
        RRect.fromRectAndRadius(
          const Rect.fromLTWH(-2.4, -6.5, 4.8, 13),
          const Radius.circular(1.8),
        ),
        Paint()
          ..color = (i.isEven ? _light : _lime)
              .withValues(alpha: (.9 * (1 - progress * .6)).clamp(0, 1)),
      );
      canvas.restore();
    }
  }

  @override
  bool shouldRepaint(_SeasonBurstPainter old) => old.progress != progress;
}
