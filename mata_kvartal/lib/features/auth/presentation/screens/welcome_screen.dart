import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../../../../core/theme/app_theme.dart';
import '../../../../shared/widgets/kvartal_logo.dart';

/// Ф3 «Вход в игру» (утверждено 31.08.2026): обещание и механика до логина.
///
/// Четыре мини-экрана: обещание → живая механика захвата → владение и
/// выцветание → баллы реальны. Схема механики — единственное место, где
/// стенография вместо реальной карты (осознанное исключение из правила Ф2).
const kWelcomeSeenKey = 'kvartal.welcome_seen.v1';

class WelcomeScreen extends ConsumerStatefulWidget {
  const WelcomeScreen({super.key});

  @override
  ConsumerState<WelcomeScreen> createState() => _WelcomeScreenState();
}

class _WelcomeScreenState extends ConsumerState<WelcomeScreen>
    with SingleTickerProviderStateMixin {
  final _page = PageController();
  late final AnimationController _loop;
  int _index = 0;

  static const _bg = Color(0xFF20252B);
  static const _dim = Color(0xFF9AA59D);
  static const _lime = Color(0xFFDFF45F);

  @override
  void initState() {
    super.initState();
    _loop = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 3400),
    );
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted && !MediaQuery.of(context).disableAnimations) {
        _loop.repeat();
      }
    });
  }

  @override
  void dispose() {
    _page.dispose();
    _loop.dispose();
    super.dispose();
  }

  Future<void> _finish() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(kWelcomeSeenKey, true);
    if (mounted) context.go('/auth/phone');
  }

  @override
  Widget build(BuildContext context) {
    final pages = [
      _PromisePage(loop: _loop),
      _MechanicPage(loop: _loop),
      _OwnershipPage(loop: _loop),
      const _PointsPage(),
    ];
    final last = _index == pages.length - 1;

    return Scaffold(
      backgroundColor: _bg,
      body: SafeArea(
        child: Column(
          children: [
            Align(
              alignment: Alignment.centerRight,
              child: TextButton(
                onPressed: _finish,
                child: const Text(
                  'Пропустить',
                  style: TextStyle(
                    color: _dim,
                    fontSize: 13.5,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
            ),
            Expanded(
              child: PageView(
                controller: _page,
                onPageChanged: (i) => setState(() => _index = i),
                children: pages,
              ),
            ),
            // Точки прогресса.
            Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                for (var i = 0; i < pages.length; i++)
                  AnimatedContainer(
                    duration: const Duration(milliseconds: 200),
                    width: i == _index ? 22 : 7,
                    height: 7,
                    margin: const EdgeInsets.symmetric(horizontal: 3),
                    decoration: BoxDecoration(
                      color: i == _index ? _lime : const Color(0xFF3A423C),
                      borderRadius: BorderRadius.circular(4),
                    ),
                  ),
              ],
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(24, 20, 24, 16),
              child: SizedBox(
                width: double.infinity,
                child: FilledButton(
                  style: FilledButton.styleFrom(
                    backgroundColor: _lime,
                    foregroundColor: const Color(0xFF171C19),
                    minimumSize: const Size(64, 54),
                  ),
                  onPressed: last
                      ? _finish
                      : () => _page.nextPage(
                          duration: const Duration(milliseconds: 320),
                          curve: AppTheme.ease,
                        ),
                  child: Text(last ? 'Начать' : 'Дальше'),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _PageShell extends StatelessWidget {
  final Widget visual;
  final String title;
  final String text;

  const _PageShell({
    required this.visual,
    required this.title,
    required this.text,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 32),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          SizedBox(height: 190, child: Center(child: visual)),
          const SizedBox(height: 34),
          Text(
            title,
            textAlign: TextAlign.center,
            style: const TextStyle(
              fontFamily: AppTheme.fontDisplay,
              fontSize: 25,
              fontWeight: FontWeight.w800,
              height: 1.15,
              color: Color(0xFFEDEFE8),
            ),
          ),
          const SizedBox(height: 12),
          Text(
            text,
            textAlign: TextAlign.center,
            style: const TextStyle(
              fontSize: 14.5,
              height: 1.55,
              fontWeight: FontWeight.w500,
              color: Color(0xFF9AA59D),
            ),
          ),
        ],
      ),
    );
  }
}

/// 1 · Обещание.
class _PromisePage extends StatelessWidget {
  final AnimationController loop;

  const _PromisePage({required this.loop});

  @override
  Widget build(BuildContext context) {
    return _PageShell(
      visual: AnimatedBuilder(
        animation: loop,
        builder: (_, __) => CustomPaint(
          size: const Size(132, 132),
          painter: KvartalMarkPainter(
            outline: const Color(0xFFEDEFE8),
            fill: const Color(0xFFDFF45F),
            close: 1,
            fillScale: .92 + .08 * (loop.value < .5 ? loop.value * 2 : (1 - loop.value) * 2),
          ),
        ),
      ),
      title: 'Беги и забирай кварталы',
      text: 'Городская игра для бегунов: каждый твой маршрут — '
          'ход на карте города.',
    );
  }
}

/// 2 · Механика: маршрут рисуется, замыкается, квартал заливается. Цикл.
class _MechanicPage extends StatelessWidget {
  final AnimationController loop;

  const _MechanicPage({required this.loop});

  @override
  Widget build(BuildContext context) {
    return _PageShell(
      visual: AnimatedBuilder(
        animation: loop,
        builder: (_, __) {
          final t = loop.value;
          final draw = (t / .55).clamp(0.0, 1.0);
          final close = ((t - .55) / .12).clamp(0.0, 1.0);
          final fill = ((t - .68) / .18).clamp(0.0, 1.0);
          return CustomPaint(
            size: const Size(132, 132),
            painter: KvartalMarkPainter(
              outline: const Color(0xFFEDEFE8),
              fill: const Color(0xFFDFF45F),
              close: close,
              draw: draw,
              fillScale: fill,
            ),
          );
        },
      ),
      title: 'Замкни маршрут — квартал твой',
      text: 'Вернись к точке старта, и контур закроется. '
          'Всё, что внутри, — теперь твоя земля.',
    );
  }
}

/// 3 · Владение: кварталы приносят баллы, без бега — выцветают.
class _OwnershipPage extends StatelessWidget {
  final AnimationController loop;

  const _OwnershipPage({required this.loop});

  @override
  Widget build(BuildContext context) {
    return _PageShell(
      visual: Row(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.center,
        children: [
          Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              CustomPaint(
                size: const Size(84, 84),
                painter: KvartalMarkPainter(
                  outline: const Color(0xFFEDEFE8),
                  fill: const Color(0xFFDFF45F),
                  close: 1,
                ),
              ),
              const SizedBox(height: 10),
              const Text(
                '+баллы каждый день',
                style: TextStyle(
                  fontSize: 11,
                  fontWeight: FontWeight.w700,
                  color: Color(0xFFDFF45F),
                ),
              ),
            ],
          ),
          const SizedBox(width: 36),
          Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              AnimatedBuilder(
                animation: loop,
                builder: (_, __) => Opacity(
                  opacity: .55 - .25 * loop.value,
                  child: CustomPaint(
                    size: const Size(84, 84),
                    painter: KvartalMarkPainter(
                      outline: const Color(0xFF9AA59D),
                      fill: const Color(0xFF3A423C),
                      close: 1,
                    ),
                  ),
                ),
              ),
              const SizedBox(height: 10),
              const Text(
                'без бега — выцветает',
                style: TextStyle(
                  fontSize: 11,
                  fontWeight: FontWeight.w700,
                  color: Color(0xFF9AA59D),
                ),
              ),
            ],
          ),
        ],
      ),
      title: 'Земля живёт, пока ты бегаешь',
      text: 'Свои кварталы приносят баллы. Забросишь бег — '
          'они выцветут, и их заберут другие.',
    );
  }
}

/// 4 · Баллы реальны.
class _PointsPage extends StatelessWidget {
  const _PointsPage();

  @override
  Widget build(BuildContext context) {
    return const _PageShell(
      visual: _PointsVisual(),
      title: 'Баллы — это рубли',
      text: '1 балл = 1 ₽ скидки в МАТА Store. Бег превращается '
          'в кроссовки, форму и экипировку.',
    );
  }
}

class _PointsVisual extends StatelessWidget {
  const _PointsVisual();

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 26, vertical: 20),
      decoration: BoxDecoration(
        color: const Color(0xFF2A302C),
        borderRadius: BorderRadius.circular(24),
        border: Border.all(color: const Color(0xFF3A423C)),
      ),
      child: const Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            '+180',
            style: TextStyle(
              fontFamily: AppTheme.fontDisplay,
              fontSize: 40,
              fontWeight: FontWeight.w800,
              height: 1,
              color: Color(0xFFDFF45F),
            ),
          ),
          SizedBox(height: 6),
          Text(
            'баллов за пробежку',
            style: TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.w600,
              color: Color(0xFF9AA59D),
            ),
          ),
        ],
      ),
    );
  }
}
