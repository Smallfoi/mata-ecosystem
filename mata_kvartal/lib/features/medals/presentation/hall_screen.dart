import 'dart:math' as math;

import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../auth/data/auth_provider.dart';
import '../data/medals_provider.dart';
import 'medal_share.dart' show showHallShareSheet;
import 'medal_widgets.dart';

/// Зал славы (вариант «Пьедестал» без пьедестала — финал по слову владельца 02.09.2026).
///
/// Из профиля бегун попадает СЮДА: его медали, по одной парят в луче света, с личной гравировкой. Свайп листает награды,
/// тап — оборот с гравировкой, полка внизу держит остальные. Полный каталог
/// 44 штампов — за кнопкой «Все медали».
///
/// Зал всегда тёмный, независимо от темы приложения: это пространство со
/// светом прожектора, как экран итогов пробежки. Без кругов и пульсов (D-46).
class TrophyHallScreen extends ConsumerStatefulWidget {
  const TrophyHallScreen({super.key});

  @override
  ConsumerState<TrophyHallScreen> createState() => _TrophyHallScreenState();
}

// Палитра зала — константы, не токены темы (зал не инвертируется).
const _hallInk = Color(0xFFEDEFE8);
const _hallMuted = Color(0xFF97A0A6);
const _hallFaint = Color(0xFF6B7378);
const _hallLime = Color(0xFFDFF45F);

class _TrophyHallScreenState extends ConsumerState<TrophyHallScreen>
    with SingleTickerProviderStateMixin {
  late final PageController _page = PageController();
  late final AnimationController _float = AnimationController(
    vsync: this,
    duration: const Duration(seconds: 5),
  )..repeat();
  int _hero = 0;

  @override
  void dispose() {
    _page.dispose();
    _float.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final medals = ref.watch(medalsProvider);
    final name = ref.watch(authProvider).user?.name ?? 'Бегун КВАРТАЛ';

    return Scaffold(
      backgroundColor: const Color(0xFF0F1216),
      body: Container(
        decoration: const BoxDecoration(
          gradient: LinearGradient(
            begin: Alignment.topCenter,
            end: Alignment.bottomCenter,
            colors: [Color(0xFF20272F), Color(0xFF12161B), Color(0xFF0A0D11)],
            stops: [0, .5, 1],
          ),
        ),
        child: SafeArea(
          child: medals.when(
            loading: () => const Center(
              child: CircularProgressIndicator(color: _hallLime),
            ),
            error: (e, _) => _Offline(
              onRetry: () => ref.invalidate(medalsProvider),
            ),
            data: (list) {
              final earned = [for (final m in list) if (m.earned) m];
              final total = list.length;
              return Column(
                children: [
                  _TopBar(
                    name: name,
                    earned: earned.length,
                    total: total,
                    onShare: earned.isEmpty
                        ? null
                        : () => showHallShareSheet(context, list),
                  ),
                  Expanded(
                    child: earned.isEmpty
                        ? _EmptyHero(float: _float)
                        : _HeroPager(
                            page: _page,
                            float: _float,
                            earned: earned,
                            hero: _hero,
                            onChanged: (i) => setState(() => _hero = i),
                          ),
                  ),
                  if (earned.isNotEmpty)
                    _Shelf(
                      earned: earned,
                      hero: _hero,
                      onPick: (i) => _page.animateToPage(
                        i,
                        duration: const Duration(milliseconds: 420),
                        curve: Curves.easeOutCubic,
                      ),
                    ),
                  _AllMedalsButton(total: total),
                ],
              );
            },
          ),
        ),
      ),
    );
  }
}

class _TopBar extends StatelessWidget {
  final String name;
  final int earned, total;
  final VoidCallback? onShare;
  const _TopBar({
    required this.name,
    required this.earned,
    required this.total,
    this.onShare,
  });

  @override
  Widget build(BuildContext context) {
    return Stack(
      children: [
        Align(
          alignment: Alignment.topLeft,
          child: IconButton(
            onPressed: () => context.pop(),
            icon: const Icon(CupertinoIcons.back, color: _hallInk),
          ),
        ),
        if (onShare != null)
          Align(
            alignment: Alignment.topRight,
            child: IconButton(
              onPressed: onShare,
              tooltip: 'Поделиться залом',
              icon: const Icon(
                CupertinoIcons.square_arrow_up,
                color: _hallInk,
              ),
            ),
          ),
        Padding(
          padding: const EdgeInsets.only(top: 10),
          child: Column(
            children: [
              const Text(
                'ЗАЛ СЛАВЫ',
                style: TextStyle(
                  fontSize: 10.5,
                  fontWeight: FontWeight.w800,
                  letterSpacing: 3,
                  color: _hallLime,
                ),
              ),
              const SizedBox(height: 7),
              // Имя одной строкой при любом системном масштабе шрифта.
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 52),
                child: FittedBox(
                  fit: BoxFit.scaleDown,
                  child: Text(
                    name,
                    maxLines: 1,
                    style: const TextStyle(
                      fontFamily: 'Unbounded',
                      fontSize: 18,
                      fontWeight: FontWeight.w700,
                      color: _hallInk,
                    ),
                  ),
                ),
              ),
              const SizedBox(height: 5),
              Text.rich(
                TextSpan(children: [
                  TextSpan(
                    text: '$earned',
                    style: const TextStyle(
                      fontWeight: FontWeight.w800,
                      color: _hallInk,
                    ),
                  ),
                  TextSpan(text: ' из $total · Штамп МАТА'),
                ]),
                style: const TextStyle(fontSize: 12, color: _hallMuted),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

/// Герой: страницы медалей над пьедесталом, луч и искры — общим фоном.
class _HeroPager extends StatelessWidget {
  final PageController page;
  final AnimationController float;
  final List<MedalFull> earned;
  final int hero;
  final ValueChanged<int> onChanged;

  const _HeroPager({
    required this.page,
    required this.float,
    required this.earned,
    required this.hero,
    required this.onChanged,
  });

  @override
  Widget build(BuildContext context) {
    return Stack(
      children: [
        // Луч прожектора и пылинки в его свете — позади медали.
        Positioned.fill(child: CustomPaint(painter: _BeamPainter())),
        PageView.builder(
          controller: page,
          onPageChanged: onChanged,
          itemCount: earned.length,
          itemBuilder: (context, i) => _HeroPage(
            medal: earned[i],
            float: float,
            active: i == hero,
          ),
        ),
        if (earned.length > 1)
          Positioned(
            left: 0,
            right: 0,
            bottom: 6,
            child: Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                for (var i = 0; i < earned.length; i++)
                  AnimatedContainer(
                    duration: const Duration(milliseconds: 220),
                    width: i == hero ? 16 : 5,
                    height: 5,
                    margin: const EdgeInsets.symmetric(horizontal: 3),
                    decoration: BoxDecoration(
                      color: i == hero
                          ? _hallLime
                          : _hallFaint.withValues(alpha: .5),
                      borderRadius: BorderRadius.circular(3),
                    ),
                  ),
              ],
            ),
          ),
      ],
    );
  }
}

class _HeroPage extends StatelessWidget {
  final MedalFull medal;
  final AnimationController float;
  final bool active;

  const _HeroPage({
    required this.medal,
    required this.float,
    required this.active,
  });

  static String _date(int ms) {
    final d = DateTime.fromMillisecondsSinceEpoch(ms);
    return '${d.day.toString().padLeft(2, '0')}.${d.month.toString().padLeft(2, '0')}.${d.year}';
  }

  @override
  Widget build(BuildContext context) {
    final e = medal.state.engraving;
    return LayoutBuilder(
      builder: (context, box) {
        // Компактные экраны — ужимаем медаль, чтобы зал не скроллился.
        final medalSize = math.min(224.0, box.maxHeight - 170);
        return Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            // Медаль просто парит в луче — без пьедестала и отражения
            // (упрощение по слову владельца, 02.09). Тап — оборот.
            AnimatedBuilder(
              animation: float,
              builder: (context, child) => Transform.translate(
                offset: Offset(
                  0,
                  -4 - 4 * math.sin(float.value * 2 * math.pi),
                ),
                child: child,
              ),
              child: MedalFlip(medal: medal, size: medalSize),
            ),
            const SizedBox(height: 26),
            Text(
              medal.def.name,
              style: const TextStyle(
                fontFamily: 'Unbounded',
                fontSize: 17,
                fontWeight: FontWeight.w700,
                color: _hallInk,
              ),
            ),
            if (e != null && e.v.isNotEmpty) ...[
              const SizedBox(height: 5),
              Text(
                '${e.v} · ${e.u}',
                style: const TextStyle(
                  fontSize: 11.5,
                  fontWeight: FontWeight.w800,
                  letterSpacing: .6,
                  color: _hallLime,
                ),
              ),
            ],
            if (medal.state.earnedAtMs != null) ...[
              const SizedBox(height: 4),
              Text(
                'ПОЛУЧЕНА ${_date(medal.state.earnedAtMs!)}',
                style: const TextStyle(
                  fontSize: 10.5,
                  letterSpacing: 1.4,
                  fontWeight: FontWeight.w600,
                  color: _hallMuted,
                ),
              ),
            ],
            const SizedBox(height: 18),
          ],
        );
      },
    );
  }
}

/// Пустой зал: луч и пунктирный контур ждут первую медаль.
class _EmptyHero extends StatelessWidget {
  final AnimationController float;
  const _EmptyHero({required this.float});

  @override
  Widget build(BuildContext context) {
    return Stack(
      children: [
        Positioned.fill(child: CustomPaint(painter: _BeamPainter())),
        Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            AnimatedBuilder(
              animation: float,
              builder: (context, child) => Transform.translate(
                offset: Offset(0, -4 * math.sin(float.value * 2 * math.pi)),
                child: child,
              ),
              child: const CustomPaint(
                size: Size(150, 168),
                painter: _DashedHexPainter(),
              ),
            ),
            const SizedBox(height: 26),
            const Text(
              'Зал ждёт первую медаль',
              style: TextStyle(
                fontFamily: 'Unbounded',
                fontSize: 15,
                fontWeight: FontWeight.w700,
                color: _hallInk,
              ),
            ),
            const SizedBox(height: 6),
            const Text(
              'Один круг у дома — и здесь встанет «Первый бег»',
              style: TextStyle(fontSize: 12.5, color: _hallMuted),
            ),
          ],
        ),
      ],
    );
  }
}

/// Полка: остальные награды на мини-постаментах + пустые слоты «скоро».
class _Shelf extends StatelessWidget {
  final List<MedalFull> earned;
  final int hero;
  final ValueChanged<int> onPick;

  const _Shelf({required this.earned, required this.hero, required this.onPick});

  @override
  Widget build(BuildContext context) {
    final others = <(int, MedalFull)>[
      for (var i = 0; i < earned.length; i++)
        if (i != hero) (i, earned[i]),
    ];
    final shown = others.take(4).toList();
    final emptySlots = (3 - shown.length).clamp(0, 3);

    return Padding(
      padding: const EdgeInsets.only(top: 4, bottom: 10),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.center,
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          for (final (i, m) in shown) ...[
            _ShelfSlot(medal: m, onTap: () => onPick(i)),
            const SizedBox(width: 24),
          ],
          for (var k = 0; k < emptySlots; k++) ...[
            const _ShelfSlot(medal: null),
            if (k != emptySlots - 1) const SizedBox(width: 24),
          ],
        ],
      ),
    );
  }
}

class _ShelfSlot extends StatelessWidget {
  final MedalFull? medal;
  final VoidCallback? onTap;
  const _ShelfSlot({required this.medal, this.onTap});

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      behavior: HitTestBehavior.opaque,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (medal != null)
            MedalImage(def: medal!.def, earned: true, size: 72)
          else
            const Padding(
              padding: EdgeInsets.symmetric(vertical: 3),
              child: CustomPaint(
                size: Size(58, 66),
                painter: _DashedHexPainter(),
              ),
            ),
          // Тень-подставка мини-постамента.
          Container(
            width: 62,
            height: 8,
            decoration: const BoxDecoration(
              gradient: RadialGradient(
                center: Alignment.topCenter,
                radius: 1,
                colors: [Color(0xFF2A323B), Color(0x002A323B)],
              ),
            ),
          ),
          const SizedBox(height: 5),
          Text(
            medal?.def.name ?? 'скоро',
            style: TextStyle(
              fontSize: 10,
              fontWeight: FontWeight.w600,
              color: medal != null ? _hallMuted : _hallFaint,
            ),
          ),
        ],
      ),
    );
  }
}

class _AllMedalsButton extends StatelessWidget {
  final int total;
  const _AllMedalsButton({required this.total});

  static String _plural(int n) {
    final m100 = n % 100;
    if (m100 >= 11 && m100 <= 14) return 'наград';
    return switch (n % 10) {
      1 => 'награда',
      2 || 3 || 4 => 'награды',
      _ => 'наград',
    };
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(20, 6, 20, 16),
      child: GestureDetector(
        onTap: () => context.push('/profile/trophies/all'),
        behavior: HitTestBehavior.opaque,
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
          decoration: BoxDecoration(
            color: const Color(0xD91B2129),
            borderRadius: BorderRadius.circular(18),
            border: Border.all(color: _hallLime.withValues(alpha: .5), width: 1.2),
          ),
          child: Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
                      'Все медали',
                      style: TextStyle(
                        fontSize: 14.5,
                        fontWeight: FontWeight.w800,
                        color: _hallInk,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      '$total ${_plural(total)} · прогресс по каждой',
                      style: const TextStyle(fontSize: 11.5, color: _hallMuted),
                    ),
                  ],
                ),
              ),
              const Text(
                '→',
                style: TextStyle(
                  fontFamily: 'Unbounded',
                  fontSize: 17,
                  color: _hallLime,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _Offline extends StatelessWidget {
  final VoidCallback onRetry;
  const _Offline({required this.onRetry});

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Text(
            'Зал не открылся — нет связи',
            style: TextStyle(fontSize: 13.5, color: _hallMuted),
          ),
          const SizedBox(height: 10),
          OutlinedButton(
            onPressed: onRetry,
            style: OutlinedButton.styleFrom(
              foregroundColor: _hallInk,
              side: const BorderSide(color: _hallFaint),
            ),
            child: const Text('Повторить'),
          ),
        ],
      ),
    );
  }
}

// ── художники зала ───────────────────────────────────────────────────────────

/// Луч прожектора: трапеция света сверху к медали + редкие пылинки.
class _BeamPainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    final cx = size.width / 2;
    final beam = Path()
      ..moveTo(cx - 42, -20)
      ..lineTo(cx + 42, -20)
      ..lineTo(cx + 148, size.height * .68)
      ..lineTo(cx - 148, size.height * .68)
      ..close();
    canvas.drawPath(
      beam,
      Paint()
        ..shader = LinearGradient(
          begin: Alignment.topCenter,
          end: Alignment.bottomCenter,
          colors: [
            const Color(0xFFEDEFE8).withValues(alpha: .10),
            const Color(0x00EDEFE8),
          ],
          stops: const [0, .82],
        ).createShader(Offset.zero & size)
        ..maskFilter = const MaskFilter.blur(BlurStyle.normal, 7),
    );
    // Пылинки в свете — статичные, детерминированные (никаких пульсов).
    final dot = Paint()..color = const Color(0xFFEDEFE8).withValues(alpha: .07);
    const pts = [
      (.36, .18, 1.1), (.62, .12, .8), (.45, .3, .9), (.57, .38, 1.2),
      (.34, .46, .8), (.66, .5, 1.0), (.5, .08, .7), (.42, .58, .9),
    ];
    for (final (fx, fy, r) in pts) {
      canvas.drawCircle(Offset(size.width * fx, size.height * fy), r, dot);
    }
  }

  @override
  bool shouldRepaint(covariant _BeamPainter oldDelegate) => false;
}

/// Пунктирный шестигранник — место, которое ждёт медаль.
class _DashedHexPainter extends CustomPainter {
  const _DashedHexPainter();

  @override
  void paint(Canvas canvas, Size size) {
    final w = size.width, h = size.height;
    final pts = [
      Offset(w / 2, 0),
      Offset(w, h * .25),
      Offset(w, h * .75),
      Offset(w / 2, h),
      Offset(0, h * .75),
      Offset(0, h * .25),
    ];
    final paint = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.5
      ..color = _hallFaint.withValues(alpha: .55);
    for (var i = 0; i < 6; i++) {
      final a = pts[i], b = pts[(i + 1) % 6];
      final len = (b - a).distance;
      const dash = 6.0, gap = 5.0;
      var t = 0.0;
      while (t < len) {
        final t2 = math.min(t + dash, len);
        canvas.drawLine(
          Offset.lerp(a, b, t / len)!,
          Offset.lerp(a, b, t2 / len)!,
          paint,
        );
        t = t2 + gap;
      }
    }
  }

  @override
  bool shouldRepaint(covariant _DashedHexPainter oldDelegate) => false;
}
