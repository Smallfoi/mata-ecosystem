import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../../core/theme/app_colors.dart';
import '../../data/notifications_provider.dart';

/// Лента уведомлений: клубные события (заявки/одобрения) и события аккаунта.
class NotificationsScreen extends ConsumerStatefulWidget {
  const NotificationsScreen({super.key});

  @override
  ConsumerState<NotificationsScreen> createState() =>
      _NotificationsScreenState();
}

class _NotificationsScreenState extends ConsumerState<NotificationsScreen> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      await ref.read(notificationsProvider.notifier).refresh();
      // Открыли ленту → помечаем прочитанными.
      await ref.read(notificationsProvider.notifier).markAllRead();
    });
  }

  @override
  Widget build(BuildContext context) {
    final st = ref.watch(notificationsProvider);

    return Scaffold(
      backgroundColor: AppColors.bgDark,
      appBar: AppBar(
        backgroundColor: AppColors.bgDark,
        title: const Text('Уведомления'),
      ),
      body: SafeArea(
        child: RefreshIndicator(
          onRefresh: () => ref.read(notificationsProvider.notifier).refresh(),
          color: AppColors.electricBlue,
          backgroundColor: AppColors.bgCard,
          child: st.items.isEmpty
              ? _Empty(loading: st.isLoading && !st.loaded)
              : ListView.separated(
                  physics: const AlwaysScrollableScrollPhysics(),
                  padding: const EdgeInsets.all(16),
                  itemCount: st.items.length,
                  separatorBuilder: (_, __) => const SizedBox(height: 10),
                  itemBuilder: (_, i) => _NotifTile(item: st.items[i]),
                ),
        ),
      ),
    );
  }
}

class _Empty extends StatelessWidget {
  final bool loading;
  const _Empty({required this.loading});

  @override
  Widget build(BuildContext context) {
    return ListView(
      physics: const AlwaysScrollableScrollPhysics(),
      children: [
        const SizedBox(height: 130),
        Icon(loading ? CupertinoIcons.clock : CupertinoIcons.bell,
            size: 54, color: AppColors.textDisabled),
        const SizedBox(height: 16),
        Center(
          child: Text(
            loading ? 'Загрузка…' : 'Пока нет уведомлений',
            style: Theme.of(context).textTheme.titleMedium?.copyWith(
                  color: AppColors.textSecondary,
                  fontWeight: FontWeight.w700,
                ),
          ),
        ),
      ],
    );
  }
}

({IconData icon, Color color}) _meta(String type, String title) {
  // Разбор забега (анти-чит): три исхода, по которым бегун должен понять, что
  // с его баллами — ждём, начислили или не засчитали.
  if (title.startsWith('Забег на проверке')) {
    return (icon: CupertinoIcons.clock_fill, color: AppColors.warning);
  }
  if (title.startsWith('Забег подтверждён')) {
    return (icon: CupertinoIcons.checkmark_seal_fill, color: AppColors.success);
  }
  if (title.startsWith('Забег не засчитан')) {
    return (icon: CupertinoIcons.exclamationmark_triangle_fill, color: AppColors.error);
  }
  if (type == 'level' || title.contains('ровень')) {
    return (icon: CupertinoIcons.star_fill, color: AppColors.warning);
  }
  if (title.contains('одобрена')) {
    return (icon: CupertinoIcons.checkmark_seal_fill, color: AppColors.success);
  }
  if (title.contains('отклонена')) {
    return (icon: CupertinoIcons.xmark_seal_fill, color: AppColors.error);
  }
  if (title.contains('заявка') || title.contains('Заявка') || title.contains('клуб')) {
    return (icon: CupertinoIcons.person_2_fill, color: AppColors.electricBlue);
  }
  if (title.contains('Заказ')) {
    return (icon: CupertinoIcons.bag_fill, color: AppColors.warning);
  }
  return (icon: CupertinoIcons.bell_fill, color: AppColors.textSecondary);
}

String _ago(DateTime? dt) {
  if (dt == null) return '';
  final d = DateTime.now().difference(dt.toLocal());
  if (d.inMinutes < 1) return 'только что';
  if (d.inMinutes < 60) return '${d.inMinutes} мин назад';
  if (d.inHours < 24) return '${d.inHours} ч назад';
  return '${d.inDays} дн назад';
}

class _NotifTile extends StatelessWidget {
  final NotificationItem item;
  const _NotifTile({required this.item});

  @override
  Widget build(BuildContext context) {
    final m = _meta(item.type, item.title);
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: AppColors.bgCard,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(
          color: item.read
              ? AppColors.separator
              : AppColors.electricBlue.withValues(alpha: 0.4),
        ),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 40,
            height: 40,
            decoration: BoxDecoration(
              color: m.color.withValues(alpha: 0.14),
              shape: BoxShape.circle,
            ),
            child: Icon(m.icon, size: 20, color: m.color),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  item.title,
                  style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                        color: AppColors.textPrimary,
                        fontWeight: FontWeight.w700,
                      ),
                ),
                if (item.body.isNotEmpty) ...[
                  const SizedBox(height: 2),
                  Text(
                    item.body,
                    style: Theme.of(context).textTheme.bodySmall?.copyWith(
                          color: AppColors.textSecondary,
                        ),
                  ),
                ],
                const SizedBox(height: 4),
                Text(
                  _ago(item.createdAt),
                  style: Theme.of(context).textTheme.labelSmall?.copyWith(
                        color: AppColors.textTertiary,
                      ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
