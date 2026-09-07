import 'dart:ui' show ImageFilter;

import 'package:flutter/material.dart';

import '../../../core/theme/app_colors.dart';
import '../data/medals_provider.dart';
import 'medal_detail.dart' show showMedalDetail;
import 'medal_share.dart' show showMedalShareSheet;
import 'medal_widgets.dart';

/// Церемония «Штамп МАТА»: медаль вбивается чеканкой, один блик, строки
/// поднимаются следом. Без кругов, ударных волн и пульсов (D-46).
///
/// Показывается после пробежки для каждой новой медали; журнал показов —
/// [MedalCeremonyLedger], чтобы чеканка игралась ровно один раз.
Future<void> showShtampCeremony(BuildContext context, MedalFull medal) async {
  await showGeneralDialog(
    context: context,
    barrierDismissible: false,
    barrierLabel: 'Медаль получена',
    barrierColor: Colors.black87,
    transitionDuration: const Duration(milliseconds: 260),
    pageBuilder: (_, __, ___) => _Ceremony(medal: medal),
    transitionBuilder: (_, anim, __, child) => FadeTransition(
      opacity: anim,
      child: BackdropFilter(
        filter: ImageFilter.blur(
          sigmaX: 8 * anim.value,
          sigmaY: 8 * anim.value,
        ),
        child: child,
      ),
    ),
  );
  await MedalCeremonyLedger.markShown(medal.def.id);
}

class _Ceremony extends StatefulWidget {
  final MedalFull medal;
  const _Ceremony({required this.medal});

  @override
  State<_Ceremony> createState() => _CeremonyState();
}

class _CeremonyState extends State<_Ceremony>
    with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 1600),
  )..forward();

  late final Animation<double> _strike = CurvedAnimation(
    parent: _c,
    curve: const Interval(0, .38, curve: Cubic(.3, 1.35, .45, 1)),
  );
  late final Animation<double> _sheen = CurvedAnimation(
    parent: _c,
    curve: const Interval(.34, .8, curve: Curves.easeInOut),
  );

  Animation<double> _row(int i) => CurvedAnimation(
        parent: _c,
        curve: Interval(
          (.42 + i * .1).clamp(0, 1).toDouble(),
          (.72 + i * .1).clamp(0, 1).toDouble(),
          curve: Curves.easeOutCubic,
        ),
      );

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  Widget _rise(int i, Widget child) {
    final a = _row(i);
    return AnimatedBuilder(
      animation: a,
      builder: (context, c) => Opacity(
        opacity: a.value,
        child: Transform.translate(
          offset: Offset(0, 14 * (1 - a.value)),
          child: c,
        ),
      ),
      child: child,
    );
  }

  @override
  Widget build(BuildContext context) {
    final m = widget.medal;
    return Scaffold(
      backgroundColor: Colors.transparent,
      body: SafeArea(
        child: Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              _rise(0, Text(
                'МЕДАЛЬ ТВОЯ',
                style: TextStyle(
                  fontSize: 12,
                  fontWeight: FontWeight.w700,
                  letterSpacing: 3.2,
                  color: AppColors.lime,
                ),
              )),
              const SizedBox(height: 22),
              AnimatedBuilder(
                animation: _strike,
                builder: (context, child) {
                  final t = _strike.value;
                  return Opacity(
                    opacity: t.clamp(0, 1),
                    // Чеканка: штамп прилетает сверху-из глубины и вбивается.
                    child: Transform.scale(
                      scale: 1.5 - 0.5 * t,
                      child: child,
                    ),
                  );
                },
                child: _CeremonySheen(
                  progress: _sheen,
                  child: MedalImage(def: m.def, earned: true, size: 232),
                ),
              ),
              const SizedBox(height: 24),
              _rise(1, Text(
                m.def.name,
                textAlign: TextAlign.center,
                style: TextStyle(
                  fontFamily: 'Unbounded',
                  fontSize: 21,
                  fontWeight: FontWeight.w700,
                  color: Colors.white,
                ),
              )),
              const SizedBox(height: 8),
              _rise(2, Padding(
                padding: const EdgeInsets.symmetric(horizontal: 40),
                child: Text(
                  m.def.rq,
                  textAlign: TextAlign.center,
                  style: TextStyle(
                    fontSize: 13.5,
                    height: 1.4,
                    color: Colors.white70,
                  ),
                ),
              )),
              const SizedBox(height: 34),
              _rise(3, FilledButton(
                style: FilledButton.styleFrom(
                  backgroundColor: AppColors.lime,
                  foregroundColor: const Color(0xFF171C19),
                  padding: const EdgeInsets.symmetric(
                    horizontal: 30,
                    vertical: 13,
                  ),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(15),
                  ),
                ),
                onPressed: () {
                  Navigator.of(context).pop();
                  showMedalDetail(context, m);
                },
                child: const Text(
                  'Рассмотреть',
                  style: TextStyle(fontSize: 14.5, fontWeight: FontWeight.w800),
                ),
              )),
              const SizedBox(height: 6),
              // Горячий момент шаринга: медаль только что вбилась (правило
              // Стравы — кнопка на пике эмоции, не в меню).
              _rise(4, TextButton(
                onPressed: () => showMedalShareSheet(context, m),
                child: Text(
                  'Поделиться',
                  style: TextStyle(
                    color: AppColors.lime,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              )),
              _rise(5, TextButton(
                onPressed: () => Navigator.of(context).pop(),
                child: Text(
                  'Дальше',
                  style: TextStyle(
                    color: Colors.white54,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              )),
            ],
          ),
        ),
      ),
    );
  }
}

/// Блик церемонии — один проход по силуэту (PNG-альфа уважается).
class _CeremonySheen extends StatelessWidget {
  final Animation<double> progress;
  final Widget child;

  const _CeremonySheen({required this.progress, required this.child});

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: progress,
      builder: (context, c) {
        final t = progress.value;
        if (t <= 0 || t >= 1) return c!;
        return ShaderMask(
          blendMode: BlendMode.srcATop,
          shaderCallback: (rect) => LinearGradient(
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
            colors: [
              Colors.transparent,
              Colors.white.withValues(alpha: .42),
              Colors.transparent,
            ],
            stops: const [.32, .5, .68],
            transform: _SlideX(rect.width * (t * 2.4 - 1.2)),
          ).createShader(rect),
          child: c,
        );
      },
      child: child,
    );
  }
}

class _SlideX extends GradientTransform {
  final double dx;
  const _SlideX(this.dx);

  @override
  Matrix4 transform(Rect bounds, {TextDirection? textDirection}) =>
      Matrix4.translationValues(dx, 0, 0);
}
