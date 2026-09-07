import 'dart:async';

import 'package:flutter/material.dart';

import '../../../../core/theme/app_colors.dart';
import '../../data/tick_feedback.dart';
import '../../logic/interval_plan.dart';
import '../widgets/tool_widgets.dart';

/// Интервальный таймер: настраиваешь работу/отдых/раунды барабанами и бежишь
/// по сигналам (звук + вибро на сменах фаз). Звук — встроенный системный клик.
class IntervalTimerScreen extends StatefulWidget {
  const IntervalTimerScreen({super.key});

  @override
  State<IntervalTimerScreen> createState() => _IntervalTimerScreenState();
}

class _IntervalTimerScreenState extends State<IntervalTimerScreen> {
  Duration _work = const Duration(seconds: 30);
  Duration _rest = const Duration(seconds: 30);
  int _rounds = 8;

  /// Меняется при выборе пресета — чтобы барабаны времени пере-инициализировались.
  int _cfgVersion = 0;

  List<IntervalStep>? _plan;
  int _stepIndex = 0;
  int _remaining = 0;
  bool _paused = false;
  Timer? _timer;
  final ToolTick _fx = ToolTick();

  static const _presets =
      <({String label, Duration work, Duration rest, int rounds})>[
        (
          label: 'Табата 20/10 ×8',
          work: Duration(seconds: 20),
          rest: Duration(seconds: 10),
          rounds: 8,
        ),
        (
          label: '30/30 ×8',
          work: Duration(seconds: 30),
          rest: Duration(seconds: 30),
          rounds: 8,
        ),
        (
          label: '1:00 / 1:00 ×5',
          work: Duration(minutes: 1),
          rest: Duration(minutes: 1),
          rounds: 5,
        ),
      ];

  @override
  void initState() {
    super.initState();
    _fx.init();
  }

  @override
  void dispose() {
    _timer?.cancel();
    _fx.dispose();
    super.dispose();
  }

  void _start() {
    final plan = buildIntervalPlan(
      workSec: _work.inSeconds,
      restSec: _rest.inSeconds,
      rounds: _rounds,
    );
    if (plan.isEmpty) return;
    _fx.play(TickKind.work);
    setState(() {
      _plan = plan;
      _stepIndex = 0;
      _remaining = plan.first.seconds;
      _paused = false;
    });
    _timer = Timer.periodic(const Duration(seconds: 1), (_) => _onSecond());
  }

  void _onSecond() {
    if (_paused) return;
    if (_remaining > 1) {
      setState(() => _remaining--);
      // Обратный отсчёт последних 5 секунд фазы — тики.
      if (_remaining <= 5) _fx.play(TickKind.count);
      return;
    }
    _advance();
  }

  void _advance() {
    final plan = _plan;
    if (plan == null) return;
    final next = _stepIndex + 1;
    if (next >= plan.length) {
      _finish();
      return;
    }
    // Свой сигнал на старт «Работы» и «Отдыха» — их слышно по-разному.
    final step = plan[next];
    _fx.play(step.phase == IntervalPhase.work ? TickKind.work : TickKind.rest);
    setState(() {
      _stepIndex = next;
      _remaining = step.seconds;
    });
  }

  void _finish() {
    _timer?.cancel();
    _timer = null;
    _fx.play(TickKind.finish);
    setState(() {
      _plan = null;
      _stepIndex = 0;
      _remaining = 0;
      _paused = false;
    });
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Готово! Тренировка завершена.')),
      );
    }
  }

  void _stop() {
    _timer?.cancel();
    _timer = null;
    setState(() {
      _plan = null;
      _stepIndex = 0;
      _remaining = 0;
      _paused = false;
    });
  }

  static String _mmss(int sec) {
    final m = sec ~/ 60;
    final s = sec % 60;
    return '$m:${s.toString().padLeft(2, '0')}';
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.bgDark,
      appBar: AppBar(
        backgroundColor: AppColors.bgDark,
        title: const Text('Интервальный таймер'),
      ),
      body: SafeArea(
        child: _plan == null ? _buildConfig(context) : _buildRunning(context),
      ),
    );
  }

  Widget _buildConfig(BuildContext context) {
    final total = intervalPlanTotalSec(
      buildIntervalPlan(
        workSec: _work.inSeconds,
        restSec: _rest.inSeconds,
        rounds: _rounds,
      ),
    );

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        ToolCard(
          child: ToolTimeField(
            key: ValueKey('work-$_cfgVersion'),
            label: 'Работа',
            value: _work,
            onChanged: (d) => setState(() => _work = d),
          ),
        ),
        const SizedBox(height: 10),
        ToolCard(
          child: ToolTimeField(
            key: ValueKey('rest-$_cfgVersion'),
            label: 'Отдых',
            value: _rest,
            onChanged: (d) => setState(() => _rest = d),
          ),
        ),
        const SizedBox(height: 10),
        ToolCard(
          child: ToolValueField(
            label: 'Раундов',
            items: [for (var r = 1; r <= 30; r++) '$r'],
            index: _rounds - 1,
            onChanged: (i) => setState(() => _rounds = i + 1),
          ),
        ),
        const SizedBox(height: 16),
        Text(
          'Готовые пресеты',
          style: Theme.of(context).textTheme.titleSmall?.copyWith(
                color: AppColors.textSecondary,
                fontWeight: FontWeight.w700,
              ),
        ),
        const SizedBox(height: 10),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: _presets
              .map(
                (p) => ActionChip(
                  label: Text(p.label),
                  backgroundColor: AppColors.bgElevated,
                  side: BorderSide(color: AppColors.separator),
                  labelStyle: TextStyle(
                    color: AppColors.textSecondary,
                    fontWeight: FontWeight.w700,
                  ),
                  onPressed: () => setState(() {
                    _work = p.work;
                    _rest = p.rest;
                    _rounds = p.rounds;
                    _cfgVersion++;
                  }),
                ),
              )
              .toList(),
        ),
        const SizedBox(height: 20),
        Center(
          child: Text(
            'Всего: ${_mmss(total)}',
            style: Theme.of(context).textTheme.titleMedium?.copyWith(
                  color: AppColors.textSecondary,
                ),
          ),
        ),
        const SizedBox(height: 16),
        SizedBox(
          height: 54,
          child: FilledButton.icon(
            onPressed: _start,
            icon: const Icon(Icons.play_arrow),
            label: const Text('Старт'),
          ),
        ),
      ],
    );
  }

  Widget _buildRunning(BuildContext context) {
    final plan = _plan!;
    final step = plan[_stepIndex];
    final isWork = step.phase == IntervalPhase.work;
    final color = isWork ? AppColors.electricBlue : AppColors.success;
    final phaseText = isWork ? 'РАБОТА' : 'ОТДЫХ';
    final progress = step.seconds > 0
        ? (step.seconds - _remaining) / step.seconds
        : 0.0;

    return Padding(
      padding: const EdgeInsets.all(16),
      child: Column(
        children: [
          const SizedBox(height: 8),
          Text(
            'Раунд ${step.round} из $_rounds',
            style: Theme.of(context).textTheme.titleMedium?.copyWith(
                  color: AppColors.textSecondary,
                ),
          ),
          Expanded(
            child: Center(
              child: Container(
                width: 240,
                height: 240,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: color.withValues(alpha: _paused ? 0.06 : 0.16),
                  border: Border.all(color: color, width: 3),
                ),
                alignment: Alignment.center,
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(
                      phaseText,
                      style: TextStyle(
                        color: color,
                        fontSize: 18,
                        fontWeight: FontWeight.w900,
                        letterSpacing: 2,
                      ),
                    ),
                    const SizedBox(height: 6),
                    Text(
                      _mmss(_remaining),
                      style: TextStyle(
                        color: AppColors.textPrimary,
                        fontSize: 68,
                        fontWeight: FontWeight.w900,
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
          ClipRRect(
            borderRadius: BorderRadius.circular(6),
            child: LinearProgressIndicator(
              value: progress.clamp(0.0, 1.0),
              minHeight: 8,
              backgroundColor: AppColors.bgElevated,
              valueColor: AlwaysStoppedAnimation<Color>(color),
            ),
          ),
          const SizedBox(height: 20),
          Row(
            children: [
              Expanded(
                child: SizedBox(
                  height: 54,
                  child: OutlinedButton.icon(
                    onPressed: () => setState(() => _paused = !_paused),
                    style: OutlinedButton.styleFrom(
                      foregroundColor: AppColors.textPrimary,
                      side: BorderSide(color: AppColors.separator),
                    ),
                    icon: Icon(_paused ? Icons.play_arrow : Icons.pause),
                    label: Text(_paused ? 'Продолжить' : 'Пауза'),
                  ),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: SizedBox(
                  height: 54,
                  child: FilledButton.icon(
                    onPressed: _stop,
                    style: FilledButton.styleFrom(
                      backgroundColor: AppColors.error,
                    ),
                    icon: const Icon(Icons.stop),
                    label: const Text('Стоп'),
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
        ],
      ),
    );
  }
}
