import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:go_router/go_router.dart';

import '../../../../core/theme/app_colors.dart';
import '../../../../core/theme/app_theme.dart';

/// Отдельная вкладка «Инструменты» — офлайн-помощники для бега (перенесены с
/// экрана «Бег» в свой экран). Сетка карточек с «живыми» иконками → роуты /tools/*.
enum _ToolAnim { sweep, beat, slide, swing, spin }

final _tools = <({
  IconData icon,
  String title,
  String sub,
  String route,
  Color color,
  _ToolAnim anim,
})>[
  (
    icon: CupertinoIcons.speedometer,
    title: 'Темп',
    sub: 'скорость и пейс',
    route: '/tools/pace',
    color: AppColors.electricBlue,
    anim: _ToolAnim.sweep,
  ),
  (
    icon: CupertinoIcons.heart_fill,
    title: 'Пульс',
    sub: 'зоны Z1–Z5',
    route: '/tools/hr-zones',
    color: AppColors.error,
    anim: _ToolAnim.beat,
  ),
  (
    icon: Icons.straighten,
    title: 'Размер обуви',
    sub: 'RU / EU / US',
    route: '/tools/shoe-size',
    color: AppColors.info,
    anim: _ToolAnim.slide,
  ),
  (
    icon: Icons.music_note,
    title: 'Метроном',
    sub: 'ритм шагов (каденс)',
    route: '/tools/metronome',
    color: AppColors.warning,
    anim: _ToolAnim.swing,
  ),
  (
    icon: Icons.timer,
    title: 'Интервалы',
    sub: 'таймер тренировки',
    route: '/tools/interval',
    color: AppColors.success,
    anim: _ToolAnim.spin,
  ),
];

class ToolsScreen extends StatelessWidget {
  const ToolsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return DecoratedBox(
      decoration: BoxDecoration(
        color: AppColors.bg,
      ),
      child: SafeArea(
        bottom: false,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(
              padding: EdgeInsets.fromLTRB(20, 14, 20, 2),
              child: Text(
                'Инструменты',
                style: TextStyle(
                  color: AppColors.ink,
                  fontSize: 30,
                  fontWeight: FontWeight.w800,
                ),
              ),
            ),
            Padding(
              padding: EdgeInsets.fromLTRB(20, 0, 20, 10),
              child: Text(
                'Офлайн-помощники для бега',
                style: TextStyle(color: AppColors.textSecondary, fontSize: 13),
              ),
            ),
            Expanded(
              child: GridView.count(
                padding: const EdgeInsets.fromLTRB(16, 6, 16, 24),
                crossAxisCount: 2,
                mainAxisSpacing: 12,
                crossAxisSpacing: 12,
                childAspectRatio: 1.02,
                children: [for (final t in _tools) _ToolCard(entry: t)],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _ToolCard extends StatelessWidget {
  final ({
    IconData icon,
    String title,
    String sub,
    String route,
    Color color,
    _ToolAnim anim,
  }) entry;
  const _ToolCard({required this.entry});

  Widget _animatedIcon() {
    final base = Icon(entry.icon, color: entry.color, size: 26);
    switch (entry.anim) {
      case _ToolAnim.beat:
        return base
            .animate(onPlay: (c) => c.repeat(reverse: true))
            .scaleXY(begin: 1.0, end: 1.18, duration: 600.ms, curve: Curves.easeInOut);
      case _ToolAnim.sweep:
        return base
            .animate(onPlay: (c) => c.repeat(reverse: true))
            .rotate(begin: -0.075, end: 0.075, duration: 900.ms, curve: Curves.easeInOut);
      case _ToolAnim.slide:
        return base
            .animate(onPlay: (c) => c.repeat(reverse: true))
            .moveX(begin: -2.5, end: 2.5, duration: 850.ms, curve: Curves.easeInOut);
      case _ToolAnim.swing:
        return base
            .animate(onPlay: (c) => c.repeat(reverse: true))
            .rotate(begin: -0.045, end: 0.045, duration: 650.ms, curve: Curves.easeInOut);
      case _ToolAnim.spin:
        return base
            .animate(onPlay: (c) => c.repeat())
            .rotate(begin: 0.0, end: 1.0, duration: 4000.ms);
    }
  }

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: () => context.push(entry.route),
      child: Container(
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: AppColors.bgCard,
          borderRadius: BorderRadius.circular(18),
          border: Border.all(color: AppColors.separator),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Container(
              width: 52,
              height: 52,
              alignment: Alignment.center,
              decoration: BoxDecoration(
                color: entry.color.withValues(alpha: 0.14),
                shape: BoxShape.circle,
              ),
              child: _animatedIcon(),
            ),
            Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  entry.title,
                  style: AppTheme.display(15, weight: FontWeight.w600),
                ),
                const SizedBox(height: 3),
                Text(
                  entry.sub,
                  style: TextStyle(fontSize: 12, color: AppColors.textTertiary),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
