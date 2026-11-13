import 'dart:ui' show lerpDouble;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/theme/app_theme.dart';
import '../../../shared/widgets/kvartal_logo.dart';
import '../../auth/data/auth_provider.dart';

/// Заставка «Захват» (Вариант 2 дизайн-проекта 24d1c230, утверждён 2026-08-23).
///
/// Единая графитовая сцена с нативным сплэшем (#2A302C — тот же цвет): знак
/// стоит ровно как системная сплэш-иконка, бегун на глазах дорисовывает
/// последний метр, петля замыкается — вспышка по контуру, «КВАРТАЛ».
/// Финал (для авторизованных): титры гаснут, знак улетает в чип шапки карты,
/// и приложение поднимается снизу (слайд шелла в app_router, ?from=splash) —
/// заставка буквально «становится» приложением.
///
/// Цельный запуск без склеек (замечания владельца 2026-08-23, калибровка по
/// записям экрана): OEM-зум плитки лаунчера заканчивается рамкой знака ~90dp
/// ровно в центре экрана; сплэш-иконка (launch_logo) смещена внутри холста
/// так, чтобы встать точно туда же; этот экран повторяет её 1:1 (знак 151.2dp
/// строго в центре) — и продолжает движением бегуна. Анимация стартует только
/// после первого отрисованного кадра. Уважает reduced motion.
class SplashScreen extends ConsumerStatefulWidget {
  const SplashScreen({super.key});

  @override
  ConsumerState<SplashScreen> createState() => _SplashScreenState();
}

class _SplashScreenState extends ConsumerState<SplashScreen>
    with SingleTickerProviderStateMixin {
  static const _bg = Color(0xFF2A302C); // ровно как нативный splash_background
  static const _light = Color(0xFFEFF1EA);
  static const _limeBright = Color(0xFFDFF45F);

  // Куда улетает знак: центр знака в чипе шапки карты (замер по скриншоту,
  // dpr 2.9: физ. (97, 281) → dp). Размер знака в чипе — 24dp.
  static const _chipMarkCenter = Offset(33.5, 97);
  static const _chipMarkSize = 24.0;

  late final AnimationController _c = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 3050),
  );

  // Бегун срывается с места и добегает последний метр — петля замыкается.
  late final Animation<double> _close = CurvedAnimation(
    parent: _c,
    curve: const Interval(0.16, 0.35, curve: Curves.easeInOutCubic),
  );

  // Короткая вспышка свечения по контуру знака в момент захвата
  // (Вариант 2 дизайн-проекта 24d1c230: без пульса и кругов).
  late final Animation<double> _flash = TweenSequence<double>([
    TweenSequenceItem(tween: Tween(begin: 0.0, end: 1.0), weight: 30),
    TweenSequenceItem(tween: Tween(begin: 1.0, end: 0.35), weight: 70),
  ]).animate(CurvedAnimation(
    parent: _c,
    curve: const Interval(0.35, 0.57, curve: Curves.easeOut),
  ));

  late final Animation<double> _title = CurvedAnimation(
    parent: _c,
    curve: const Interval(0.39, 0.54, curve: Curves.easeOutCubic),
  );

  late final Animation<double> _tagline = CurvedAnimation(
    parent: _c,
    curve: const Interval(0.46, 0.61, curve: Curves.easeOutCubic),
  );

  // Финал: титры гаснут, знак улетает в чип шапки (та же кривая, что полёт
  // знака в дизайн-проекте: markfly cubic-bezier(.5,.05,.28,1)).
  late final Animation<double> _titleOut = CurvedAnimation(
    parent: _c,
    curve: const Interval(0.66, 0.74, curve: Curves.easeOut),
  );
  late final Animation<double> _fly = CurvedAnimation(
    parent: _c,
    curve: const Interval(0.70, 0.92, curve: Cubic(0.5, 0.05, 0.28, 1)),
  );

  // Финал играем только авторизованным (знаку есть куда лететь — чип карты).
  bool _withFinale = false;

  @override
  void initState() {
    super.initState();
    // Старт строго после первого показанного кадра: первый видимый кадр
    // Flutter = чистый графит (как системный сплэш), всё идёт на глазах.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      _c.forward();
      // Решение о финале — перед его началом (auth к этому моменту готов).
      Future.delayed(const Duration(milliseconds: 2050), () {
        if (!mounted) return;
        final authed =
            ref.read(authProvider).status == AuthStatus.authenticated;
        if (authed) {
          setState(() => _withFinale = true);
          // Знак долетает к ~2800мс; карта стартует следом и накрывает сцену.
          Future.delayed(const Duration(milliseconds: 790), () {
            if (mounted) context.go('/map?from=splash');
          });
        } else {
          Future.delayed(const Duration(milliseconds: 450), () {
            if (mounted) context.go('/auth/phone');
          });
        }
      });
    });
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final reduceMotion = MediaQuery.of(context).disableAnimations;
    final screen = MediaQuery.of(context).size;
    // 151.2dp: рамка знака 109dp = 316px на эталонном экране (dpr 2.9) —
    // ровно размер системной сплэш-иконки и финала OEM-зума плитки.
    const markSize = 151.2;

    return Scaffold(
      backgroundColor: _bg,
      body: AnimatedBuilder(
        animation: _c,
        builder: (context, _) {
          final close = reduceMotion ? 1.0 : _close.value;
          final title = reduceMotion ? 1.0 : _title.value;
          final tagline = reduceMotion ? 1.0 : _tagline.value;
          final live = _withFinale && !reduceMotion;
          final titleOut = live ? _titleOut.value : 0.0;
          final fly = live ? _fly.value : 0.0;
          final flash =
              reduceMotion ? 0.0 : _flash.value * (1 - titleOut);

          // Полёт знака: центр экрана → центр знака чипа, 151.2dp → 24dp.
          final mSize = lerpDouble(markSize, _chipMarkSize, fly)!;
          final cx = lerpDouble(screen.width / 2, _chipMarkCenter.dx, fly)!;
          final cy = lerpDouble(screen.height / 2, _chipMarkCenter.dy, fly)!;

          return Stack(
            children: [
              // Знак: старт строго в центре экрана — ровно там, где его
              // оставила системная сплэш-иконка (и финал зума плитки).
              Positioned(
                left: cx - mSize / 2,
                top: cy - mSize / 2,
                width: mSize,
                height: mSize,
                child: Stack(
                  alignment: Alignment.center,
                  children: [
                    // Вспышка строго по форме знака (рамка со скруглением),
                    // никаких кругов — Вариант 2 утверждённого дизайна.
                    if (flash > 0.01)
                      Positioned.fill(
                        child: Padding(
                          padding: EdgeInsets.all(mSize * (9 / 48)),
                          child: DecoratedBox(
                            decoration: BoxDecoration(
                              borderRadius: BorderRadius.circular(
                                mSize * (9 / 48),
                              ),
                              boxShadow: [
                                BoxShadow(
                                  color: _limeBright.withValues(
                                    alpha: 0.42 * flash,
                                  ),
                                  blurRadius: mSize * 0.30,
                                  spreadRadius: mSize * 0.02,
                                ),
                              ],
                            ),
                          ),
                        ),
                      ),
                    CustomPaint(
                      size: Size.square(mSize),
                      painter: KvartalMarkPainter(
                        outline: _light,
                        fill: _limeBright,
                        close: close,
                      ),
                    ),
                  ],
                ),
              ),

              // Титры — ниже знака, позиционированы независимо (знак не
              // смещается от их наличия); в финале гаснут.
              Positioned(
                left: 0,
                right: 0,
                top: screen.height / 2 + markSize / 2 + 26,
                child: Opacity(
                  opacity: 1 - titleOut,
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      // «КВАРТАЛ» — собирается из разреженных букв в момент
                      // захвата (трекинг съезжается, как в дизайне).
                      Opacity(
                        opacity: title,
                        child: Transform.translate(
                          offset: Offset(0, 14 * (1 - title)),
                          child: Text(
                            'КВАРТАЛ',
                            style: TextStyle(
                              fontFamily: AppTheme.fontDisplay,
                              fontSize: 34,
                              fontWeight: FontWeight.w700,
                              color: _light,
                              letterSpacing: 2 + 12 * (1 - title),
                            ),
                          ),
                        ),
                      ),
                      const SizedBox(height: 8),
                      Opacity(
                        opacity: tagline,
                        child: Transform.translate(
                          offset: Offset(0, 12 * (1 - tagline)),
                          child: const Text(
                            'Замкни маршрут. Забери квартал.',
                            style: TextStyle(
                              fontSize: 14,
                              color: Color(0xFFB9C1BB),
                              letterSpacing: 0.8,
                            ),
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ],
          );
        },
      ),
    );
  }
}
