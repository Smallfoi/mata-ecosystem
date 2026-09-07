import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../../core/theme/app_colors.dart';
import '../../data/me_stats_provider.dart';

/// Личная статистика (/v1/me/stats): бег + баллы + заказы — единая витрина
/// экосистемы (данные из общего бэка, одинаковы во всех приложениях).
class StatsScreen extends ConsumerWidget {
  const StatsScreen({super.key});

  static String _km(double v) =>
      v == v.roundToDouble() ? v.toStringAsFixed(0) : v.toStringAsFixed(1);

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final stats = ref.watch(meStatsProvider);
    return Scaffold(
      backgroundColor: AppColors.bgDark,
      appBar: AppBar(
        backgroundColor: AppColors.bgDark,
        title: const Text('Моя статистика'),
      ),
      body: stats.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (_, __) => Center(
          child: Padding(
            padding: EdgeInsets.all(24),
            child: Text(
              'Не удалось загрузить статистику.\nПроверьте подключение и попробуйте позже.',
              textAlign: TextAlign.center,
              style: TextStyle(color: AppColors.muted),
            ),
          ),
        ),
        data: (s) => ListView(
          padding: const EdgeInsets.all(16),
          children: [
            const _SectionTitle('Бег'),
            _StatRow([
              _Stat('Забегов', '${s.runsCount}', Icons.directions_run),
              _Stat('Дистанция', '${_km(s.totalKm)} км', Icons.route_outlined),
            ]),
            const SizedBox(height: 20),
            const _SectionTitle('Баллы'),
            _StatRow([
              _Stat('Баланс', '${s.balance}', Icons.star_border),
              _Stat('Заработано', '${s.earned}', Icons.trending_up),
              _Stat('Потрачено', '${s.spent}', Icons.trending_down),
            ]),
            const SizedBox(height: 20),
            const _SectionTitle('Заказы'),
            _StatRow([
              _Stat('Заказов', '${s.ordersCount}', Icons.shopping_bag_outlined),
              _Stat('На сумму', '${s.totalSpent} ₽', Icons.payments_outlined),
            ]),
            const SizedBox(height: 22),
            Text(
              'Статистика едина во всех приложениях экосистемы: покупки и заказы '
              'учитываются из МАТА Store.',
              style: TextStyle(fontSize: 13, height: 1.4, color: AppColors.muted),
            ),
          ],
        ),
      ),
    );
  }
}

class _SectionTitle extends StatelessWidget {
  final String text;
  const _SectionTitle(this.text);

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: 10),
        child: Text(
          text,
          style: TextStyle(
            fontSize: 16,
            fontWeight: FontWeight.w800,
            color: AppColors.ink,
          ),
        ),
      );
}

class _Stat {
  final String label;
  final String value;
  final IconData icon;
  const _Stat(this.label, this.value, this.icon);
}

class _StatRow extends StatelessWidget {
  final List<_Stat> stats;
  const _StatRow(this.stats);

  @override
  Widget build(BuildContext context) {
    // IntrinsicHeight — иначе stretch в Row внутри ListView получает
    // неограниченную высоту и секции ниже первой рендерятся пустыми.
    final children = <Widget>[];
    for (var i = 0; i < stats.length; i++) {
      if (i > 0) children.add(const SizedBox(width: 10));
      children.add(Expanded(child: _StatCard(stats[i])));
    }
    return IntrinsicHeight(
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: children,
      ),
    );
  }
}

class _StatCard extends StatelessWidget {
  final _Stat stat;
  const _StatCard(this.stat);

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(vertical: 16, horizontal: 12),
        decoration: BoxDecoration(
          color: AppColors.bgCard,
          borderRadius: BorderRadius.circular(14),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(stat.icon, size: 22, color: AppColors.electricBlue),
            const SizedBox(height: 10),
            Text(
              stat.value,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(
                fontSize: 20,
                fontWeight: FontWeight.w800,
                color: AppColors.ink,
              ),
            ),
            const SizedBox(height: 2),
            Text(
              stat.label,
              style: TextStyle(fontSize: 12, color: AppColors.muted),
            ),
          ],
        ),
      );
}
