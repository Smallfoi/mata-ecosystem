import 'dart:async' show unawaited;

import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../../../../core/theme/app_colors.dart';
import '../../../../core/theme/app_theme.dart';
import '../../../map/data/zone_provider.dart';
import '../../../territory/data/territory_provider.dart';
import '../../../permissions/data/location_access_provider.dart';
import '../../../permissions/presentation/location_setup_sheet.dart';
import '../../data/run_mode_provider.dart';
import '../../data/run_provider.dart';
import 'run_result_screen.dart';
import 'runs_journal_screen.dart' show RunTileCard;
import '../../data/completed_runs_provider.dart';
import '../../../shoes/presentation/shoe_run_picker.dart';
import '../../../../shared/widgets/kvartal_logo.dart';

const _locSetupShownKey = 'kvartal.loc_setup_shown.v1';

class RunScreen extends ConsumerWidget {
  const RunScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final runState = ref.watch(runProvider);
    return runState.status == RunStatus.idle
        ? _IdleView(runState: runState)
        : _ActiveRunView(runState: runState);
  }
}

// ── Экран до начала тренировки ─────────────────────────────────────────────

class _IdleView extends ConsumerStatefulWidget {
  final RunState runState;
  const _IdleView({required this.runState});

  @override
  ConsumerState<_IdleView> createState() => _IdleViewState();
}

class _IdleViewState extends ConsumerState<_IdleView> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _maybeOnboardLocation());
  }

  /// Один раз при первом запуске объясняем и просим фоновую геолокацию.
  /// Дальше — постоянный баннер-предупреждение, пока доступ не настроен.
  Future<void> _maybeOnboardLocation() async {
    await ref.read(locationAccessProvider.notifier).refresh();
    if (!mounted) return;
    final prefs = await SharedPreferences.getInstance();
    final shown = prefs.getBool(_locSetupShownKey) ?? false;
    if (shown) return;
    final st = ref.read(locationAccessProvider);
    if (st.fullyReady) return;
    await prefs.setBool(_locSetupShownKey, true);
    if (!mounted) return;
    openLocationSetup(context);
  }

  /// Pull-to-refresh: перезагрузить историю забегов (синк push+pull обновит и баланс).
  Future<void> _refresh() async {
    await ref.read(completedRunsProvider.notifier).load();
  }

  @override
  Widget build(BuildContext context) {
    final recentRuns = ref.watch(completedRunsProvider);
    final stats = _RunStats.from(recentRuns);

    return Scaffold(
      backgroundColor: AppColors.bgDark,
      // Фоновый градиент (синий сверху → чёрный) — как на профиле/клубе/рейтинге.
      body: DecoratedBox(
        decoration: BoxDecoration(
          color: AppColors.bg,
        ),
        child: SafeArea(
          child: RefreshIndicator(
            onRefresh: _refresh,
            child: SingleChildScrollView(
              physics: const AlwaysScrollableScrollPhysics(),
              padding: const EdgeInsets.fromLTRB(20, 16, 20, 128),
              child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _RunHeader(),
                const SizedBox(height: 16),
                const LocationWarningBanner(),
                // Ф3: первый квест до первой пробежки — короткий и достижимый.
                if (recentRuns.isEmpty) ...[
                  const _FirstQuestCard(),
                  const SizedBox(height: 16),
                ],
                _QuickStatsRow(stats: stats),
                const SizedBox(height: 20),
                _StartCard(),
                const SizedBox(height: 24),
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Text(
                      'Цели на неделю',
                      style: Theme.of(context).textTheme.titleMedium?.copyWith(
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    Text(
                      '${(stats.weekProgress * 100).round()}%',
                      style: TextStyle(
                        fontSize: 13,
                        fontWeight: FontWeight.w700,
                        color: AppColors.accentInk,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 12),
                _WeeklyGoalCard(weekKm: stats.weekKm),
                const SizedBox(height: 24),
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Text(
                      'Последние пробежки',
                      style: Theme.of(context).textTheme.titleMedium?.copyWith(
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    GestureDetector(
                      onTap: () => context.push('/runs'),
                      child: Text(
                        'Все',
                        style: TextStyle(
                          fontSize: 13,
                          fontWeight: FontWeight.w600,
                          color: AppColors.accentInk,
                        ),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 10),
                if (recentRuns.isEmpty)
                  const _EmptyRunsHint()
                else
                  for (final r in recentRuns.take(3)) ...[
                    RunTileCard(
                      run: r,
                      onTap: () => context.push('/runs/passport', extra: r),
                    ),
                    const SizedBox(height: 8),
                  ],
              ],
            ),
          ),
          ),
        ),
      ),
    );
  }
}


class _RunHeader extends ConsumerWidget {
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final mode = ref.watch(runModeProvider);
    return Row(
      mainAxisAlignment: MainAxisAlignment.spaceBetween,
      children: [
        Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'КВАРТАЛ',
              style: Theme.of(context).textTheme.headlineMedium?.copyWith(
                fontWeight: FontWeight.w800,
                height: 1.1,
              ),
            ),
            const SizedBox(height: 2),
            Text(
              mode == RunMode.free
                  ? 'Якутск · беги в своём темпе'
                  : 'Якутск · территория ждёт',
              style: Theme.of(
                context,
              ).textTheme.bodySmall?.copyWith(color: AppColors.textTertiary),
            ),
          ],
        ),
        Container(
          width: 48,
          height: 48,
          decoration: BoxDecoration(
            color: AppColors.bgCard,
            borderRadius: BorderRadius.circular(14),
            border: Border.all(color: AppColors.separator),
          ),
          child: const Center(child: KvartalLogoMark(size: 34)),
        ),
      ],
    );
  }
}

/// Реальная статистика бега из истории забегов (completedRunsProvider, синк с
/// сервером push+pull). Один источник правды — без зашитых заглушек.
class _RunStats {
  final double todayKm;
  final double weekKm;
  final int streakDays;
  final int totalZones;
  const _RunStats({
    required this.todayKm,
    required this.weekKm,
    required this.streakDays,
    required this.totalZones,
  });

  static const weeklyGoalKm = 40.0;
  double get weekProgress => (weekKm / weeklyGoalKm).clamp(0.0, 1.0);

  factory _RunStats.from(List<CompletedRun> runs) {
    final now = DateTime.now();
    final today = DateTime(now.year, now.month, now.day);
    final weekStart = today.subtract(Duration(days: today.weekday - 1)); // пн
    double todayKm = 0, weekKm = 0;
    int zones = 0;
    final days = <DateTime>{};
    for (final r in runs) {
      final d = DateTime(r.finishedAt.year, r.finishedAt.month, r.finishedAt.day);
      if (d == today) todayKm += r.distanceKm;
      if (!d.isBefore(weekStart)) weekKm += r.distanceKm;
      zones += r.capturedZones;
      days.add(d);
    }
    // Дней подряд: считаем назад от сегодня (или со вчера, если сегодня ещё не бегал).
    int streak = 0;
    var probe = today;
    if (!days.contains(probe)) probe = probe.subtract(const Duration(days: 1));
    while (days.contains(probe)) {
      streak++;
      probe = probe.subtract(const Duration(days: 1));
    }
    return _RunStats(
      todayKm: todayKm, weekKm: weekKm, streakDays: streak, totalZones: zones,
    );
  }
}

class _QuickStatsRow extends ConsumerWidget {
  final _RunStats stats;
  const _QuickStatsRow({required this.stats});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final isFreeRun = ref.watch(runModeProvider) == RunMode.free;
    return Row(
      children: [
        _QuickStat(
          icon: CupertinoIcons.flame_fill,
          value: stats.todayKm.toStringAsFixed(1),
          label: 'км сегодня',
          color: AppColors.accentInk,
        ),
        const SizedBox(width: 10),
        _QuickStat(
          icon: CupertinoIcons.bolt_fill,
          value: '${stats.streakDays}',
          label: 'дней подряд',
          color: AppColors.accentInk,
        ),
        const SizedBox(width: 10),
        // Свободному бегуну зоны не нужны — вместо них километры недели.
        if (isFreeRun)
          _QuickStat(
            icon: CupertinoIcons.chart_bar_alt_fill,
            value: stats.weekKm.toStringAsFixed(1),
            label: 'км за неделю',
            color: AppColors.accentInk,
          )
        else
          _QuickStat(
            icon: CupertinoIcons.location_fill,
            value: '${stats.totalZones}',
            label: 'зон моих',
            color: AppColors.accentInk,
          ),
      ],
    );
  }
}

class _QuickStat extends StatelessWidget {
  final IconData icon;
  final String value, label;
  final Color color;
  const _QuickStat({
    required this.icon,
    required this.value,
    required this.label,
    required this.color,
  });

  @override
  Widget build(BuildContext context) {
    return Expanded(
      child: Container(
        padding: const EdgeInsets.symmetric(vertical: 12, horizontal: 10),
        decoration: BoxDecoration(
          color: color.withValues(alpha: 0.10),
          borderRadius: BorderRadius.circular(14),
          border: Border.all(color: color.withValues(alpha: 0.25)),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(icon, color: color, size: 16),
            const SizedBox(height: 7),
            Text(
              value,
              style: TextStyle(
                fontSize: 20,
                fontWeight: FontWeight.w800,
                color: AppColors.textPrimary,
                height: 1,
              ),
            ),
            const SizedBox(height: 2),
            Text(
              label,
              style: TextStyle(
                fontSize: 10,
                color: AppColors.textSecondary,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _StartCard extends ConsumerWidget {
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final mode = ref.watch(runModeProvider);
    return GestureDetector(
          onTap: () async {
            // Перед стартом спрашиваем, в каких кроссовках бежим — с выбранной
            // пары спишется ресурс (если есть пары; иначе сразу старт).
            final proceed = await showRunShoePicker(context, ref);
            if (!proceed || !context.mounted) return;
            ref.read(runProvider.notifier).start();
          },
          child: Container(
            width: double.infinity,
            padding: const EdgeInsets.all(22),
            decoration: BoxDecoration(
              gradient: LinearGradient(
                colors: [AppColors.graphite, Color(0xFF15181C)],
                begin: Alignment.topLeft,
                end: Alignment.bottomRight,
              ),
              borderRadius: BorderRadius.circular(24),
              border: Border.all(color: AppColors.lime.withValues(alpha: 0.35)),
            ),
            child: Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        'Готов бежать?',
                        style: Theme.of(context).textTheme.headlineSmall
                            ?.copyWith(
                              color: AppColors.onDark,
                              fontWeight: FontWeight.w700,
                            ),
                      ),
                      const SizedBox(height: 4),
                      Text(
                        mode == RunMode.free
                            ? 'Темп, дистанция, время. Твой бег.'
                            : 'Замкни маршрут. Забери квартал.',
                        style: TextStyle(
                          fontSize: 14,
                          color: AppColors.onDark.withValues(alpha: 0.72),
                        ),
                      ),
                      const SizedBox(height: 14),
                      const _RunModeSwitch(),
                      const SizedBox(height: 14),
                      Container(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 18,
                          vertical: 10,
                        ),
                        decoration: BoxDecoration(
                          color: AppColors.lime,
                          borderRadius: BorderRadius.circular(AppTheme.rPill),
                        ),
                        child: Row(
                          mainAxisSize: MainAxisSize.min,
                          children: const [
                            // На лайме — только константный тёмный: AppColors.ink
                            // в графитовой теме светлый и на лайме невидим.
                            Icon(
                              CupertinoIcons.play_fill,
                              color: Color(0xFF171C19),
                              size: 13,
                            ),
                            SizedBox(width: 8),
                            Text(
                              'НАЧАТЬ',
                              style: TextStyle(
                                color: Color(0xFF171C19),
                                fontWeight: FontWeight.w800,
                                fontSize: 13,
                                letterSpacing: 1.2,
                              ),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(width: 16),
                // Плитка знака — скруглённый квадрат, как иконка приложения
                // (владелец 2026-08-22: никаких кругов, знак везде одинаковый).
                Container(
                  width: 82,
                  height: 82,
                  decoration: BoxDecoration(
                    borderRadius: BorderRadius.circular(22),
                    color: AppColors.line,
                    border: Border.all(
                      color: AppColors.lime.withValues(alpha: 0.35),
                      width: 1.2,
                    ),
                    boxShadow: [
                      BoxShadow(
                        color: AppColors.lime.withValues(alpha: 0.22),
                        blurRadius: 28,
                        spreadRadius: 2,
                      ),
                    ],
                  ),
                  child: const Center(
                    child: KvartalLogoMark(
                      size: 58,
                      outline: Color(0xFFEDEFE8), // светлый контур на тёмной карточке
                    ),
                  ),
                ),
              ],
            ),
          ),
        )
        .animate(onPlay: (c) => c.repeat(reverse: true))
        .scaleXY(
          begin: 1.0,
          end: 1.015,
          duration: 2200.ms,
          curve: Curves.easeInOut,
        );
  }
}

/// Переключатель режима пробежки прямо на карточке старта: один тап —
/// и «чистый бегун» убирает игру в захват, один тап — возвращает.
/// Выбор запоминается между сессиями (kvartal.run_mode.v1).
class _RunModeSwitch extends ConsumerWidget {
  const _RunModeSwitch();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final mode = ref.watch(runModeProvider);
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        for (final option in RunMode.values) ...[
          if (option != RunMode.values.first) const SizedBox(width: 8),
          GestureDetector(
            // Перехватывает тап раньше карточки — старт не сработает.
            onTap: () => ref.read(runModeProvider.notifier).set(option),
            child: AnimatedContainer(
              duration: const Duration(milliseconds: 180),
              curve: Curves.easeOut,
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
              decoration: BoxDecoration(
                color: mode == option
                    ? AppColors.lime.withValues(alpha: 0.16)
                    : Colors.transparent,
                borderRadius: BorderRadius.circular(AppTheme.rPill),
                border: Border.all(
                  color: mode == option
                      ? AppColors.lime.withValues(alpha: 0.8)
                      : AppColors.onDark.withValues(alpha: 0.25),
                ),
              ),
              child: Text(
                option.label,
                style: TextStyle(
                  fontSize: 12,
                  fontWeight: FontWeight.w700,
                  letterSpacing: 0.3,
                  color: mode == option
                      ? AppColors.lime
                      : AppColors.onDark.withValues(alpha: 0.65),
                ),
              ),
            ),
          ),
        ],
      ],
    );
  }
}

// ── Экран активной тренировки ──────────────────────────────────────────────

class _ActiveRunView extends ConsumerWidget {
  final RunState runState;
  const _ActiveRunView({required this.runState});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final notifier = ref.read(runProvider.notifier);
    final isActive = runState.status == RunStatus.active;
    final isFreeRun = ref.watch(runModeProvider) == RunMode.free;

    return Scaffold(
      backgroundColor: AppColors.bgDark,
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [
              Row(
                children: [
                  _StatusBadge(isActive: isActive),
                  const Spacer(),
                  GestureDetector(
                    onTap: () => _showStopDialog(context, ref),
                    child: Container(
                      width: 36,
                      height: 36,
                      decoration: BoxDecoration(
                        color: AppColors.bgCard,
                        shape: BoxShape.circle,
                        border: Border.all(color: AppColors.separator),
                      ),
                      child: Icon(
                        CupertinoIcons.xmark,
                        color: AppColors.textSecondary,
                        size: 16,
                      ),
                    ),
                  ),
                ],
              ),
              const Spacer(),

              Text(
                runState.distanceKm.toStringAsFixed(2),
                style: TextStyle(
                  fontSize: 84,
                  fontWeight: FontWeight.w900,
                  color: AppColors.textPrimary,
                  height: 1,
                  letterSpacing: -4,
                ),
              ),
              Text(
                'КМ',
                style: TextStyle(
                  fontSize: 12,
                  fontWeight: FontWeight.w700,
                  letterSpacing: 4,
                  color: AppColors.textSecondary,
                ),
              ),
              const SizedBox(height: 32),

              Container(
                padding: const EdgeInsets.symmetric(
                  vertical: 20,
                  horizontal: 16,
                ),
                decoration: BoxDecoration(
                  color: AppColors.bgCard,
                  borderRadius: BorderRadius.circular(20),
                  border: Border.all(color: AppColors.separator),
                ),
                child: Row(
                  children: [
                    _MetricTile(
                      label: 'ВРЕМЯ',
                      value: runState.elapsedFormatted,
                    ),
                    _MetricDivider(),
                    _MetricTile(
                      label: 'ТЕМП',
                      value: '${runState.paceFormatted}/км',
                    ),
                    // В свободном режиме зон нет — метрика была бы шумом.
                    if (!isFreeRun) ...[
                      _MetricDivider(),
                      const _MetricTile(label: 'ЗОНЫ', value: '+0'),
                    ],
                  ],
                ),
              ),
              const Spacer(),

              Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  _RunControlButton(
                    icon: isActive
                        ? CupertinoIcons.pause_fill
                        : CupertinoIcons.play_fill,
                    color: isActive ? AppColors.warning : AppColors.success,
                    onTap: () =>
                        isActive ? notifier.pause() : notifier.resume(),
                  ),
                  const SizedBox(width: 24),
                  _RunControlButton(
                    icon: CupertinoIcons.stop_fill,
                    color: AppColors.error,
                    onTap: () => _showStopDialog(context, ref),
                    size: 72,
                  ),
                  const SizedBox(width: 24),
                  _RunControlButton(
                    icon: CupertinoIcons.map,
                    color: AppColors.warning,
                    onTap: () => context.go('/map'),
                  ),
                ],
              ),
              const SizedBox(height: 16),
            ],
          ),
        ),
      ),
    );
  }

  void _showStopDialog(BuildContext context, WidgetRef ref) {
    final run = ref.read(runProvider);
    final distance = run.distanceKm.toStringAsFixed(2);

    // Завершение без захвата — общий путь свободного режима и незамкнутого
    // контура. Километры всё равно уйдут на сервер (зачёты/дивизион/баллы).
    void finishWithoutCapture(BuildContext ctx) {
      final result = RunResult(
        route: List.of(run.route),
        elapsed: run.elapsed,
        distanceMeters: run.distanceMeters,
        capturedZones: 0,
        capturedTerritory: false,
        finishedAt: DateTime.now(),
        runId: '',
      );
      ref.read(runProvider.notifier).stop();
      Navigator.pop(ctx);
      // Без захвата — без салюта: церемония пройдёт тихой веткой.
      context.push('/run/result', extra: result);
    }

    // Свободный режим: никакой риторики захвата — только бег и его цифры.
    if (ref.read(runModeProvider) == RunMode.free) {
      showDialog(
        context: context,
        builder: (ctx) => AlertDialog(
          backgroundColor: AppColors.bgCard,
          shape:
              RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
          title: const Text('Завершить пробежку?'),
          content: Text(
            'Дистанция: $distance км\n'
            'Время: ${run.elapsedFormatted}',
            style: TextStyle(color: AppColors.textSecondary),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(ctx),
              child: const Text('Продолжить'),
            ),
            FilledButton(
              onPressed: () => finishWithoutCapture(ctx),
              style: FilledButton.styleFrom(
                backgroundColor: AppColors.electricBlue,
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(10),
                ),
              ),
              child: const Text('Завершить'),
            ),
          ],
        ),
      );
      return;
    }

    final zoneNotifier = ref.read(zoneProvider.notifier);
    final closure = zoneNotifier.inspectLoopClosure(run.route);
    final canCapture = closure.canCapture;
    final gap = closure.gapMeters.round();
    final captureHint = canCapture
        ? 'Контур замкнут по GPS. Подтверди захват территории.'
        : closure.hasEnoughDistance
        ? 'До стартовой точки по GPS: $gap м. Для захвата нужно вернуться в радиус 20 м.'
        : 'Маршрут слишком короткий для захвата. Минимальный периметр: 50 м.';

    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: AppColors.bgCard,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
        title: Text(
          canCapture ? 'Захватить территорию?' : 'Завершить пробежку?',
        ),
        content: Text(
          'Дистанция: $distance км\n'
          'Время: ${run.elapsedFormatted}\n'
          'До старта: $gap м\n'
          '$captureHint',
          style: TextStyle(color: AppColors.textSecondary),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Продолжить'),
          ),
          if (!canCapture)
            TextButton(
              onPressed: () => finishWithoutCapture(ctx),
              child: const Text('Завершить без захвата'),
            ),
          FilledButton(
            onPressed: canCapture
                ? () {
                    final captured = zoneNotifier.checkAndCaptureLoop(
                      run.route,
                    );
                    // Реальный захват на PostGIS-бэке (D-09): отправляем маршрут
                    // + дистанцию/время для серверного античита по скорости.
                    // Карта подписана на territoryProvider и обновится сама,
                    // как только сервер вернёт обновлённую территорию.
                    unawaited(
                      ref
                          .read(territoryProvider.notifier)
                          .capture(
                            run.route,
                            distanceMeters: run.distanceMeters,
                            elapsedSeconds: run.elapsed.inSeconds,
                          ),
                    );
                    final result = RunResult(
                      route: List.of(run.route),
                      elapsed: run.elapsed,
                      distanceMeters: run.distanceMeters,
                      capturedZones: captured.length,
                      capturedTerritory: true,
                      finishedAt: DateTime.now(),
                      runId: '',
                    );
                    ref
                        .read(runProvider.notifier)
                        .stop(
                          capturedZones: captured.length,
                          capturedTerritory: true,
                        );
                    Navigator.pop(ctx);
                    context.push('/run/result', extra: result);
                  }
                : null,
            style: FilledButton.styleFrom(
              backgroundColor: AppColors.electricBlue,
              disabledBackgroundColor: AppColors.bgElevated,
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(10),
              ),
            ),
            child: const Text('Захватить'),
          ),
        ],
      ),
    );
  }
}

class _StatusBadge extends StatelessWidget {
  final bool isActive;
  const _StatusBadge({required this.isActive});

  @override
  Widget build(BuildContext context) {
    final color = isActive ? AppColors.success : AppColors.warning;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.15),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: color.withValues(alpha: 0.4)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
                width: 6,
                height: 6,
                decoration: BoxDecoration(color: color, shape: BoxShape.circle),
              )
              .animate(onPlay: (c) => c.repeat(reverse: true))
              .scaleXY(
                begin: 0.6,
                end: 1.5,
                duration: 700.ms,
                curve: Curves.easeInOut,
              ),
          const SizedBox(width: 6),
          Text(
            isActive ? 'ЗАПИСЬ' : 'ПАУЗА',
            style: TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.w700,
              color: color,
              letterSpacing: 1,
            ),
          ),
        ],
      ),
    );
  }
}

class _MetricTile extends StatelessWidget {
  final String label, value;
  const _MetricTile({required this.label, required this.value});

  @override
  Widget build(BuildContext context) {
    return Expanded(
      child: Column(
        children: [
          Text(
            value,
            style: Theme.of(context).textTheme.titleLarge,
            textAlign: TextAlign.center,
          ),
          const SizedBox(height: 4),
          Text(
            label,
            style: Theme.of(
              context,
            ).textTheme.labelSmall?.copyWith(letterSpacing: 1),
            textAlign: TextAlign.center,
          ),
        ],
      ),
    );
  }
}

class _MetricDivider extends StatelessWidget {
  @override
  Widget build(BuildContext context) =>
      Container(width: 1, height: 36, color: AppColors.separator);
}

class _RunControlButton extends StatelessWidget {
  final IconData icon;
  final Color color;
  final VoidCallback onTap;
  final double size;
  const _RunControlButton({
    required this.icon,
    required this.color,
    required this.onTap,
    this.size = 60,
  });

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        width: size,
        height: size,
        decoration: BoxDecoration(
          color: color.withValues(alpha: 0.15),
          shape: BoxShape.circle,
          border: Border.all(color: color.withValues(alpha: 0.4), width: 2),
        ),
        child: Icon(icon, color: color, size: size * 0.42),
      ),
    );
  }
}

// ── Run history widgets ───────────────────────────────────────────────────

class _EmptyRunsHint extends StatelessWidget {
  const _EmptyRunsHint();

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: AppColors.bgCard,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AppColors.separator),
      ),
      child: Text(
        'Завершённые пробежки появятся здесь после первого старта.',
        style: TextStyle(color: AppColors.textSecondary, fontSize: 13),
      ),
    );
  }
}

class _WeeklyGoalCard extends StatelessWidget {
  final double weekKm;
  const _WeeklyGoalCard({required this.weekKm});

  @override
  Widget build(BuildContext context) {
    final current = weekKm;
    const goal = _RunStats.weeklyGoalKm;
    final progress = (current / goal).clamp(0.0, 1.0);

    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        color: AppColors.bgCard,
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: AppColors.separator),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(
                '${current.toStringAsFixed(1)} км',
                style: Theme.of(
                  context,
                ).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w800),
              ),
              Text(
                'из ${goal.toStringAsFixed(0)} км',
                style: Theme.of(
                  context,
                ).textTheme.bodySmall?.copyWith(color: AppColors.textSecondary),
              ),
            ],
          ),
          const SizedBox(height: 12),
          ClipRRect(
            borderRadius: BorderRadius.circular(6),
            child: LinearProgressIndicator(
              value: progress,
              minHeight: 8,
              backgroundColor: AppColors.bgElevated,
              valueColor: AlwaysStoppedAnimation(AppColors.electricBlue),
            ),
          ),
          const SizedBox(height: 10),
          Text(
            current >= goal
                ? 'Цель недели выполнена 🎉'
                : 'Осталось ${(goal - current).toStringAsFixed(1)} км до цели',
            style: Theme.of(
              context,
            ).textTheme.bodySmall?.copyWith(color: AppColors.textTertiary),
          ),
        ],
      ),
    );
  }
}


/// Ф3 «Вход в игру»: первый квест — 800 метров, конец кроется медалью дня 1.
class _FirstQuestCard extends StatelessWidget {
  const _FirstQuestCard();

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: AppColors.block,
        borderRadius: BorderRadius.circular(16),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'ПЕРВЫЙ КВЕСТ',
            style: TextStyle(
              fontSize: 10.5,
              fontWeight: FontWeight.w800,
              letterSpacing: 1.6,
              color: Color(0xFFDFF45F),
            ),
          ),
          const SizedBox(height: 6),
          const Text(
            'Пробеги 800 метров',
            style: TextStyle(
              fontFamily: AppTheme.fontDisplay,
              fontSize: 19,
              fontWeight: FontWeight.w800,
              color: Color(0xFFEDEFE8),
            ),
          ),
          const SizedBox(height: 4),
          const Text(
            'Небольшой круг у дома — этого достаточно. '
            'За первую пробежку — стальной штамп «Первый бег».',
            style: TextStyle(
              fontSize: 12.5,
              height: 1.45,
              fontWeight: FontWeight.w500,
              color: Color(0xFF9AA59D),
            ),
          ),
        ],
      ),
    );
  }
}
