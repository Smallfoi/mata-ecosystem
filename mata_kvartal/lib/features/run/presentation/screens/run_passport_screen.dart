import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:latlong2/latlong.dart' show Distance, LengthUnit;

import '../../../../core/theme/app_colors.dart';
import '../../../../core/theme/app_theme.dart';
import '../../../medals/data/medals_provider.dart';
import '../../../medals/presentation/medal_detail.dart';
import '../../../medals/presentation/medal_widgets.dart';
import '../../data/completed_runs_provider.dart';
import '../widgets/run_share.dart';
import 'run_result_screen.dart' show RoutePainter;

/// «Паспорт пробежки» (дизайн утверждён 05.09.2026): маршрут-герой, вся
/// аналитика, награды и баллы пробежки, шаринг в любой момент. Пустые блоки
/// не рисуются — показываем только настоящие данные (правило дизайна).
class RunPassportScreen extends ConsumerWidget {
  final CompletedRun run;
  const RunPassportScreen({super.key, required this.run});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final captured = run.capturedZones > 0;
    final started = run.finishedAt.subtract(run.elapsed);
    final medals = ref.watch(medalsProvider).valueOrNull ?? const <MedalFull>[];
    // Награды этой пробежки: выдачи в окно [старт−1 мин, финиш+10 мин] —
    // сервер судит медали при синке сразу после финиша.
    final awards = [
      for (final m in medals)
        if (m.state.earnedAtMs != null &&
            m.state.earnedAtMs! >=
                started.subtract(const Duration(minutes: 1)).millisecondsSinceEpoch &&
            m.state.earnedAtMs! <=
                run.finishedAt.add(const Duration(minutes: 10)).millisecondsSinceEpoch)
          m,
    ];
    final splits = computeKmSplits(run);
    final points = ref.watch(lastRunPointsProvider);
    final runPoints = points != null && points.runId == run.id ? points.points : null;

    return Scaffold(
      backgroundColor: AppColors.bg,
      appBar: AppBar(
        backgroundColor: AppColors.bg,
        title: Text('Пробежка · ${run.dateLabel.toLowerCase()}'),
        actions: [
          IconButton(
            tooltip: 'Поделиться',
            onPressed: () => _share(context),
            icon: Icon(CupertinoIcons.square_arrow_up, color: AppColors.lime),
          ),
        ],
      ),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(16, 6, 16, 24),
          children: [
            _TrackHero(run: run, captured: captured, started: started),
            const SizedBox(height: 12),
            _KmRow(run: run),
            const SizedBox(height: 12),
            Row(
              children: [
                _chip(context, run.elapsedFormatted, 'ВРЕМЯ'),
                const SizedBox(width: 8),
                _chip(context, run.paceFormatted, 'ТЕМП /КМ'),
                if (captured) ...[
                  const SizedBox(width: 8),
                  _chip(context, '+${run.capturedZones}',
                      run.capturedZones == 1 ? 'КВАРТАЛ' : 'КВАРТАЛА',
                      lime: true),
                ],
              ],
            ),
            const SizedBox(height: 12),
            FilledButton.icon(
              style: FilledButton.styleFrom(
                backgroundColor: AppColors.lime,
                foregroundColor: const Color(0xFF171C19),
                minimumSize: const Size(64, 52),
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(14),
                ),
              ),
              onPressed: () => _share(context),
              icon: const Icon(CupertinoIcons.square_arrow_up, size: 18),
              label: const Text(
                'Поделиться пробежкой',
                style: TextStyle(fontWeight: FontWeight.w800),
              ),
            ),
            const SizedBox(height: 8),
            OutlinedButton(
              style: OutlinedButton.styleFrom(
                foregroundColor: AppColors.textPrimary,
                side: BorderSide(color: AppColors.separator),
                minimumSize: const Size(64, 46),
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(14),
                ),
              ),
              onPressed: () => context.go('/map'),
              child: const Text('Показать на карте'),
            ),
            if (splits.length >= 2) ...[
              const SizedBox(height: 14),
              _SplitsBlock(splits: splits),
            ],
            if (awards.isNotEmpty) ...[
              const SizedBox(height: 14),
              _AwardsBlock(awards: awards),
            ],
            if (runPoints != null && runPoints > 0) ...[
              const SizedBox(height: 14),
              _PointsBlock(points: runPoints, captured: captured),
            ],
          ],
        ),
      ),
    );
  }

  void _share(BuildContext context) {
    showRunShareSheet(
      context,
      RunShareData(
        route: run.route,
        elapsed: run.elapsed,
        distanceMeters: run.distanceMeters,
        capturedZones: run.capturedZones,
        finishedAt: run.finishedAt,
        runId: run.id,
      ),
    );
  }

  Widget _chip(BuildContext context, String v, String l, {bool lime = false}) =>
      Expanded(
        child: Container(
          padding: const EdgeInsets.symmetric(vertical: 10, horizontal: 6),
          decoration: BoxDecoration(
            color: AppColors.bgCard,
            borderRadius: BorderRadius.circular(13),
            border: Border.all(
              color: lime
                  ? AppColors.lime.withValues(alpha: .5)
                  : AppColors.separator,
            ),
          ),
          child: Column(
            children: [
              Text(
                v,
                style: TextStyle(
                  fontFamily: AppTheme.fontDisplay,
                  fontSize: 15,
                  fontWeight: FontWeight.w800,
                  letterSpacing: -.3,
                  color: lime ? AppColors.lime : AppColors.textPrimary,
                ),
              ),
              const SizedBox(height: 2),
              Text(
                l,
                style: TextStyle(
                  fontSize: 8.5,
                  letterSpacing: 1.3,
                  fontWeight: FontWeight.w700,
                  color: AppColors.textSecondary,
                ),
              ),
            ],
          ),
        ),
      );
}

/// Честные сплиты: секунды на каждый километр из времени точек маршрута
/// (тропы D-60 пишут его у всех новых пробежек). Нет времени — нет сплитов.
List<int> computeKmSplits(CompletedRun run) {
  if (run.route.length < 2 ||
      run.routeTimes.length != run.route.length ||
      run.distanceKm < 1) {
    return const [];
  }
  const distCalc = Distance();
  final splits = <int>[];
  var acc = 0.0;
  var kmStartMs = run.routeTimes.first;
  for (var i = 1; i < run.route.length; i++) {
    acc += distCalc.as(LengthUnit.Meter, run.route[i - 1], run.route[i]);
    if (acc >= 1000) {
      splits.add(((run.routeTimes[i] - kmStartMs) / 1000).round());
      kmStartMs = run.routeTimes[i];
      acc -= 1000;
    }
  }
  return splits.where((s) => s > 0).toList();
}

class _TrackHero extends StatelessWidget {
  final CompletedRun run;
  final bool captured;
  final DateTime started;
  const _TrackHero({
    required this.run,
    required this.captured,
    required this.started,
  });

  @override
  Widget build(BuildContext context) {
    String hm(DateTime d) =>
        '${d.hour.toString().padLeft(2, '0')}:${d.minute.toString().padLeft(2, '0')}';
    return Container(
      height: 250,
      clipBehavior: Clip.antiAlias,
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: AppColors.separator),
        gradient: const RadialGradient(
          center: Alignment(0, -.9),
          radius: 1.4,
          colors: [Color(0xFF1D242C), Color(0xFF12161B)],
        ),
      ),
      child: Stack(
        children: [
          if (run.route.length >= 2)
            Positioned.fill(
              child: Padding(
                padding: const EdgeInsets.fromLTRB(8, 6, 8, 6),
                child: CustomPaint(
                  painter: RoutePainter(
                    route: run.route,
                    progress: 1,
                    fill: captured ? 1 : 0,
                    fitFactor: 1,
                    topInset: 6,
                  ),
                  child: const SizedBox.expand(),
                ),
              ),
            )
          else
            Center(
              child: Padding(
                padding: const EdgeInsets.all(24),
                child: Text(
                  'Маршрут остался на телефоне, где записана пробежка, — '
                  'сервер сырой GPS не хранит',
                  textAlign: TextAlign.center,
                  style: TextStyle(
                    fontSize: 12.5,
                    color: AppColors.textTertiary,
                  ),
                ),
              ),
            ),
          Positioned(
            top: 10,
            left: 10,
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 4),
              decoration: BoxDecoration(
                color: captured ? AppColors.lime : AppColors.bgElevated,
                borderRadius: BorderRadius.circular(7),
              ),
              child: Text(
                captured ? 'ЗАХВАТ' : 'СВОБОДНАЯ',
                style: TextStyle(
                  fontSize: 9,
                  fontWeight: FontWeight.w800,
                  letterSpacing: 1,
                  color: captured
                      ? const Color(0xFF171C19)
                      : AppColors.textSecondary,
                ),
              ),
            ),
          ),
          Positioned(
            top: 10,
            right: 10,
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 4),
              decoration: BoxDecoration(
                color: AppColors.bg.withValues(alpha: .7),
                borderRadius: BorderRadius.circular(7),
                border: Border.all(color: AppColors.separator),
              ),
              child: Text(
                '${hm(started)} – ${hm(run.finishedAt)}',
                style: TextStyle(
                  fontSize: 9.5,
                  fontWeight: FontWeight.w700,
                  color: AppColors.textSecondary,
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _KmRow extends StatelessWidget {
  final CompletedRun run;
  const _KmRow({required this.run});

  @override
  Widget build(BuildContext context) {
    final d = run.finishedAt;
    final date =
        '${d.day.toString().padLeft(2, '0')}.${d.month.toString().padLeft(2, '0')}.${d.year}';
    return Row(
      crossAxisAlignment: CrossAxisAlignment.end,
      children: [
        Text(
          run.distanceKm.toStringAsFixed(2),
          style: TextStyle(
            fontFamily: AppTheme.fontDisplay,
            fontSize: 44,
            fontWeight: FontWeight.w900,
            letterSpacing: -2,
            height: 1,
            color: AppColors.textPrimary,
          ),
        ),
        const SizedBox(width: 6),
        Padding(
          padding: const EdgeInsets.only(bottom: 4),
          child: Text(
            'КМ',
            style: TextStyle(
              fontFamily: AppTheme.fontDisplay,
              fontSize: 16,
              fontWeight: FontWeight.w800,
              color: AppColors.lime,
            ),
          ),
        ),
        const Spacer(),
        Text(
          date,
          style: TextStyle(
            fontSize: 10,
            letterSpacing: 1.2,
            fontWeight: FontWeight.w700,
            color: AppColors.textSecondary,
          ),
        ),
      ],
    );
  }
}

class _SplitsBlock extends StatelessWidget {
  final List<int> splits;
  const _SplitsBlock({required this.splits});

  @override
  Widget build(BuildContext context) {
    final best = splits.reduce((a, b) => a < b ? a : b);
    final worst = splits.reduce((a, b) => a > b ? a : b);
    String pace(int s) =>
        '${(s ~/ 60)}:${(s % 60).toString().padLeft(2, '0')}';
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: AppColors.bgCard,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AppColors.separator),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'ТЕМП ПО КИЛОМЕТРАМ',
            style: TextStyle(
              fontSize: 9.5,
              fontWeight: FontWeight.w800,
              letterSpacing: 1.6,
              color: AppColors.textSecondary,
            ),
          ),
          const SizedBox(height: 12),
          SizedBox(
            height: 98,
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                for (var i = 0; i < splits.length; i++) ...[
                  if (i > 0) const SizedBox(width: 7),
                  Expanded(
                    child: Column(
                      mainAxisAlignment: MainAxisAlignment.end,
                      children: [
                        Text(
                          pace(splits[i]),
                          style: TextStyle(
                            fontSize: 9,
                            fontWeight: FontWeight.w800,
                            color: splits[i] == best
                                ? AppColors.lime
                                : AppColors.textSecondary,
                          ),
                        ),
                        const SizedBox(height: 4),
                        Container(
                          // Быстрый км — высокий столбик.
                          height: 14 +
                              40 *
                                  (worst == best
                                      ? 1
                                      : (worst - splits[i]) / (worst - best)),
                          decoration: BoxDecoration(
                            borderRadius: const BorderRadius.vertical(
                              top: Radius.circular(6),
                              bottom: Radius.circular(3),
                            ),
                            color: splits[i] == best
                                ? AppColors.lime
                                : AppColors.lime.withValues(alpha: .22),
                            border: Border.all(
                              color: AppColors.lime.withValues(
                                alpha: splits[i] == best ? 1 : .4,
                              ),
                            ),
                          ),
                        ),
                        const SizedBox(height: 4),
                        Text(
                          '${i + 1}',
                          style: TextStyle(
                            fontSize: 8.5,
                            fontWeight: FontWeight.w700,
                            color: AppColors.textTertiary,
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _AwardsBlock extends StatelessWidget {
  final List<MedalFull> awards;
  const _AwardsBlock({required this.awards});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: AppColors.bgCard,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AppColors.separator),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'НАГРАДЫ ЭТОЙ ПРОБЕЖКИ',
            style: TextStyle(
              fontSize: 9.5,
              fontWeight: FontWeight.w800,
              letterSpacing: 1.6,
              color: AppColors.textSecondary,
            ),
          ),
          const SizedBox(height: 10),
          for (var i = 0; i < awards.length; i++) ...[
            if (i > 0) const SizedBox(height: 8),
            InkWell(
              borderRadius: BorderRadius.circular(13),
              onTap: () => showMedalDetail(context, awards[i]),
              child: Container(
                padding:
                    const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
                decoration: BoxDecoration(
                  color: AppColors.bgElevated,
                  borderRadius: BorderRadius.circular(13),
                  border: Border.all(
                    color: AppColors.lime.withValues(alpha: .35),
                  ),
                ),
                child: Row(
                  children: [
                    MedalImage(
                      def: awards[i].def,
                      earned: true,
                      size: 42,
                    ),
                    const SizedBox(width: 11),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            awards[i].def.name,
                            style: TextStyle(
                              fontSize: 13,
                              fontWeight: FontWeight.w800,
                              color: AppColors.textPrimary,
                            ),
                          ),
                          const SizedBox(height: 1),
                          Text(
                            'медаль · тап — карточка и шаринг',
                            style: TextStyle(
                              fontSize: 10.5,
                              color: AppColors.textSecondary,
                            ),
                          ),
                        ],
                      ),
                    ),
                    Icon(
                      CupertinoIcons.chevron_right,
                      size: 15,
                      color: AppColors.lime,
                    ),
                  ],
                ),
              ),
            ),
          ],
        ],
      ),
    );
  }
}

class _PointsBlock extends StatelessWidget {
  final int points;
  final bool captured;
  const _PointsBlock({required this.points, required this.captured});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: AppColors.bgCard,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AppColors.separator),
      ),
      child: Row(
        children: [
          Text(
            '+$points',
            style: TextStyle(
              fontFamily: AppTheme.fontDisplay,
              fontSize: 24,
              fontWeight: FontWeight.w900,
              color: AppColors.lime,
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Text(
              captured
                  ? 'баллы экосистемы за бег и захват · тратятся в МАТА Store'
                  : 'баллы экосистемы за бег · тратятся в МАТА Store',
              style: TextStyle(
                fontSize: 11,
                height: 1.4,
                color: AppColors.textSecondary,
              ),
            ),
          ),
        ],
      ),
    );
  }
}
