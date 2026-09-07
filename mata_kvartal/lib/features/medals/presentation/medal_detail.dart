import 'dart:ui' show ImageFilter;

import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';

import '../../../core/theme/app_colors.dart';
import '../data/medal_defs.dart';
import '../data/medals_provider.dart';
import 'medal_share.dart' show showMedalShareSheet;
import 'medal_widgets.dart';

/// Карточка медали: чеканка при появлении, тап — 3D-оборот с гравировкой.
///
/// Появление — по эталону: медаль «вбивается» (масштаб с лёгким перелётом),
/// затем один проход блика; строки поднимаются следом. Без кругов и пульсов.
Future<void> showMedalDetail(BuildContext context, MedalFull medal) {
  return showGeneralDialog(
    context: context,
    barrierDismissible: true,
    barrierLabel: 'Медаль',
    barrierColor: Colors.black54,
    transitionDuration: const Duration(milliseconds: 220),
    pageBuilder: (_, __, ___) => _MedalDetail(medal: medal),
    transitionBuilder: (_, anim, __, child) => FadeTransition(
      opacity: anim,
      child: BackdropFilter(
        filter: ImageFilter.blur(
          sigmaX: 6 * anim.value,
          sigmaY: 6 * anim.value,
        ),
        child: child,
      ),
    ),
  );
}

class _MedalDetail extends StatefulWidget {
  final MedalFull medal;
  const _MedalDetail({required this.medal});

  @override
  State<_MedalDetail> createState() => _MedalDetailState();
}

class _MedalDetailState extends State<_MedalDetail>
    with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 1400),
  )..forward();

  // Чеканка медали: вбивается с перелётом 7 % и оседает.
  late final Animation<double> _strike = CurvedAnimation(
    parent: _c,
    curve: const Interval(0, .43, curve: Cubic(.3, 1.35, .45, 1)),
  );
  late final Animation<double> _sheen = CurvedAnimation(
    parent: _c,
    curve: const Interval(.4, .85, curve: Curves.easeInOut),
  );

  Animation<double> _row(int i) => CurvedAnimation(
        parent: _c,
        curve: Interval(.3 + i * .08, (.62 + i * .08).clamp(0, 1).toDouble(),
            curve: Curves.easeOutCubic),
      );

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final m = widget.medal;
    final earned = m.earned;
    final date = m.state.earnedAtMs == null
        ? null
        : DateTime.fromMillisecondsSinceEpoch(m.state.earnedAtMs!);

    return Scaffold(
      backgroundColor: Colors.transparent,
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.symmetric(horizontal: 28, vertical: 24),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                AnimatedBuilder(
                  animation: _c,
                  builder: (context, child) {
                    final t = _strike.value;
                    final scale = 0.66 + 0.34 * t;
                    return Opacity(
                      opacity: t.clamp(0, 1),
                      child: Transform.scale(scale: scale, child: child),
                    );
                  },
                  child: _Sheen(
                    progress: _sheen,
                    enabled: earned,
                    child: earned
                        ? MedalFlip(medal: m, size: 248)
                        : MedalImage(
                            def: m.def,
                            earned: false,
                            size: 248,
                          ),
                  ),
                ),
                const SizedBox(height: 18),
                _rise(0, Text(
                  m.def.name,
                  textAlign: TextAlign.center,
                  style: TextStyle(
                    fontFamily: 'Unbounded',
                    fontSize: 19,
                    fontWeight: FontWeight.w700,
                    color: Colors.white,
                  ),
                )),
                const SizedBox(height: 6),
                _rise(1, Text(
                  m.def.rq,
                  textAlign: TextAlign.center,
                  style: TextStyle(
                    fontSize: 13.5,
                    height: 1.4,
                    color: Colors.white70,
                  ),
                )),
                const SizedBox(height: 10),
                _rise(2, Text(
                  '${m.def.tier.title} · ${m.def.cat.title}',
                  style: TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w600,
                    letterSpacing: .4,
                    color: Colors.white38,
                  ),
                )),
                const SizedBox(height: 16),
                if (earned) ...[
                  _rise(3, Text(
                    'Получена ${_fmtDate(date!)}',
                    style: TextStyle(
                      fontSize: 13,
                      fontWeight: FontWeight.w700,
                      color: AppColors.lime,
                    ),
                  )),
                  const SizedBox(height: 8),
                  _rise(4, Text(
                    'Нажми на медаль — на обороте личная гравировка',
                    style: TextStyle(fontSize: 12, color: Colors.white38),
                  )),
                ] else if (m.def.waitNote != null)
                  _rise(3, Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 12),
                    child: Text(
                      m.def.waitNote!,
                      textAlign: TextAlign.center,
                      style: TextStyle(
                        fontSize: 12.5,
                        height: 1.4,
                        color: Colors.white38,
                      ),
                    ),
                  ))
                else if (m.state.progress != null)
                  _rise(3, _Progress(progress: m.state.progress!))
                else
                  _rise(3, Text(
                    'Ещё впереди',
                    style: TextStyle(fontSize: 12.5, color: Colors.white38),
                  )),
                const SizedBox(height: 26),
                if (earned)
                  _rise(5, CupertinoButton(
                    onPressed: () => showMedalShareSheet(context, m),
                    child: Text(
                      'Поделиться',
                      style: TextStyle(
                        color: AppColors.lime,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                  )),
                _rise(earned ? 6 : 5, CupertinoButton(
                  onPressed: () => Navigator.of(context).pop(),
                  child: Text(
                    'Закрыть',
                    style: TextStyle(
                      color: Colors.white70,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                )),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _rise(int i, Widget child) {
    final a = _row(i);
    return AnimatedBuilder(
      animation: a,
      builder: (context, c) => Opacity(
        opacity: a.value,
        child: Transform.translate(
          offset: Offset(0, 12 * (1 - a.value)),
          child: c,
        ),
      ),
      child: child,
    );
  }

  static String _fmtDate(DateTime d) =>
      '${d.day.toString().padLeft(2, '0')}.${d.month.toString().padLeft(2, '0')}.${d.year}';
}

/// Один проход глянцевого блика по силуэту медали (уважает прозрачность PNG).
class _Sheen extends StatelessWidget {
  final Animation<double> progress;
  final bool enabled;
  final Widget child;

  const _Sheen({
    required this.progress,
    required this.enabled,
    required this.child,
  });

  @override
  Widget build(BuildContext context) {
    if (!enabled) return child;
    return AnimatedBuilder(
      animation: progress,
      builder: (context, c) {
        final t = progress.value;
        if (t <= 0 || t >= 1) return c!;
        return ShaderMask(
          blendMode: BlendMode.srcATop,
          shaderCallback: (rect) {
            final dx = rect.width * (t * 2.4 - 1.2);
            return LinearGradient(
              begin: Alignment.topLeft,
              end: Alignment.bottomRight,
              colors: [
                Colors.transparent,
                Colors.white.withValues(alpha: .38),
                Colors.transparent,
              ],
              stops: const [.32, .5, .68],
              transform: _Slide(dx),
            ).createShader(rect);
          },
          child: c,
        );
      },
      child: child,
    );
  }
}

class _Slide extends GradientTransform {
  final double dx;
  const _Slide(this.dx);

  @override
  Matrix4 transform(Rect bounds, {TextDirection? textDirection}) =>
      Matrix4.translationValues(dx, 0, 0);
}

class _Progress extends StatelessWidget {
  final ({double cur, num target}) progress;
  const _Progress({required this.progress});

  @override
  Widget build(BuildContext context) {
    final frac = (progress.cur / progress.target).clamp(0.0, 1.0);
    String f(num v) => v == v.roundToDouble()
        ? v.toStringAsFixed(0)
        : v.toStringAsFixed(1);
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        SizedBox(
          width: 190,
          child: ClipRRect(
            borderRadius: BorderRadius.circular(3),
            child: LinearProgressIndicator(
              value: frac,
              minHeight: 5,
              backgroundColor: Colors.white12,
              valueColor: AlwaysStoppedAnimation(AppColors.lime),
            ),
          ),
        ),
        const SizedBox(height: 6),
        Text(
          '${f(progress.cur.clamp(0, progress.target))} из ${f(progress.target)}',
          style: TextStyle(
            fontSize: 12,
            fontWeight: FontWeight.w600,
            color: Colors.white54,
          ),
        ),
      ],
    );
  }
}
