import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../../core/theme/app_colors.dart';
import '../../data/shoes_provider.dart';

/// Трекер износа кроссовок: купленные в Store пары и остаток их ресурса.
/// Перед добавлением в трекер у пользователя спрашиваем подтверждение (мог купить
/// в подарок / не для бега). Километраж убавляется автоматически после пробежек.
class ShoesScreen extends ConsumerStatefulWidget {
  const ShoesScreen({super.key});

  @override
  ConsumerState<ShoesScreen> createState() => _ShoesScreenState();
}

class _ShoesScreenState extends ConsumerState<ShoesScreen> {
  @override
  void initState() {
    super.initState();
    // Только обновляем список. Всплывающее окно про новые покупки показывается
    // глобально при открытии приложения (MainScaffold), а не здесь.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      ref.read(shoesProvider.notifier).refresh();
    });
  }

  @override
  Widget build(BuildContext context) {
    final st = ref.watch(shoesProvider);
    final empty = st.shoes.isEmpty && st.pending.isEmpty;

    return Scaffold(
      backgroundColor: AppColors.bgDark,
      appBar: AppBar(
        backgroundColor: AppColors.bgDark,
        title: const Text('Мои кроссовки'),
      ),
      body: SafeArea(
        child: RefreshIndicator(
          onRefresh: () => ref.read(shoesProvider.notifier).refresh(),
          color: AppColors.electricBlue,
          backgroundColor: AppColors.bgCard,
          child: empty
              ? _Empty(loading: st.isLoading && !st.loaded)
              : ListView(
                  physics: const AlwaysScrollableScrollPhysics(),
                  padding: const EdgeInsets.all(16),
                  children: [
                    if (st.pending.isNotEmpty) ...[
                      _SectionTitle('Новые покупки — добавить?'),
                      const SizedBox(height: 10),
                      for (final s in st.pending) ...[
                        _PendingTile(
                          shoe: s,
                          onDecide: (add) async {
                            final ok = await ref
                                .read(shoesProvider.notifier)
                                .confirm(shoeId: s.id, add: add);
                            if (!ok && context.mounted) {
                              ScaffoldMessenger.of(context).showSnackBar(
                                const SnackBar(
                                    content: Text('Нет связи — попробуйте позже')),
                              );
                            }
                          },
                        ),
                        const SizedBox(height: 12),
                      ],
                      const SizedBox(height: 8),
                    ],
                    if (st.shoes.isNotEmpty) ...[
                      _SectionTitle('Трекер износа'),
                      const SizedBox(height: 10),
                      for (final s in st.shoes) ...[
                        _ShoeTile(shoe: s),
                        const SizedBox(height: 12),
                      ],
                    ],
                  ],
                ),
        ),
      ),
    );
  }
}

class _SectionTitle extends StatelessWidget {
  final String text;
  const _SectionTitle(this.text);

  @override
  Widget build(BuildContext context) => Text(
        text,
        style: Theme.of(context)
            .textTheme
            .titleMedium
            ?.copyWith(fontWeight: FontWeight.w700),
      );
}

class _Empty extends StatelessWidget {
  final bool loading;
  const _Empty({required this.loading});

  @override
  Widget build(BuildContext context) {
    return ListView(
      physics: const AlwaysScrollableScrollPhysics(),
      children: [
        const SizedBox(height: 120),
        Icon(
          loading ? CupertinoIcons.clock : Icons.directions_run,
          size: 56,
          color: AppColors.textDisabled,
        ),
        const SizedBox(height: 16),
        Center(
          child: Text(
            loading ? 'Загрузка…' : 'Пока нет кроссовок',
            style: Theme.of(context).textTheme.titleMedium?.copyWith(
                  color: AppColors.textSecondary,
                  fontWeight: FontWeight.w700,
                ),
          ),
        ),
        if (!loading) ...[
          const SizedBox(height: 8),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 40),
            child: Text(
              'Купи кроссовки в МАТА Store — мы спросим, добавить ли их '
              'в трекер, и будем считать пробег и износ.',
              textAlign: TextAlign.center,
              style: Theme.of(context)
                  .textTheme
                  .bodyMedium
                  ?.copyWith(color: AppColors.textTertiary),
            ),
          ),
        ],
      ],
    );
  }
}

/// Карточка купленной, но не подтверждённой пары: фото + кнопки решения.
class _PendingTile extends StatelessWidget {
  final ShoeAsset shoe;
  final void Function(bool add) onDecide;
  const _PendingTile({required this.shoe, required this.onDecide});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: AppColors.bgCard,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(
          color: AppColors.electricBlue.withValues(alpha: 0.45),
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              _ShoeImage(url: shoe.imageUrl),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      shoe.model,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(context).textTheme.titleSmall?.copyWith(
                            color: AppColors.textPrimary,
                            fontWeight: FontWeight.w700,
                          ),
                    ),
                    const SizedBox(height: 3),
                    Text(
                      'Новая покупка · добавить в приложение?',
                      style: Theme.of(context)
                          .textTheme
                          .bodySmall
                          ?.copyWith(color: AppColors.textTertiary),
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              Expanded(
                child: OutlinedButton(
                  onPressed: () => onDecide(false),
                  style: OutlinedButton.styleFrom(
                    foregroundColor: AppColors.textSecondary,
                    side: BorderSide(color: AppColors.separator),
                  ),
                  child: const Text('Нет'),
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: FilledButton(
                  onPressed: () => onDecide(true),
                  child: const Text('Да'),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _ShoeTile extends ConsumerWidget {
  final ShoeAsset shoe;
  const _ShoeTile({required this.shoe});

  Color get _accent {
    if (shoe.retired || shoe.wearPercent >= 90) return AppColors.error;
    if (shoe.wearPercent >= 70) return AppColors.warning;
    return AppColors.electricBlue;
  }

  Future<void> _confirmDelete(BuildContext context, WidgetRef ref) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: AppColors.bgCard,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
        title: const Text('Удалить кроссовки?'),
        content: Text(
          'Убрать «${shoe.model}» из приложения?',
          style: TextStyle(color: AppColors.textSecondary),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(false),
            child: Text('Отмена',
                style: TextStyle(color: AppColors.textSecondary)),
          ),
          FilledButton(
            onPressed: () => Navigator.of(ctx).pop(true),
            style: FilledButton.styleFrom(backgroundColor: AppColors.error),
            child: const Text('Удалить'),
          ),
        ],
      ),
    );
    if (ok != true) return;
    final done = await ref.read(shoesProvider.notifier).delete(shoe.id);
    if (!done && context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Не удалось удалить — попробуйте позже')),
      );
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final accent = _accent;
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: AppColors.bgCard,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(
          color: shoe.retired
              ? AppColors.error.withValues(alpha: 0.4)
              : AppColors.separator,
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              _ShoeImage(url: shoe.imageUrl),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      shoe.model,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(context).textTheme.titleSmall?.copyWith(
                            color: AppColors.textPrimary,
                            fontWeight: FontWeight.w700,
                          ),
                    ),
                    const SizedBox(height: 3),
                    Text(
                      shoe.retired
                          ? 'Ресурс исчерпан · ${shoe.totalKm.toStringAsFixed(0)} км'
                          : 'Осталось ${shoe.remainingKm.toStringAsFixed(0)} из ${shoe.maxKm.toStringAsFixed(0)} км',
                      style: Theme.of(context).textTheme.bodySmall?.copyWith(
                            color: AppColors.textTertiary,
                          ),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 8),
              shoe.retired
                  ? _Badge(text: 'Заменить', color: AppColors.error)
                  : Text(
                      '${shoe.wearPercent}%',
                      style: TextStyle(
                        color: accent,
                        fontWeight: FontWeight.w900,
                        fontSize: 16,
                      ),
                    ),
              // Корзина — удалить пару из приложения.
              IconButton(
                tooltip: 'Удалить',
                visualDensity: VisualDensity.compact,
                padding: const EdgeInsets.only(left: 6),
                constraints: const BoxConstraints(),
                icon: Icon(CupertinoIcons.trash,
                    size: 18, color: AppColors.textTertiary),
                onPressed: () => _confirmDelete(context, ref),
              ),
            ],
          ),
          const SizedBox(height: 12),
          ClipRRect(
            borderRadius: BorderRadius.circular(6),
            child: LinearProgressIndicator(
              value: (shoe.wearPercent / 100).clamp(0.0, 1.0),
              minHeight: 7,
              backgroundColor: AppColors.bgElevated,
              valueColor: AlwaysStoppedAnimation<Color>(accent),
            ),
          ),
        ],
      ),
    );
  }
}

class _ShoeImage extends StatelessWidget {
  final String url;
  static const double size = 54;
  const _ShoeImage({required this.url});

  @override
  Widget build(BuildContext context) {
    final placeholder = Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        color: AppColors.electricBlue.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Icon(
        Icons.directions_run,
        color: AppColors.electricBlue,
        size: size * 0.48,
      ),
    );
    if (!url.startsWith('http')) return placeholder;
    return ClipRRect(
      borderRadius: BorderRadius.circular(12),
      child: Image.network(
        url,
        width: size,
        height: size,
        fit: BoxFit.cover,
        errorBuilder: (_, __, ___) => placeholder,
      ),
    );
  }
}

class _Badge extends StatelessWidget {
  final String text;
  final Color color;
  const _Badge({required this.text, required this.color});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.15),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Text(
        text,
        style: TextStyle(
          color: color,
          fontWeight: FontWeight.w800,
          fontSize: 12,
        ),
      ),
    );
  }
}
