import 'dart:async';

import 'package:flutter/material.dart';

import '../../../../core/theme/app_colors.dart';
import '../../data/tick_feedback.dart';
import '../../logic/interval_plan.dart';
import '../widgets/tool_widgets.dart';

/// Метроном каденса: задаёт частоту шагов (шагов/мин) звуком + вибро.
/// Каденс выбирается барабаном. Звук — встроенный системный клик.
class CadenceMetronomeScreen extends StatefulWidget {
  const CadenceMetronomeScreen({super.key});

  @override
  State<CadenceMetronomeScreen> createState() => _CadenceMetronomeScreenState();
}

class _CadenceMetronomeScreenState extends State<CadenceMetronomeScreen> {
  static const _min = 120;
  static const _max = 220;

  int _spm = 170;
  bool _running = false;
  bool _beat = false;
  Timer? _timer;
  final ToolTick _fx = ToolTick();

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

  void _apply(int spm) {
    setState(() => _spm = spm.clamp(_min, _max));
    if (_running) _start();
  }

  void _toggle() => _running ? _stop() : _start();

  void _start() {
    _timer?.cancel();
    final ms = metronomeIntervalMs(_spm);
    if (ms <= 0) return;
    setState(() => _running = true);
    _tick();
    _timer = Timer.periodic(Duration(milliseconds: ms), (_) => _tick());
  }

  void _stop() {
    _timer?.cancel();
    _timer = null;
    if (mounted) {
      setState(() {
        _running = false;
        _beat = false;
      });
    }
  }

  void _tick() {
    _fx.play(TickKind.count);
    if (mounted) setState(() => _beat = !_beat);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.bgDark,
      appBar: AppBar(
        backgroundColor: AppColors.bgDark,
        title: const Text('Метроном каденса'),
      ),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            children: [
              const SizedBox(height: 8),
              Expanded(
                child: Center(
                  child: AnimatedContainer(
                    duration: const Duration(milliseconds: 90),
                    width: _beat ? 190 : 164,
                    height: _beat ? 190 : 164,
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      color: AppColors.electricBlue.withValues(
                        alpha: _beat ? 0.28 : 0.12,
                      ),
                      border: Border.all(
                        color: AppColors.electricBlue.withValues(alpha: 0.6),
                        width: 2,
                      ),
                    ),
                    alignment: Alignment.center,
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Text(
                          '$_spm',
                          style: TextStyle(
                            color: AppColors.textPrimary,
                            fontSize: 56,
                            fontWeight: FontWeight.w900,
                          ),
                        ),
                        Text(
                          'шагов/мин',
                          style: Theme.of(context).textTheme.bodyMedium
                              ?.copyWith(color: AppColors.textSecondary),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
              ToolValueField(
                label: 'Каденс',
                items: [for (var s = _min; s <= _max; s++) '$s'],
                index: _spm - _min,
                onChanged: (i) => _apply(i + _min),
              ),
              const SizedBox(height: 8),
              Wrap(
                spacing: 8,
                alignment: WrapAlignment.center,
                children: const [160, 170, 180]
                    .map(
                      (p) => ActionChip(
                        label: Text('$p'),
                        backgroundColor: AppColors.bgElevated,
                        side: BorderSide(color: AppColors.separator),
                        labelStyle: TextStyle(
                          color: AppColors.textSecondary,
                          fontWeight: FontWeight.w700,
                        ),
                        onPressed: () => _apply(p),
                      ),
                    )
                    .toList(),
              ),
              const SizedBox(height: 14),
              SizedBox(
                width: double.infinity,
                height: 54,
                child: FilledButton.icon(
                  onPressed: _toggle,
                  style: FilledButton.styleFrom(
                    backgroundColor: _running
                        ? AppColors.error
                        : AppColors.electricBlue,
                  ),
                  icon: Icon(_running ? Icons.stop : Icons.play_arrow),
                  label: Text(_running ? 'Стоп' : 'Старт'),
                ),
              ),
              const SizedBox(height: 10),
              Text(
                'Оптимальный беговой каденс обычно 170–185. Звук тихий — лучше '
                'слышно в наушниках; есть вибрация.',
                textAlign: TextAlign.center,
                style: Theme.of(context).textTheme.bodySmall?.copyWith(
                      color: AppColors.textTertiary,
                    ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
