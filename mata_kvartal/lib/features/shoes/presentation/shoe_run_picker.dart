import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../../core/theme/app_colors.dart';
import '../data/shoes_provider.dart';

/// Лист выбора кроссовок ПЕРЕД стартом забега: в каких бежим — с этой пары и
/// спишется ресурс (км). Поддерживает несколько пар + вариант «без кроссовок».
/// Возвращает true — можно стартовать; false — пользователь отменил (закрыл лист).
Future<bool> showRunShoePicker(BuildContext context, WidgetRef ref) async {
  final shoes = ref.read(shoesProvider).activeShoes;
  // Нет рабочих пар — спрашивать нечего, бежим без списания.
  if (shoes.isEmpty) {
    ref.read(shoesProvider.notifier).selectRunShoe('');
    return true;
  }
  final result = await showModalBottomSheet<bool>(
    context: context,
    backgroundColor: AppColors.bgCard,
    isScrollControlled: true,
    shape: const RoundedRectangleBorder(
      borderRadius: BorderRadius.vertical(top: Radius.circular(22)),
    ),
    builder: (ctx) {
      void pick(String? id) {
        ref.read(shoesProvider.notifier).selectRunShoe(id);
        Navigator.of(ctx).pop(true);
      }

      return SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(20, 12, 20, 16),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Center(
                child: Container(
                  width: 40, height: 4,
                  decoration: BoxDecoration(
                    color: AppColors.separator,
                    borderRadius: BorderRadius.circular(2),
                  ),
                ),
              ),
              const SizedBox(height: 16),
              Text(
                'В каких кроссовках бежишь?',
                style: Theme.of(context).textTheme.titleLarge?.copyWith(
                      fontWeight: FontWeight.w800,
                    ),
              ),
              const SizedBox(height: 4),
              Text(
                'Ресурс (км) спишется с выбранной пары',
                style: Theme.of(context).textTheme.bodySmall?.copyWith(
                      color: AppColors.textTertiary,
                    ),
              ),
              const SizedBox(height: 16),
              Flexible(
                child: SingleChildScrollView(
                  child: Column(
                    children: [
                      for (final s in shoes)
                        _ShoeOption(shoe: s, onTap: () => pick(s.id)),
                      _NoShoesOption(onTap: () => pick('')),
                    ],
                  ),
                ),
              ),
            ],
          ),
        ),
      );
    },
  );
  return result ?? false;
}

class _ShoeOption extends StatelessWidget {
  final ShoeAsset shoe;
  final VoidCallback onTap;
  const _ShoeOption({required this.shoe, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Material(
        color: AppColors.bgElevated,
        borderRadius: BorderRadius.circular(14),
        child: InkWell(
          borderRadius: BorderRadius.circular(14),
          onTap: onTap,
          child: Padding(
            padding: const EdgeInsets.all(12),
            child: Row(
              children: [
                ClipRRect(
                  borderRadius: BorderRadius.circular(10),
                  child: Container(
                    width: 48, height: 48,
                    color: AppColors.bgCard,
                    child: shoe.imageUrl.isNotEmpty
                        ? Image.network(
                            shoe.imageUrl,
                            fit: BoxFit.cover,
                            errorBuilder: (_, __, ___) => Icon(
                              Icons.directions_run,
                              color: AppColors.textTertiary,
                            ),
                          )
                        : Icon(Icons.directions_run,
                            color: AppColors.textTertiary),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        shoe.model,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: Theme.of(context).textTheme.bodyLarge?.copyWith(
                              fontWeight: FontWeight.w700,
                            ),
                      ),
                      const SizedBox(height: 4),
                      Text(
                        'Осталось ${shoe.remainingKm.toStringAsFixed(0)} из '
                        '${shoe.maxKm.toStringAsFixed(0)} км',
                        style: Theme.of(context).textTheme.bodySmall?.copyWith(
                              color: AppColors.textSecondary,
                            ),
                      ),
                      const SizedBox(height: 6),
                      ClipRRect(
                        borderRadius: BorderRadius.circular(4),
                        child: LinearProgressIndicator(
                          value: shoe.maxKm > 0
                              ? (shoe.remainingKm / shoe.maxKm).clamp(0.0, 1.0)
                              : 0,
                          minHeight: 5,
                          backgroundColor: AppColors.bgCard,
                          valueColor: AlwaysStoppedAnimation(
                            shoe.wearPercent >= 85
                                ? AppColors.error
                                : AppColors.electricBlue,
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(width: 8),
                Icon(Icons.chevron_right, color: AppColors.textTertiary),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _NoShoesOption extends StatelessWidget {
  final VoidCallback onTap;
  const _NoShoesOption({required this.onTap});

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(14),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 14, horizontal: 12),
          child: Row(
            children: [
              Icon(Icons.block, size: 20, color: AppColors.textTertiary),
              const SizedBox(width: 12),
              Expanded(
                child: Text(
                  'Без кроссовок (не списывать ресурс)',
                  style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                        color: AppColors.textSecondary,
                      ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
