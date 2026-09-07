import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/theme/app_colors.dart';
import '../data/shoes_provider.dart';

/// Спрашиваем по каждой купленной паре: «Добавить кроссовки в приложение?» (Да/Нет).
/// Вызывается при открытии приложения (из MainScaffold), а не только на экране кроссовок.
Future<void> promptPendingShoes(BuildContext context, WidgetRef ref) async {
  final pending = [...ref.read(shoesProvider).pending];
  for (final shoe in pending) {
    if (!context.mounted) break;
    final add = await showAddShoeDialog(context, shoe);
    if (add == null) break; // закрыл без ответа — спросим в следующий раз
    final ok =
        await ref.read(shoesProvider.notifier).confirm(shoeId: shoe.id, add: add);
    if (!ok && context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Нет связи — попробуйте позже')),
      );
      break;
    }
  }
}

/// Диалог «Добавить кроссовки в приложение?» с фото и мягкой анимацией появления
/// (масштаб + затухание). true=Да, false=Нет, null=закрыл.
Future<bool?> showAddShoeDialog(BuildContext context, ShoeAsset shoe) {
  return showGeneralDialog<bool>(
    context: context,
    barrierDismissible: true,
    barrierLabel: MaterialLocalizations.of(context).modalBarrierDismissLabel,
    barrierColor: Colors.black.withValues(alpha: 0.55),
    transitionDuration: const Duration(milliseconds: 240),
    pageBuilder: (ctx, _, __) => _AddShoeDialog(shoe: shoe),
    transitionBuilder: (ctx, anim, _, child) {
      final curved = CurvedAnimation(parent: anim, curve: Curves.easeOutBack);
      return FadeTransition(
        opacity: anim,
        child: ScaleTransition(
          scale: Tween<double>(begin: 0.9, end: 1.0).animate(curved),
          child: child,
        ),
      );
    },
  );
}

class _AddShoeDialog extends StatelessWidget {
  final ShoeAsset shoe;
  const _AddShoeDialog({required this.shoe});

  @override
  Widget build(BuildContext context) {
    return Dialog(
      backgroundColor: AppColors.bgCard,
      insetPadding: const EdgeInsets.symmetric(horizontal: 44, vertical: 24),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(24),
        side: BorderSide(color: AppColors.electricBlue.withValues(alpha: 0.25)),
      ),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(22, 24, 22, 18),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            _PromptImage(url: shoe.imageUrl),
            const SizedBox(height: 14),
            Text(
              'Добавить кроссовки?',
              textAlign: TextAlign.center,
              style: TextStyle(
                color: AppColors.textPrimary,
                fontSize: 18,
                fontWeight: FontWeight.w800,
              ),
            ),
            const SizedBox(height: 6),
            Text(
              shoe.model,
              textAlign: TextAlign.center,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(
                color: AppColors.textSecondary,
                fontSize: 14,
                fontWeight: FontWeight.w600,
              ),
            ),
            const SizedBox(height: 18),
            // Кнопки: маленькие, минималистичные (пилюли), по центру.
            Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                _MiniButton(
                  label: 'Нет',
                  primary: false,
                  onTap: () => Navigator.of(context).pop(false),
                ),
                const SizedBox(width: 12),
                _MiniButton(
                  label: 'Да',
                  primary: true,
                  onTap: () => Navigator.of(context).pop(true),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

/// Компактная кнопка-пилюля для диалога.
class _MiniButton extends StatelessWidget {
  final String label;
  final bool primary;
  final VoidCallback onTap;
  const _MiniButton({
    required this.label,
    required this.primary,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: 100,
      height: 42,
      child: primary
          ? FilledButton(
              onPressed: onTap,
              style: FilledButton.styleFrom(
                padding: EdgeInsets.zero,
                shape: const StadiumBorder(),
              ),
              child: Text(label,
                  style: const TextStyle(
                      fontSize: 15, fontWeight: FontWeight.w700)),
            )
          : OutlinedButton(
              onPressed: onTap,
              style: OutlinedButton.styleFrom(
                padding: EdgeInsets.zero,
                shape: const StadiumBorder(),
                foregroundColor: AppColors.textSecondary,
                side: BorderSide(color: AppColors.separator),
              ),
              child: Text(label,
                  style: const TextStyle(
                      fontSize: 15, fontWeight: FontWeight.w600)),
            ),
    );
  }
}

class _PromptImage extends StatelessWidget {
  final String url;
  const _PromptImage({required this.url});

  @override
  Widget build(BuildContext context) {
    final resolved = url;
    const size = 88.0;
    final placeholder = Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        color: AppColors.electricBlue.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(16),
      ),
      child: Icon(Icons.directions_run,
          color: AppColors.electricBlue, size: 40),
    );
    if (!resolved.startsWith('http')) return placeholder;
    return ClipRRect(
      borderRadius: BorderRadius.circular(16),
      child: Image.network(
        resolved,
        width: size,
        height: size,
        fit: BoxFit.cover,
        errorBuilder: (_, __, ___) => placeholder,
      ),
    );
  }
}
