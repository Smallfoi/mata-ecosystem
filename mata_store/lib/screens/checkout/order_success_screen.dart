import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';
import '../../models/order.dart';
import '../../providers/order_provider.dart';
import '../../theme/app_theme.dart';
import '../../widgets/remote_text.dart';
import '../profile/order_detail_screen.dart';

class OrderSuccessScreen extends StatelessWidget {
  final String orderId;
  const OrderSuccessScreen({super.key, required this.orderId});

  @override
  Widget build(BuildContext context) {
    final order = context.read<OrderProvider>().findById(orderId);

    return Scaffold(
      backgroundColor: AppColors.white,
      body: SafeArea(
        child: LayoutBuilder(
          builder: (context, constraints) => SingleChildScrollView(
            child: ConstrainedBox(
              constraints: BoxConstraints(minHeight: constraints.maxHeight),
              child: IntrinsicHeight(
                child: Padding(
                  padding: const EdgeInsets.all(24),
                  child: Column(
                    children: [
                      const Spacer(),

                      // Icon
                      Container(
                            width: 88,
                            height: 88,
                            color: AppColors.grey100,
                            child: const Icon(
                              Icons.check,
                              size: 44,
                              color: AppColors.black,
                            ),
                          )
                          .animate()
                          .scale(duration: 600.ms, curve: Curves.elasticOut)
                          .fadeIn(duration: 300.ms),

                      const SizedBox(height: 32),

                      RemoteText(
                        'app.ordersuccess.title',
                        'ЗАКАЗ ОФОРМЛЕН!',
                        style: TextStyle(
                          fontSize: 26,
                          fontWeight: FontWeight.w700,
                          letterSpacing: 2,
                          color: AppColors.black,
                        ),
                      ).animate().fadeIn(duration: 400.ms, delay: 200.ms),

                      const SizedBox(height: 12),

                      if (order != null) ...[
                        Text(
                          'Заказ №${order.id}',
                          style: TextStyle(
                            fontSize: 16,
                            fontWeight: FontWeight.w500,
                            color: AppColors.grey600,
                            letterSpacing: 1,
                          ),
                        ).animate().fadeIn(duration: 400.ms, delay: 300.ms),
                        const SizedBox(height: 24),
                        _InfoCard(order: order)
                            .animate()
                            .fadeIn(duration: 400.ms, delay: 400.ms)
                            .slideY(begin: 0.1),
                      ] else
                        const RemoteText(
                          'app.ordersuccess.subtitle',
                          'Ваш заказ принят в обработку',
                          style: TextStyle(
                            fontSize: 14,
                            color: AppColors.grey600,
                            height: 1.5,
                          ),
                        ).animate().fadeIn(duration: 400.ms, delay: 300.ms),

                      const Spacer(),

                      if (order != null) ...[
                        GestureDetector(
                              onTap: () => Navigator.of(context).push(
                                PageRouteBuilder(
                                  pageBuilder: (_, a, b) =>
                                      OrderDetailScreen(order: order),
                                  transitionsBuilder: (_, a, b, child) =>
                                      SlideTransition(
                                        position:
                                            Tween<Offset>(
                                              begin: const Offset(1, 0),
                                              end: Offset.zero,
                                            ).animate(
                                              CurvedAnimation(
                                                parent: a,
                                                curve: Curves.easeOutCubic,
                                              ),
                                            ),
                                        child: child,
                                      ),
                                  transitionDuration: const Duration(
                                    milliseconds: 320,
                                  ),
                                ),
                              ),
                              child: Container(
                                height: 52,
                                color: AppColors.black,
                                alignment: Alignment.center,
                                child: RemoteText(
                                  'app.ordersuccess.detailsTitle',
                                  'ДЕТАЛИ ЗАКАЗА',
                                  style: TextStyle(
                                    fontSize: 15,
                                    fontWeight: FontWeight.w600,
                                    color: Colors.white,
                                    letterSpacing: 2,
                                  ),
                                ),
                              ),
                            )
                            .animate()
                            .fadeIn(duration: 400.ms, delay: 500.ms)
                            .slideY(begin: 0.1),
                        const SizedBox(height: 12),
                      ],

                      // Buttons
                      GestureDetector(
                            onTap: () => context.go('/profile'),
                            child: Container(
                              height: 52,
                              // ВАЖНО: цвет — ВНУТРИ decoration. Нельзя задавать
                              // Container(color:) и Container(decoration:) вместе
                              // (assert «color == null || decoration == null»),
                              // а при order != null decoration был не-null → краш
                              // на экране «Заказ оформлен».
                              decoration: BoxDecoration(
                                color: order == null
                                    ? AppColors.black
                                    : AppColors.white,
                                border: order == null
                                    ? null
                                    : Border.all(color: AppColors.grey200),
                              ),
                              alignment: Alignment.center,
                              child: RemoteText(
                                'app.ordersuccess.myOrders',
                                'МОИ ЗАКАЗЫ',
                                style: TextStyle(
                                  fontSize: 15,
                                  fontWeight: FontWeight.w600,
                                  color: order == null
                                      ? Colors.white
                                      : AppColors.black,
                                  letterSpacing: 2,
                                ),
                              ),
                            ),
                          )
                          .animate()
                          .fadeIn(
                            duration: 400.ms,
                            delay: order == null ? 500.ms : 580.ms,
                          )
                          .slideY(begin: 0.1),

                      const SizedBox(height: 12),

                      GestureDetector(
                            onTap: () => context.go('/'),
                            child: Container(
                              height: 52,
                              decoration: BoxDecoration(
                                border: Border.all(color: AppColors.grey200),
                              ),
                              alignment: Alignment.center,
                              child: RemoteText(
                                'app.ordersuccess.toHome',
                                'НА ГЛАВНУЮ',
                                style: TextStyle(
                                  fontSize: 15,
                                  fontWeight: FontWeight.w500,
                                  color: AppColors.black,
                                  letterSpacing: 2,
                                ),
                              ),
                            ),
                          )
                          .animate()
                          .fadeIn(duration: 400.ms, delay: 580.ms)
                          .slideY(begin: 0.1),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _InfoCard extends StatelessWidget {
  final Order order;
  const _InfoCard({required this.order});

  @override
  Widget build(BuildContext context) {
    final data = order.checkoutData;
    final deliveryLine = data.deliveryType == DeliveryType.pickup
        ? 'г. Москва, ул. Спортивная, 5'
        : [
            data.city,
            data.street,
            data.house,
          ].where((s) => s != null && s.isNotEmpty).join(', ');

    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(border: Border.all(color: AppColors.grey200)),
      child: Column(
        children: [
          _Row(
            label: 'Сумма заказа',
            labelKey: 'app.ordersuccess.sumLabel',
            value: '${order.total.toInt()} ₽',
          ),
          const Divider(height: 20),
          _Row(
            label: 'Доставка',
            labelKey: 'app.ordersuccess.deliveryLabel',
            value: OrderProvider.deliveryLabel(data.deliveryType),
          ),
          const SizedBox(height: 4),
          _Row(
            label: '',
            value: deliveryLine,
            small: true,
            valueColor: AppColors.grey600,
          ),
          const Divider(height: 20),
          _Row(
            label: 'Оплата',
            labelKey: 'app.ordersuccess.paymentLabel',
            value: OrderProvider.paymentLabel(data.paymentType),
          ),
          const Divider(height: 20),
          _Row(
            label: 'Статус',
            labelKey: 'app.ordersuccess.statusLabel',
            value: OrderProvider.statusLabel(order.status),
            valueColor: AppColors.black,
          ),
        ],
      ),
    );
  }
}

class _Row extends StatelessWidget {
  final String label;
  final String? labelKey;
  final String value;
  final bool small;
  final Color? valueColor;

  const _Row({
    required this.label,
    this.labelKey,
    required this.value,
    this.small = false,
    this.valueColor,
  });

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        if (label.isNotEmpty)
          SizedBox(
            width: 110,
            child: labelKey == null
                ? Text(
                    label,
                    style: const TextStyle(fontSize: 14, color: AppColors.grey600),
                  )
                : RemoteText(
                    labelKey!,
                    label,
                    style: const TextStyle(fontSize: 14, color: AppColors.grey600),
                  ),
          ),
        Expanded(
          child: Text(
            value,
            textAlign: label.isEmpty ? TextAlign.start : TextAlign.end,
            style: TextStyle(
              fontSize: small ? 12 : 13,
              fontWeight: small ? FontWeight.w400 : FontWeight.w600,
              color: valueColor ?? AppColors.black,
            ),
          ),
        ),
      ],
    );
  }
}
