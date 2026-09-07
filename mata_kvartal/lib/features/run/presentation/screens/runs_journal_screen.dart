import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:latlong2/latlong.dart' show LatLng;

import '../../../../core/theme/app_colors.dart';
import '../../../../core/theme/app_theme.dart';
import '../../data/completed_runs_provider.dart';

/// «Журнал пробежек» (дизайн «Паспорт пробежки», 05.09.2026): вся история
/// по месяцам со сводками; тайл — мини-росчерк маршрута (лаймовый = захват,
/// голубой = свободная), тап открывает паспорт. Закрывает «дверь в никуда»
/// — кнопку «Все» на вкладке «Бег».
class RunsJournalScreen extends ConsumerWidget {
  const RunsJournalScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final runs = ref.watch(completedRunsProvider);
    final groups = <String, List<CompletedRun>>{};
    for (final r in runs) {
      final key = '${r.finishedAt.year}-${r.finishedAt.month}';
      groups.putIfAbsent(key, () => []).add(r);
    }

    return Scaffold(
      backgroundColor: AppColors.bg,
      appBar: AppBar(
        backgroundColor: AppColors.bg,
        title: const Text('Журнал пробежек'),
      ),
      body: SafeArea(
        child: runs.isEmpty
            ? Center(
                child: Text(
                  'Пока пусто — первая пробежка появится здесь',
                  style: TextStyle(color: AppColors.textSecondary),
                ),
              )
            : ListView(
                padding: const EdgeInsets.fromLTRB(16, 4, 16, 24),
                children: [
                  for (final entry in groups.entries) ...[
                    _MonthHeader(runs: entry.value),
                    for (final r in entry.value) ...[
                      RunTileCard(
                        run: r,
                        onTap: () => context.push('/runs/passport', extra: r),
                      ),
                      const SizedBox(height: 8),
                    ],
                    const SizedBox(height: 8),
                  ],
                ],
              ),
      ),
    );
  }
}

class _MonthHeader extends StatelessWidget {
  final List<CompletedRun> runs;
  const _MonthHeader({required this.runs});

  static const _months = [
    'Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
    'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь',
  ];

  @override
  Widget build(BuildContext context) {
    final d = runs.first.finishedAt;
    final km = runs.fold(0.0, (s, r) => s + r.distanceKm);
    final zones = runs.fold(0, (s, r) => s + r.capturedZones);
    final parts = [
      '${runs.length} ${_runsWord(runs.length)}',
      '${km.toStringAsFixed(1)} км',
      if (zones > 0) '+$zones кв.',
    ];
    return Padding(
      padding: const EdgeInsets.fromLTRB(2, 10, 2, 10),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.baseline,
        textBaseline: TextBaseline.alphabetic,
        children: [
          Text(
            '${_months[d.month - 1]} ${d.year}',
            style: TextStyle(
              fontFamily: AppTheme.fontDisplay,
              fontSize: 14.5,
              fontWeight: FontWeight.w700,
              color: AppColors.textPrimary,
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              parts.join(' · '),
              overflow: TextOverflow.ellipsis,
              style: TextStyle(
                fontSize: 11,
                fontWeight: FontWeight.w600,
                color: AppColors.textTertiary,
              ),
            ),
          ),
        ],
      ),
    );
  }

  static String _runsWord(int n) {
    final mod100 = n % 100;
    if (mod100 >= 11 && mod100 <= 14) return 'пробежек';
    return switch (n % 10) {
      1 => 'пробежка',
      2 || 3 || 4 => 'пробежки',
      _ => 'пробежек',
    };
  }
}

/// Тайл пробежки с мини-росчерком — общий для журнала и вкладки «Бег».
class RunTileCard extends StatelessWidget {
  final CompletedRun run;
  final VoidCallback onTap;
  const RunTileCard({super.key, required this.run, required this.onTap});

  @override
  Widget build(BuildContext context) {
    final captured = run.capturedZones > 0;
    final t = run.finishedAt;
    return InkWell(
      borderRadius: BorderRadius.circular(16),
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: AppColors.bgCard,
          borderRadius: BorderRadius.circular(16),
          border: Border.all(color: AppColors.separator),
        ),
        child: Row(
          children: [
            Container(
              width: 52,
              height: 52,
              decoration: BoxDecoration(
                color: const Color(0xFF12161B),
                borderRadius: BorderRadius.circular(12),
                border: Border.all(
                  color: (captured ? AppColors.lime : AppColors.electricBlue)
                      .withValues(alpha: .3),
                ),
              ),
              child: run.route.length >= 2
                  ? CustomPaint(
                      painter: MiniRoutePainter(
                        route: run.route,
                        color: captured
                            ? AppColors.lime
                            : AppColors.electricBlue,
                        filled: captured,
                      ),
                    )
                  : Icon(
                      CupertinoIcons.location_north_fill,
                      size: 18,
                      color: AppColors.textTertiary,
                    ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    '${run.dateLabel.toUpperCase()} · '
                    '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}',
                    style: TextStyle(
                      fontSize: 10,
                      fontWeight: FontWeight.w700,
                      letterSpacing: .5,
                      color: AppColors.textSecondary,
                    ),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    '${run.distanceKm.toStringAsFixed(2)} км',
                    style: TextStyle(
                      fontFamily: AppTheme.fontDisplay,
                      fontSize: 16,
                      fontWeight: FontWeight.w800,
                      color: AppColors.textPrimary,
                    ),
                  ),
                  if (captured) ...[
                    const SizedBox(height: 3),
                    Container(
                      padding: const EdgeInsets.symmetric(
                          horizontal: 7, vertical: 2),
                      decoration: BoxDecoration(
                        color: AppColors.lime,
                        borderRadius: BorderRadius.circular(6),
                      ),
                      child: Text(
                        '+${run.capturedZones} '
                        '${run.capturedZones == 1 ? 'КВАРТАЛ' : 'КВАРТАЛА'}',
                        style: const TextStyle(
                          fontSize: 8.5,
                          fontWeight: FontWeight.w800,
                          color: Color(0xFF171C19),
                        ),
                      ),
                    ),
                  ],
                ],
              ),
            ),
            Column(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                Text(
                  run.elapsedFormatted,
                  style: TextStyle(
                    fontSize: 12.5,
                    fontWeight: FontWeight.w700,
                    color: AppColors.textPrimary,
                  ),
                ),
                const SizedBox(height: 2),
                Text(
                  '${run.paceFormatted} /км',
                  style: TextStyle(
                    fontSize: 10.5,
                    color: AppColors.textTertiary,
                  ),
                ),
              ],
            ),
            const SizedBox(width: 6),
            Icon(
              CupertinoIcons.chevron_right,
              size: 15,
              color: AppColors.textTertiary,
            ),
          ],
        ),
      ),
    );
  }
}

/// Мини-росчерк для тайла: полилиния маршрута, у захвата — лёгкая заливка.
class MiniRoutePainter extends CustomPainter {
  final List<LatLng> route;
  final Color color;
  final bool filled;
  MiniRoutePainter({
    required this.route,
    required this.color,
    required this.filled,
  });

  @override
  void paint(Canvas canvas, Size size) {
    if (route.length < 2) return;
    var minLat = route.first.latitude, maxLat = minLat;
    var minLng = route.first.longitude, maxLng = minLng;
    for (final p in route) {
      minLat = p.latitude < minLat ? p.latitude : minLat;
      maxLat = p.latitude > maxLat ? p.latitude : maxLat;
      minLng = p.longitude < minLng ? p.longitude : minLng;
      maxLng = p.longitude > maxLng ? p.longitude : maxLng;
    }
    final latSpan = (maxLat - minLat).abs().clamp(1e-6, double.infinity);
    final lngSpan = (maxLng - minLng).abs().clamp(1e-6, double.infinity);
    const pad = 9.0;
    final scale = ((size.width - pad * 2) / lngSpan)
        .clamp(0, (size.height - pad * 2) / latSpan)
        .toDouble();
    final w = lngSpan * scale, h = latSpan * scale;
    final ox = (size.width - w) / 2, oy = (size.height - h) / 2;
    final path = Path();
    for (var i = 0; i < route.length; i++) {
      final p = route[i];
      final o = Offset(
        ox + (p.longitude - minLng) * scale,
        oy + (maxLat - p.latitude) * scale,
      );
      i == 0 ? path.moveTo(o.dx, o.dy) : path.lineTo(o.dx, o.dy);
    }
    if (filled) {
      final fillPath = Path.from(path)..close();
      canvas.drawPath(
        fillPath,
        Paint()..color = color.withValues(alpha: .12),
      );
    }
    canvas.drawPath(
      path,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 2.2
        ..strokeJoin = StrokeJoin.round
        ..strokeCap = StrokeCap.round
        ..color = color,
    );
  }

  @override
  bool shouldRepaint(covariant MiniRoutePainter old) =>
      old.route != route || old.color != color || old.filled != filled;
}
