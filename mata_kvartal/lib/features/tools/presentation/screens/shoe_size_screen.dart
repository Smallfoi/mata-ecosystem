import 'package:flutter/material.dart';

import '../../../../core/theme/app_colors.dart';
import '../../logic/shoe_size.dart';
import '../widgets/tool_widgets.dart';

/// Калькулятор размера кроссовок: длина стопы (см, барабан) → RU/EU, см, UK, US.
class ShoeSizeScreen extends StatefulWidget {
  const ShoeSizeScreen({super.key});

  @override
  State<ShoeSizeScreen> createState() => _ShoeSizeScreenState();
}

class _ShoeSizeScreenState extends State<ShoeSizeScreen> {
  // Длина стопы 15.0 … 40.0 см с шагом 0.5.
  static final _feet = List<double>.generate(51, (i) => 15.0 + i * 0.5);
  int _footIdx = 22; // 26.0 см
  bool _running = false;

  static String _fmt(double v) {
    final r = roundHalf(v);
    return r % 1 == 0 ? r.toStringAsFixed(0) : r.toStringAsFixed(1);
  }

  @override
  Widget build(BuildContext context) {
    final footCm = _feet[_footIdx];
    final s = sizesFromFootCm(footCm, running: _running);

    return Scaffold(
      backgroundColor: AppColors.bgDark,
      appBar: AppBar(
        backgroundColor: AppColors.bgDark,
        title: const Text('Размер кроссовок'),
      ),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            ToolCard(
              title: 'Длина стопы',
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  ToolValueField(
                    label: 'Длина стопы',
                    items: [for (final f in _feet) '${f.toStringAsFixed(1)} см'],
                    index: _footIdx,
                    onChanged: (i) => setState(() => _footIdx = i),
                  ),
                  const SizedBox(height: 8),
                  Row(
                    children: [
                      Expanded(
                        child: Text(
                          'Для бега (+0.5)',
                          style: Theme.of(context).textTheme.bodyMedium
                              ?.copyWith(color: AppColors.textSecondary),
                        ),
                      ),
                      Switch(
                        value: _running,
                        onChanged: (v) => setState(() => _running = v),
                      ),
                    ],
                  ),
                  Text(
                    'Измерь стопу от пятки до большого пальца, стоя. Лучше '
                    'вечером — к вечеру стопа немного больше.',
                    style: Theme.of(context).textTheme.bodySmall?.copyWith(
                          color: AppColors.textTertiary,
                        ),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 16),
            _SizeTile(label: 'RU / EU', sub: 'европейский', value: _fmt(s.eu)),
            const SizedBox(height: 10),
            _SizeTile(
              label: 'Mondopoint',
              sub: 'длина стопы, см',
              value: _fmt(s.mondo),
            ),
            const SizedBox(height: 10),
            _SizeTile(label: 'UK', sub: 'британский', value: _fmt(s.uk)),
            const SizedBox(height: 10),
            _SizeTile(label: 'US', sub: 'мужской', value: _fmt(s.usMen)),
            const SizedBox(height: 10),
            _SizeTile(label: 'US', sub: 'женский', value: _fmt(s.usWomen)),
            const SizedBox(height: 12),
            Text(
              'Размеры приблизительные — сетки брендов отличаются. Перед покупкой '
              'сверяйся с размерной таблицей конкретной модели.',
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: AppColors.textTertiary,
                  ),
            ),
          ],
        ),
      ),
    );
  }
}

class _SizeTile extends StatelessWidget {
  final String label;
  final String sub;
  final String value;
  const _SizeTile({required this.label, required this.sub, required this.value});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
      decoration: BoxDecoration(
        color: AppColors.bgCard,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppColors.separator),
      ),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  label,
                  style: Theme.of(context).textTheme.titleSmall?.copyWith(
                        color: AppColors.textPrimary,
                        fontWeight: FontWeight.w700,
                      ),
                ),
                Text(
                  sub,
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                        color: AppColors.textTertiary,
                      ),
                ),
              ],
            ),
          ),
          Text(
            value,
            style: TextStyle(
              color: AppColors.electricBlue,
              fontSize: 22,
              fontWeight: FontWeight.w900,
            ),
          ),
        ],
      ),
    );
  }
}
