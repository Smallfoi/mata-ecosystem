import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';
import '../../models/app_notification.dart';
import '../../providers/notifications_provider.dart';
import '../../providers/order_provider.dart';
import '../../theme/app_theme.dart';
import '../../widgets/remote_text.dart';
import '../profile/order_detail_screen.dart';

class NotificationsScreen extends StatefulWidget {
  const NotificationsScreen({super.key});

  @override
  State<NotificationsScreen> createState() => _NotificationsScreenState();
}

class _NotificationsScreenState extends State<NotificationsScreen> {
  @override
  void initState() {
    super.initState();
    // Помечаем все прочитанными при открытии экрана.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<NotificationsProvider>().markAllRead();
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.white,
      appBar: AppBar(
        leading: IconButton(
          onPressed: () => context.pop(),
          icon: const Icon(Icons.arrow_back, size: 22),
        ),
        title: RemoteText(
          'app.notif.title',
          'УВЕДОМЛЕНИЯ',
          style: TextStyle(
            fontSize: 20,
            fontWeight: FontWeight.w700,
            letterSpacing: 3,
          ),
        ),
        actions: [
          Consumer<NotificationsProvider>(
            builder: (context, notif, _) {
              if (notif.items.isEmpty) return const SizedBox.shrink();
              return TextButton(
                onPressed: () => _confirmClear(context, notif),
                child: const RemoteText(
                  'app.notif.clear',
                  'Очистить',
                  style: TextStyle(color: AppColors.grey600, fontSize: 13),
                ),
              );
            },
          ),
        ],
      ),
      body: Consumer<NotificationsProvider>(
        builder: (context, notif, _) {
          if (notif.items.isEmpty) return const _EmptyNotifications();
          return ListView.separated(
            padding: const EdgeInsets.symmetric(vertical: 8),
            itemCount: notif.items.length,
            separatorBuilder: (_, __) => const Divider(height: 1),
            itemBuilder: (context, i) {
              final n = notif.items[i];
              return _NotificationTile(notification: n)
                  .animate(delay: (i * 40).ms)
                  .fadeIn(duration: 300.ms)
                  .slideX(begin: 0.05, curve: Curves.easeOut);
            },
          );
        },
      ),
    );
  }

  void _confirmClear(BuildContext context, NotificationsProvider notif) {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        shape: const RoundedRectangleBorder(borderRadius: BorderRadius.zero),
        title: const RemoteText(
            'app.notif.clearDialog.title', 'Очистить уведомления?'),
        content: const RemoteText(
            'app.notif.clearDialog.body', 'Все уведомления будут удалены'),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(),
            child: const RemoteText('app.notif.clearDialog.cancel', 'Отмена',
                style: TextStyle(color: AppColors.grey600)),
          ),
          TextButton(
            onPressed: () {
              Navigator.of(ctx).pop();
              notif.clear();
            },
            child: const RemoteText('app.notif.clearDialog.confirm', 'Очистить',
                style: TextStyle(color: AppColors.red)),
          ),
        ],
      ),
    );
  }
}

class _NotificationTile extends StatelessWidget {
  final AppNotification notification;
  const _NotificationTile({required this.notification});

  IconData get _icon {
    switch (notification.type) {
      case NotifType.order:
        return Icons.local_shipping_outlined;
      case NotifType.promo:
        return Icons.percent;
      case NotifType.system:
        return Icons.info_outline;
    }
  }

  void _onTap(BuildContext context) {
    if (notification.orderId == null) return;
    final order =
        context.read<OrderProvider>().findById(notification.orderId!);
    if (order == null) return;
    Navigator.of(context).push(
      PageRouteBuilder(
        pageBuilder: (_, a, b) => OrderDetailScreen(order: order),
        transitionsBuilder: (_, a, b, child) => SlideTransition(
          position: Tween<Offset>(
            begin: const Offset(1, 0),
            end: Offset.zero,
          ).animate(CurvedAnimation(parent: a, curve: Curves.easeOutCubic)),
          child: child,
        ),
        transitionDuration: const Duration(milliseconds: 320),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: notification.orderId != null ? () => _onTap(context) : null,
      child: Container(
        color: notification.read ? AppColors.white : const Color(0xFFF7F7F7),
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Icon
            Container(
              width: 40,
              height: 40,
              decoration: const BoxDecoration(
                color: AppColors.black,
                shape: BoxShape.circle,
              ),
              child: Icon(_icon, size: 18, color: Colors.white),
            ),
            const SizedBox(width: 14),
            // Content
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Expanded(
                        child: Text(
                          notification.title,
                          style: TextStyle(
                            fontSize: 14,
                            fontWeight: notification.read
                                ? FontWeight.w600
                                : FontWeight.w700,
                            color: AppColors.black,
                          ),
                        ),
                      ),
                      if (!notification.read)
                        Container(
                          width: 8,
                          height: 8,
                          margin: const EdgeInsets.only(left: 8, top: 4),
                          decoration: const BoxDecoration(
                            color: AppColors.black,
                            shape: BoxShape.circle,
                          ),
                        ),
                    ],
                  ),
                  const SizedBox(height: 4),
                  Text(
                    notification.body,
                    style: const TextStyle(
                      fontSize: 13,
                      color: AppColors.grey600,
                      height: 1.4,
                    ),
                  ),
                  const SizedBox(height: 6),
                  Text(
                    _timeAgo(notification.createdAt),
                    style: const TextStyle(
                      fontSize: 11,
                      color: AppColors.grey500,
                    ),
                  ),
                ],
              ),
            ),
            if (notification.orderId != null)
              const Padding(
                padding: EdgeInsets.only(left: 4, top: 2),
                child: Icon(Icons.chevron_right,
                    size: 18, color: AppColors.grey400),
              ),
          ],
        ),
      ),
    );
  }

  String _timeAgo(DateTime dt) {
    final diff = DateTime.now().difference(dt);
    if (diff.inSeconds < 60) return 'только что';
    if (diff.inMinutes < 60) return '${diff.inMinutes} мин назад';
    if (diff.inHours < 24) return '${diff.inHours} ч назад';
    if (diff.inDays < 7) return '${diff.inDays} дн назад';
    return '${dt.day.toString().padLeft(2, '0')}.'
        '${dt.month.toString().padLeft(2, '0')}.${dt.year}';
  }
}

class _EmptyNotifications extends StatelessWidget {
  const _EmptyNotifications();

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: const [
          Icon(Icons.notifications_none, size: 56, color: AppColors.grey200),
          SizedBox(height: 12),
          RemoteText(
            'app.notif.empty.title',
            'Нет уведомлений',
            style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
          ),
          SizedBox(height: 4),
          RemoteText(
            'app.notif.empty.subtitle',
            'Здесь появятся обновления по заказам',
            style: TextStyle(fontSize: 13, color: AppColors.grey600),
          ),
        ],
      ),
    );
  }
}
