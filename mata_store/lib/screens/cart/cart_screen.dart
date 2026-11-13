import 'package:flutter/material.dart';
import '../../widgets/product_image.dart';
import '../../widgets/remote_text.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';
import '../../models/cart_item.dart';
import '../../providers/cart_provider.dart';
import '../../providers/tab_notifier.dart';
import '../../theme/app_theme.dart';

class CartScreen extends StatelessWidget {
  const CartScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.white,
      appBar: AppBar(
        title: RemoteText(
          'app.cart.title',
          'КОРЗИНА',
          style: TextStyle(
            fontSize: 20,
            fontWeight: FontWeight.w700,
            letterSpacing: 3,
          ),
        ),
        actions: [
          Consumer<CartProvider>(
            builder: (context, cart, _) {
              if (cart.items.isEmpty) return const SizedBox.shrink();
              return TextButton(
                onPressed: () => _confirmClear(context, cart),
                child: const RemoteText(
                  'app.cart.clear',
                  'Очистить',
                  style: TextStyle(color: AppColors.grey600, fontSize: 13),
                ),
              );
            },
          ),
        ],
      ),
      body: Consumer<TabNotifier>(
        builder: (context, tabs, _) {
          final cart = context.watch<CartProvider>();
          return KeyedSubtree(
            key: ValueKey('cart-${tabs.activationCount(2)}'),
            child: cart.items.isEmpty
                ? const _EmptyCart()
                : Column(
                    children: [
                      _CartHeader(cart: cart),
                      Expanded(
                        child: ListView.separated(
                          padding: const EdgeInsets.fromLTRB(16, 20, 16, 20),
                          itemCount: cart.items.length,
                          separatorBuilder: (_, __) => const Divider(height: 28),
                          itemBuilder: (context, index) {
                            final item = cart.items[index];
                            return _CartItemTile(item: item, index: index)
                                .animate(delay: (index * 80).ms)
                                .fadeIn(duration: 380.ms, curve: Curves.easeOut)
                                .slideX(
                                  begin: 0.12,
                                  duration: 380.ms,
                                  curve: Curves.easeOut,
                                );
                          },
                        ),
                      ),
                      _OrderSummary(cart: cart),
                    ],
                  ),
          );
        },
      ),
    );
  }

  void _confirmClear(BuildContext context, CartProvider cart) {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        shape: const RoundedRectangleBorder(borderRadius: BorderRadius.zero),
        title: const RemoteText('app.cart.clearDialog.title', 'Очистить корзину?'),
        content: const RemoteText(
            'app.cart.clearDialog.body', 'Все товары будут удалены из корзины'),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(),
            child: const RemoteText('app.cart.clearDialog.cancel', 'Отмена',
                style: TextStyle(color: AppColors.grey600)),
          ),
          TextButton(
            onPressed: () {
              Navigator.of(ctx).pop();
              cart.clear();
            },
            child: const RemoteText('app.cart.clearDialog.confirm', 'Очистить',
                style: TextStyle(color: AppColors.red)),
          ),
        ],
      ),
    );
  }
}

// ─── Чёрная шапка с итогом ────────────────────────────────────────────────────

class _CartHeader extends StatelessWidget {
  final CartProvider cart;
  const _CartHeader({required this.cart});

  String _plural(int n) {
    if (n % 10 == 1 && n % 100 != 11) return 'товар';
    if (n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 10 || n % 100 >= 20)) {
      return 'товара';
    }
    return 'товаров';
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      color: AppColors.black,
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(20, 18, 20, 18),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  '${cart.itemCount} ${_plural(cart.itemCount)}',
                  style: const TextStyle(
                    fontSize: 13,
                    color: Color(0xFF888888),
                    letterSpacing: 0.3,
                  ),
                ),
                const SizedBox(height: 2),
                RemoteText(
                  'app.cart.totalDue',
                  'Итого к оплате',
                  style: TextStyle(
                    fontSize: 14,
                    color: Colors.white54,
                    letterSpacing: 1,
                  ),
                ),
              ],
            ),
          ),
          Text(
            '${cart.total.toInt()} ₽',
            style: TextStyle(
              fontSize: 32,
              fontWeight: FontWeight.w700,
              color: Colors.white,
              letterSpacing: -0.5,
            ),
          ),
        ],
      ),
    )
        .animate()
        .fadeIn(duration: 350.ms)
        .slideY(begin: -0.15, duration: 350.ms, curve: Curves.easeOut);
  }
}

// ─── Товар в корзине ──────────────────────────────────────────────────────────

class _CartItemTile extends StatefulWidget {
  final CartItem item;
  final int index;
  const _CartItemTile({required this.item, required this.index});

  @override
  State<_CartItemTile> createState() => _CartItemTileState();
}

class _CartItemTileState extends State<_CartItemTile> {
  @override
  Widget build(BuildContext context) {
    final cart = context.read<CartProvider>();

    return Dismissible(
      key: ValueKey(widget.item.key),
      direction: DismissDirection.endToStart,
      onDismissed: (_) => cart.remove(widget.item.key),
      background: Container(
        alignment: Alignment.centerRight,
        padding: const EdgeInsets.only(right: 20),
        color: AppColors.red,
        child: const Icon(Icons.delete_outline, color: Colors.white, size: 24),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Фото
          SizedBox(
            width: 88,
            height: 108,
            child: ProductImage(path: widget.item.product.firstImage),
          ),

          const SizedBox(width: 14),

          // Информация
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  widget.item.product.brand.toUpperCase(),
                  style: const TextStyle(
                    fontSize: 10,
                    fontWeight: FontWeight.w600,
                    color: AppColors.grey600,
                    letterSpacing: 1,
                  ),
                ),
                const SizedBox(height: 3),
                Text(
                  widget.item.product.name,
                  style: const TextStyle(
                    fontSize: 14,
                    fontWeight: FontWeight.w600,
                    color: AppColors.black,
                    height: 1.3,
                  ),
                ),
                const SizedBox(height: 5),
                Text(
                  '${widget.item.size}  ·  ${widget.item.color}',
                  style: const TextStyle(
                    fontSize: 12,
                    color: AppColors.grey500,
                  ),
                ),
                const SizedBox(height: 12),
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Text(
                      '${widget.item.total.toInt()} ₽',
                      style: const TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.w800,
                        color: AppColors.black,
                      ),
                    ),
                    _QtyRow(item: widget.item),
                  ],
                ),
              ],
            ),
          ),

          // Удалить
          GestureDetector(
            onTap: () => cart.remove(widget.item.key),
            child: const Padding(
              padding: EdgeInsets.only(left: 10),
              child: Icon(Icons.close, size: 17, color: AppColors.grey400),
            ),
          ),
        ],
      ),
    );
  }
}

// ─── Кнопки количества ────────────────────────────────────────────────────────

class _QtyRow extends StatelessWidget {
  final CartItem item;
  const _QtyRow({required this.item});

  @override
  Widget build(BuildContext context) {
    final cart = context.read<CartProvider>();
    return Row(
      children: [
        _QtyButton(
          icon: Icons.remove,
          onTap: () => cart.decrement(item.key),
        ),
        AnimatedSwitcher(
          duration: const Duration(milliseconds: 200),
          transitionBuilder: (child, anim) => ScaleTransition(
            scale: anim,
            child: FadeTransition(opacity: anim, child: child),
          ),
          child: SizedBox(
            key: ValueKey(item.quantity),
            width: 32,
            child: Text(
              '${item.quantity}',
              textAlign: TextAlign.center,
              style: const TextStyle(
                fontSize: 15,
                fontWeight: FontWeight.w700,
                color: AppColors.black,
              ),
            ),
          ),
        ),
        _QtyButton(
          icon: Icons.add,
          onTap: () => cart.increment(item.key),
        ),
      ],
    );
  }
}

class _QtyButton extends StatefulWidget {
  final IconData icon;
  final VoidCallback onTap;
  const _QtyButton({required this.icon, required this.onTap});

  @override
  State<_QtyButton> createState() => _QtyButtonState();
}

class _QtyButtonState extends State<_QtyButton> {
  bool _pressed = false;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: widget.onTap,
      onTapDown: (_) { if (mounted) setState(() => _pressed = true); },
      onTapUp: (_) { if (mounted) setState(() => _pressed = false); },
      onTapCancel: () { if (mounted) setState(() => _pressed = false); },
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 100),
        width: 30,
        height: 30,
        decoration: BoxDecoration(
          color: _pressed ? AppColors.black : AppColors.white,
          border: Border.all(
            color: _pressed ? AppColors.black : AppColors.grey200,
          ),
        ),
        child: Icon(
          widget.icon,
          size: 15,
          color: _pressed ? AppColors.white : AppColors.black,
        ),
      ),
    );
  }
}

// ─── Итог и кнопка заказа ────────────────────────────────────────────────────

class _OrderSummary extends StatelessWidget {
  final CartProvider cart;
  const _OrderSummary({required this.cart});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: EdgeInsets.fromLTRB(
        20,
        16,
        20,
        16 + MediaQuery.of(context).padding.bottom,
      ),
      decoration: const BoxDecoration(
        color: AppColors.white,
        border: Border(top: BorderSide(color: AppColors.grey200)),
      ),
      child: Column(
        children: [
          // Детали
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              const RemoteText(
                'app.cart.delivery',
                'Доставка',
                style: TextStyle(fontSize: 13, color: AppColors.grey600),
              ),
              const RemoteText(
                'app.cart.deliveryNote',
                'Рассчитывается при оформлении',
                style: TextStyle(fontSize: 12, color: AppColors.grey500),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              const RemoteText(
                'app.cart.summaryTotal',
                'Итого',
                style: TextStyle(
                  fontSize: 15,
                  fontWeight: FontWeight.w700,
                  color: AppColors.black,
                ),
              ),
              Text(
                '${cart.total.toInt()} ₽',
                style: TextStyle(
                  fontSize: 22,
                  fontWeight: FontWeight.w700,
                  color: AppColors.black,
                ),
              ),
            ],
          ),
          const SizedBox(height: 14),
          _CheckoutButton(),
        ],
      ),
    )
        .animate()
        .slideY(begin: 0.15, duration: 400.ms, curve: Curves.easeOut)
        .fadeIn(duration: 400.ms);
  }
}

class _CheckoutButton extends StatefulWidget {
  @override
  State<_CheckoutButton> createState() => _CheckoutButtonState();
}

class _CheckoutButtonState extends State<_CheckoutButton> {
  bool _pressed = false;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: () => context.push('/checkout'),
      onTapDown: (_) { if (mounted) setState(() => _pressed = true); },
      onTapUp: (_) { if (mounted) setState(() => _pressed = false); },
      onTapCancel: () { if (mounted) setState(() => _pressed = false); },
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 120),
        height: 52,
        color: _pressed ? AppColors.grey800 : AppColors.black,
        alignment: Alignment.center,
        child: RemoteText(
          'app.cart.checkout',
          'ОФОРМИТЬ ЗАКАЗ',
          style: TextStyle(
            fontSize: 15,
            fontWeight: FontWeight.w600,
            color: AppColors.white,
            letterSpacing: 2,
          ),
        ),
      ),
    );
  }
}

// ─── Пустая корзина ───────────────────────────────────────────────────────────

class _EmptyCart extends StatelessWidget {
  const _EmptyCart();

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 40),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Icon(
              Icons.shopping_bag_outlined,
              size: 72,
              color: AppColors.grey200,
            )
                .animate()
                .scale(
                  begin: const Offset(0.5, 0.5),
                  duration: 500.ms,
                  curve: Curves.elasticOut,
                )
                .fadeIn(duration: 300.ms),

            const SizedBox(height: 20),

            const RemoteText(
              'app.cart.empty.title',
              'Корзина пуста',
              style: TextStyle(
                fontSize: 20,
                fontWeight: FontWeight.w700,
                color: AppColors.black,
              ),
            )
                .animate(delay: 150.ms)
                .fadeIn(duration: 350.ms)
                .slideY(begin: 0.2, curve: Curves.easeOut),

            const SizedBox(height: 8),

            const RemoteText(
              'app.cart.empty.subtitle',
              'Добавьте товары из каталога,\nчтобы оформить заказ',
              textAlign: TextAlign.center,
              style: TextStyle(
                fontSize: 14,
                color: AppColors.grey600,
                height: 1.5,
              ),
            )
                .animate(delay: 230.ms)
                .fadeIn(duration: 350.ms)
                .slideY(begin: 0.2, curve: Curves.easeOut),

            const SizedBox(height: 32),

            GestureDetector(
              onTap: () => context.go('/catalog'),
              child: Container(
                height: 50,
                color: AppColors.black,
                alignment: Alignment.center,
                child: RemoteText(
                  'app.cart.empty.toCatalog',
                  'ПЕРЕЙТИ В КАТАЛОГ',
                  style: TextStyle(
                    fontSize: 14,
                    fontWeight: FontWeight.w600,
                    color: AppColors.white,
                    letterSpacing: 2,
                  ),
                ),
              ),
            )
                .animate(delay: 320.ms)
                .fadeIn(duration: 350.ms)
                .slideY(begin: 0.2, curve: Curves.easeOut),

            const SizedBox(height: 12),

            GestureDetector(
              onTap: () => context.go('/'),
              child: Container(
                height: 50,
                decoration: BoxDecoration(
                  border: Border.all(color: AppColors.grey200),
                ),
                alignment: Alignment.center,
                child: RemoteText(
                  'app.cart.empty.toHome',
                  'НА ГЛАВНУЮ',
                  style: TextStyle(
                    fontSize: 14,
                    fontWeight: FontWeight.w500,
                    color: AppColors.black,
                    letterSpacing: 2,
                  ),
                ),
              ),
            )
                .animate(delay: 390.ms)
                .fadeIn(duration: 350.ms)
                .slideY(begin: 0.2, curve: Curves.easeOut),
          ],
        ),
      ),
    );
  }
}
