import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';
import '../../models/order.dart';
import '../../providers/order_provider.dart';
import '../../theme/app_theme.dart';
import '../../widgets/product_image.dart';
import '../../widgets/remote_text.dart';
import 'return_request_screen.dart';

class OrderDetailScreen extends StatelessWidget {
  final Order order;
  const OrderDetailScreen({super.key, required this.order});

  @override
  Widget build(BuildContext context) {
    final data = order.checkoutData;

    return Scaffold(
      backgroundColor: AppColors.white,
      body: Column(
        children: [
          _Header(order: order, onClose: () => Navigator.of(context).pop()),
          Expanded(
            child: SingleChildScrollView(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  // ── Status bar ────────────────────────────────────────────
                  _StatusBar(status: order.status),

                  // ── Items ─────────────────────────────────────────────────
                  _Section(
                    title: 'Товары (${order.items.length})',
                    child: Column(
                      children: order.items
                          .asMap()
                          .entries
                          .map((e) => _ItemRow(
                                item: e.value,
                                isLast:
                                    e.key == order.items.length - 1,
                              )
                                  .animate(delay: (e.key * 60).ms)
                                  .fadeIn(duration: 300.ms)
                                  .slideX(begin: 0.05))
                          .toList(),
                    ),
                  ),

                  const _Divider(),

                  // ── Delivery ──────────────────────────────────────────────
                  _Section(
                    contentKey: 'app.orderdetail.section_delivery',
                    title: 'Доставка',
                    child: Column(
                      children: [
                        _InfoRow(
                          icon: Icons.local_shipping_outlined,
                          label: OrderProvider.deliveryLabel(
                              data.deliveryType),
                          value: _deliveryCostText,
                        ),
                        if (data.deliveryType != DeliveryType.pickup &&
                            data.city != null) ...[
                          const SizedBox(height: 10),
                          _InfoRow(
                            icon: Icons.location_on_outlined,
                            label: 'Адрес',
                            value: _addressText,
                            contentKey: 'app.orderdetail.info_address',
                          ),
                        ] else if (data.deliveryType ==
                            DeliveryType.pickup) ...[
                          const SizedBox(height: 10),
                          _InfoRow(
                            icon: Icons.store_outlined,
                            label: 'Адрес самовывоза',
                            value: 'г. Москва, ул. Спортивная, 5',
                            contentKey: 'app.orderdetail.info_pickup_address',
                          ),
                        ],
                      ],
                    ),
                  ),

                  const _Divider(),

                  // ── Contact ───────────────────────────────────────────────
                  _Section(
                    contentKey: 'app.orderdetail.section_contact',
                    title: 'Контакт',
                    child: Column(
                      children: [
                        _InfoRow(
                          icon: Icons.person_outline,
                          label: 'Получатель',
                          value: data.name,
                          contentKey: 'app.orderdetail.info_recipient',
                        ),
                        const SizedBox(height: 10),
                        _InfoRow(
                          icon: Icons.phone_outlined,
                          label: 'Телефон',
                          value: data.phone,
                          contentKey: 'app.orderdetail.info_phone',
                        ),
                        const SizedBox(height: 10),
                        _InfoRow(
                          icon: Icons.mail_outline,
                          label: 'Email',
                          value: data.email,
                          contentKey: 'app.orderdetail.info_email',
                        ),
                      ],
                    ),
                  ),

                  const _Divider(),

                  // ── Payment ───────────────────────────────────────────────
                  _Section(
                    contentKey: 'app.orderdetail.section_payment',
                    title: 'Оплата',
                    child: _InfoRow(
                      icon: _paymentIcon,
                      label: OrderProvider.paymentLabel(data.paymentType),
                      value: '',
                    ),
                  ),

                  const _Divider(),

                  // ── Price breakdown ───────────────────────────────────────
                  _Section(
                    contentKey: 'app.orderdetail.section_total',
                    title: 'Сумма',
                    child: Column(
                      children: [
                        _PriceRow(
                            contentKey: 'app.orderdetail.price_items',
                            label: 'Товары',
                            value: '${order.subtotal.toInt()} ₽'),
                        const SizedBox(height: 8),
                        _PriceRow(
                          contentKey: 'app.orderdetail.price_delivery',
                          label: 'Доставка',
                          value: order.deliveryCost == 0
                              ? 'Бесплатно'
                              : '${order.deliveryCost.toInt()} ₽',
                        ),
                        if (order.pointsRedeemed > 0) ...[
                          const SizedBox(height: 8),
                          _PriceRow(
                            contentKey: 'app.orderdetail.price_points',
                            label: 'Баллы',
                            value: '−${order.pointsRedeemed} ₽',
                          ),
                        ],
                        const Padding(
                          padding: EdgeInsets.symmetric(vertical: 12),
                          child: Divider(color: AppColors.grey200),
                        ),
                        Row(
                          mainAxisAlignment: MainAxisAlignment.spaceBetween,
                          children: [
                            const RemoteText('app.orderdetail.total_label', 'Итого',
                                style: TextStyle(
                                  fontSize: 16,
                                  fontWeight: FontWeight.w700,
                                )),
                            Text(
                              '${order.total.toInt()} ₽',
                              style: TextStyle(
                                fontSize: 24,
                                fontWeight: FontWeight.w700,
                                color: AppColors.black,
                              ),
                            ),
                          ],
                        ),
                      ],
                    ),
                  ),

                  // ── Возврат (D-112): заявку оформляет покупатель сам ───────
                  if (_returnable)
                    Padding(
                      padding: const EdgeInsets.fromLTRB(20, 8, 20, 0),
                      child: OutlinedButton(
                        onPressed: () => Navigator.of(context).push(
                          MaterialPageRoute(
                            builder: (_) =>
                                ReturnRequestScreen(orderId: order.id),
                          ),
                        ),
                        child: const RemoteText(
                            'app.orderdetail.return', 'Оформить возврат'),
                      ),
                    ),

                  const SizedBox(height: 24),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  /// Оплаченный заказ можно вернуть (целиком или частями) — сроки и
  /// что именно, решает сервер на экране заявки.
  bool get _returnable =>
      order.paymentStatus == 'paid' ||
      order.paymentStatus == 'partially_refunded';

  String get _deliveryCostText {
    if (order.deliveryCost == 0) return 'Бесплатно';
    return '${order.deliveryCost.toInt()} ₽';
  }

  String get _addressText {
    final d = order.checkoutData;
    final parts = [d.city, d.street, d.house]
        .where((s) => s != null && s.isNotEmpty)
        .join(', ');
    final apt = d.apartment != null ? ', кв. ${d.apartment}' : '';
    final postal =
        d.postalCode != null ? '\n${d.postalCode}' : '';
    return '$parts$apt$postal';
  }

  IconData get _paymentIcon {
    switch (order.checkoutData.paymentType) {
      case PaymentType.card:
        return Icons.credit_card_outlined;
      case PaymentType.cash:
        return Icons.payments_outlined;
      case PaymentType.sbp:
        return Icons.qr_code_outlined;
    }
  }
}

// ─── Header ───────────────────────────────────────────────────────────────────

class _Header extends StatelessWidget {
  final Order order;
  final VoidCallback onClose;
  const _Header({required this.order, required this.onClose});

  @override
  Widget build(BuildContext context) {
    return Container(
      color: AppColors.black,
      child: SafeArea(
        bottom: false,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(20, 8, 20, 20),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  GestureDetector(
                    onTap: onClose,
                    child: Container(
                      padding: const EdgeInsets.all(4),
                      child: const Icon(Icons.arrow_back,
                          color: Colors.white, size: 22),
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Text(
                      'ЗАКАЗ №${order.id}',
                      style: TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.w700,
                        color: Colors.white,
                        letterSpacing: 1.5,
                      ),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 10),
              Padding(
                padding: const EdgeInsets.only(left: 38),
                child: Text(
                  _formatDate(order.createdAt),
                  style: const TextStyle(
                    fontSize: 12,
                    color: Color(0xFF888888),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  String _formatDate(DateTime dt) {
    const months = [
      '', 'января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
      'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря',
    ];
    return '${dt.day} ${months[dt.month]} ${dt.year}, '
        '${dt.hour.toString().padLeft(2, '0')}:'
        '${dt.minute.toString().padLeft(2, '0')}';
  }
}

// ─── Status bar ───────────────────────────────────────────────────────────────

class _StatusBar extends StatelessWidget {
  final OrderStatus status;
  const _StatusBar({required this.status});

  Color get _color {
    switch (status) {
      case OrderStatus.pending:
        return const Color(0xFF1565C0);
      case OrderStatus.processing:
        return const Color(0xFFE65100);
      case OrderStatus.shipped:
        return const Color(0xFF6A1B9A);
      case OrderStatus.delivered:
        return const Color(0xFF2E7D32);
      case OrderStatus.cancelled:
        return AppColors.red;
    }
  }

  IconData get _icon {
    switch (status) {
      case OrderStatus.pending:
        return Icons.hourglass_top_outlined;
      case OrderStatus.processing:
        return Icons.inventory_2_outlined;
      case OrderStatus.shipped:
        return Icons.local_shipping_outlined;
      case OrderStatus.delivered:
        return Icons.check_circle_outline;
      case OrderStatus.cancelled:
        return Icons.cancel_outlined;
    }
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
      color: _color.withValues(alpha: 0.08),
      child: Row(
        children: [
          Icon(_icon, size: 20, color: _color),
          const SizedBox(width: 10),
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              RemoteText(
                'app.orderdetail.status_label',
                'Статус заказа',
                style: TextStyle(
                    fontSize: 11, color: _color.withValues(alpha: 0.7)),
              ),
              Text(
                OrderProvider.statusLabel(status),
                style: TextStyle(
                  fontSize: 14,
                  fontWeight: FontWeight.w700,
                  color: _color,
                ),
              ),
            ],
          ),
        ],
      ),
    ).animate().fadeIn(duration: 350.ms);
  }
}

// ─── Section ──────────────────────────────────────────────────────────────────

class _Section extends StatelessWidget {
  final String title;
  final Widget child;
  final String? contentKey;
  const _Section({required this.title, required this.child, this.contentKey});

  @override
  Widget build(BuildContext context) {
    const titleStyle = TextStyle(
      fontSize: 11,
      fontWeight: FontWeight.w700,
      letterSpacing: 1.2,
      color: AppColors.grey600,
    );
    return Padding(
      padding: const EdgeInsets.fromLTRB(20, 20, 20, 4),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          contentKey == null
              ? Text(
                  title.toUpperCase(),
                  style: titleStyle,
                )
              : RemoteText(
                  contentKey!,
                  title,
                  upper: true,
                  style: titleStyle,
                ),
          const SizedBox(height: 14),
          child,
        ],
      ),
    );
  }
}

class _Divider extends StatelessWidget {
  const _Divider();

  @override
  Widget build(BuildContext context) {
    return Container(
        height: 8, color: AppColors.grey100);
  }
}

// ─── Item row ─────────────────────────────────────────────────────────────────

class _ItemRow extends StatelessWidget {
  final OrderItem item;
  final bool isLast;
  const _ItemRow({required this.item, required this.isLast});

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Image
            SizedBox(
              width: 72,
              height: 88,
              child: item.imageUrl.isNotEmpty
                  ? ProductImage(path: item.imageUrl, iconSize: 20)
                  : Container(color: AppColors.grey100),
            ),
            const SizedBox(width: 14),
            // Info
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    item.productBrand.toUpperCase(),
                    style: const TextStyle(
                      fontSize: 10,
                      fontWeight: FontWeight.w600,
                      color: AppColors.grey400,
                      letterSpacing: 1,
                    ),
                  ),
                  const SizedBox(height: 3),
                  Text(
                    item.productName,
                    style: const TextStyle(
                      fontSize: 14,
                      fontWeight: FontWeight.w600,
                      color: AppColors.black,
                      height: 1.3,
                    ),
                  ),
                  const SizedBox(height: 6),
                  Row(
                    children: [
                      _Tag(item.size),
                      const SizedBox(width: 6),
                      _Tag(item.color),
                      const SizedBox(width: 6),
                      _Tag('×${item.quantity}'),
                    ],
                  ),
                  const SizedBox(height: 8),
                  Text(
                    '${item.total.toInt()} ₽',
                    style: const TextStyle(
                      fontSize: 15,
                      fontWeight: FontWeight.w800,
                      color: AppColors.black,
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
        if (!isLast)
          const Padding(
            padding: EdgeInsets.symmetric(vertical: 14),
            child: Divider(color: AppColors.grey100, height: 1),
          ),
      ],
    );
  }
}

class _Tag extends StatelessWidget {
  final String text;
  const _Tag(this.text);

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      color: AppColors.grey100,
      child: Text(
        text,
        style: const TextStyle(
          fontSize: 11,
          fontWeight: FontWeight.w600,
          color: AppColors.grey600,
        ),
      ),
    );
  }
}

// ─── Info row ─────────────────────────────────────────────────────────────────

class _InfoRow extends StatelessWidget {
  final IconData icon;
  final String label;
  final String value;
  final String? contentKey;
  const _InfoRow(
      {required this.icon,
      required this.label,
      required this.value,
      this.contentKey});

  @override
  Widget build(BuildContext context) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Icon(icon, size: 18, color: AppColors.grey600),
        const SizedBox(width: 10),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              contentKey == null
                  ? Text(label,
                      style: const TextStyle(
                          fontSize: 12, color: AppColors.grey600))
                  : RemoteText(contentKey!, label,
                      style: const TextStyle(
                          fontSize: 12, color: AppColors.grey600)),
              if (value.isNotEmpty)
                Text(value,
                    style: const TextStyle(
                      fontSize: 14,
                      fontWeight: FontWeight.w600,
                      color: AppColors.black,
                      height: 1.4,
                    )),
            ],
          ),
        ),
      ],
    );
  }
}

// ─── Price row ────────────────────────────────────────────────────────────────

class _PriceRow extends StatelessWidget {
  final String contentKey;
  final String label;
  final String value;
  const _PriceRow(
      {required this.contentKey, required this.label, required this.value});

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisAlignment: MainAxisAlignment.spaceBetween,
      children: [
        RemoteText(contentKey, label,
            style: const TextStyle(
                fontSize: 13, color: AppColors.grey600)),
        Text(value,
            style: const TextStyle(
                fontSize: 13,
                fontWeight: FontWeight.w600,
                color: AppColors.black)),
      ],
    );
  }
}
