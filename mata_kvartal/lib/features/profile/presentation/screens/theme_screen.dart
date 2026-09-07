import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../../core/theme/app_colors.dart';
import '../../../../core/theme/app_theme.dart';
import '../../../../core/theme/theme_controller.dart';

/// Экран «Тема» (Ф8 «Графитовый интерьер», утверждено 31.08.2026).
///
/// Три интерьера: Графит (по умолчанию), Светлая, Как в системе.
/// Выбор применяется сразу — всё приложение пересобирается новой палитрой.
class ThemeScreen extends ConsumerWidget {
  const ThemeScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final mode = ref.watch(interiorProvider);
    return Scaffold(
      backgroundColor: AppColors.bg,
      appBar: AppBar(backgroundColor: AppColors.bg, title: const Text('Тема')),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            Padding(
              padding: const EdgeInsets.only(left: 4, bottom: 12),
              child: Text(
                'Графит не слепит на улице и в темноте — '
                'карта и цифры читаются с руки.',
                style: TextStyle(
                  fontSize: 13.5,
                  height: 1.45,
                  color: AppColors.muted,
                ),
              ),
            ),
            for (final option in Interior.values) ...[
              _InteriorTile(
                option: option,
                selected: option == mode,
                onTap: () => ref.read(interiorProvider.notifier).set(option),
              ),
              const SizedBox(height: 10),
            ],
          ],
        ),
      ),
    );
  }
}

class _InteriorTile extends StatelessWidget {
  final Interior option;
  final bool selected;
  final VoidCallback onTap;

  const _InteriorTile({
    required this.option,
    required this.selected,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Material(
      color: AppColors.paper,
      borderRadius: BorderRadius.circular(AppTheme.rMd),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(AppTheme.rMd),
        child: Container(
          padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(AppTheme.rMd),
            border: Border.all(
              color: selected ? AppColors.limeDeep : AppColors.line,
              width: selected ? 1.4 : 1,
            ),
          ),
          child: Row(
            children: [
              _Swatch(option: option),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      option.label,
                      style: TextStyle(
                        fontFamily: AppTheme.fontDisplay,
                        fontSize: 15.5,
                        fontWeight: FontWeight.w700,
                        color: AppColors.ink,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      option.hint,
                      style: TextStyle(
                        fontSize: 12.5,
                        height: 1.35,
                        color: AppColors.muted,
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 10),
              if (selected)
                Container(
                  width: 26,
                  height: 26,
                  decoration: const BoxDecoration(
                    color: AppColors.lime,
                    shape: BoxShape.circle,
                  ),
                  child: const Icon(
                    CupertinoIcons.checkmark_alt,
                    size: 17,
                    color: Color(0xFF171C19),
                  ),
                )
              else
                Container(
                  width: 26,
                  height: 26,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    border: Border.all(color: AppColors.line, width: 1.4),
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }
}

/// Мини-превью интерьера: фон + «карточка» + лаймовая точка действия.
class _Swatch extends StatelessWidget {
  final Interior option;

  const _Swatch({required this.option});

  @override
  Widget build(BuildContext context) {
    final graphite = switch (option) {
      Interior.graphite => true,
      Interior.light => false,
      Interior.system =>
        MediaQuery.platformBrightnessOf(context) == Brightness.dark,
    };
    final bg = graphite ? const Color(0xFF20252B) : const Color(0xFFF0EFE9);
    final card = graphite ? const Color(0xFF2F362F) : const Color(0xFFFFFFFF);
    final line = graphite ? const Color(0xFF3A423C) : const Color(0xFFE0DED2);
    return Container(
      width: 44,
      height: 44,
      decoration: BoxDecoration(
        color: bg,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: line),
      ),
      padding: const EdgeInsets.all(7),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 18,
            height: 8,
            decoration: BoxDecoration(
              color: card,
              borderRadius: BorderRadius.circular(3),
              border: Border.all(color: line, width: .7),
            ),
          ),
          const Spacer(),
          Container(
            width: 8,
            height: 8,
            decoration: const BoxDecoration(
              color: AppColors.lime,
              shape: BoxShape.circle,
            ),
          ),
        ],
      ),
    );
  }
}
