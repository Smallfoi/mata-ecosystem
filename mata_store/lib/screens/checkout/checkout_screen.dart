import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';
import '../../models/loyalty.dart';
import '../../models/order.dart';
import '../../providers/auth_provider.dart';
import '../../providers/cart_provider.dart';
import '../../providers/loyalty_provider.dart';
import '../../providers/order_provider.dart';
import '../../theme/app_theme.dart';
import '../../widgets/product_image.dart';
import '../../widgets/remote_text.dart';

class CheckoutScreen extends StatefulWidget {
  const CheckoutScreen({super.key});

  @override
  State<CheckoutScreen> createState() => _CheckoutScreenState();
}

class _CheckoutScreenState extends State<CheckoutScreen> {
  final _pageCtrl = PageController();
  int _step = 0;
  String? _stepError;
  bool _placing = false;

  // Step 1 — Контакты
  final _nameCtrl = TextEditingController();
  final _phoneCtrl = TextEditingController();
  final _emailCtrl = TextEditingController();

  // Step 2 — Доставка
  DeliveryType _delivery = DeliveryType.courier;
  final _cityCtrl = TextEditingController();
  final _streetCtrl = TextEditingController();
  final _houseCtrl = TextEditingController();
  final _aptCtrl = TextEditingController();
  final _postalCtrl = TextEditingController();

  // Step 3 — Оплата
  // Единственный способ оплаты — СБП (D-72).
  PaymentType _payment = PaymentType.sbp;

  // Списание баллов лояльности
  int _pointsToRedeem = 0;

  @override
  void initState() {
    super.initState();
    final auth = context.read<AuthProvider>();
    if (auth.isLoggedIn) {
      final user = auth.user!;
      _nameCtrl.text = user.name;
      _emailCtrl.text = user.email;
      if (user.phone != null) _phoneCtrl.text = user.phone!;
      // Pre-fill last saved address
      if (user.addresses.isNotEmpty) {
        final addr = user.addresses.first;
        _cityCtrl.text = addr.city;
        _streetCtrl.text = addr.street;
        _houseCtrl.text = addr.house;
        if (addr.apartment != null) _aptCtrl.text = addr.apartment!;
        if (addr.postalCode != null) _postalCtrl.text = addr.postalCode!;
      }
    }
  }

  @override
  void dispose() {
    _pageCtrl.dispose();
    for (final c in [
      _nameCtrl,
      _phoneCtrl,
      _emailCtrl,
      _cityCtrl,
      _streetCtrl,
      _houseCtrl,
      _aptCtrl,
      _postalCtrl,
    ]) {
      c.dispose();
    }
    super.dispose();
  }

  String? _validate() {
    switch (_step) {
      case 0:
        if (_nameCtrl.text.trim().isEmpty) return 'Введите имя';
        if (_phoneCtrl.text.trim().isEmpty) return 'Введите телефон';
        if (!_emailCtrl.text.contains('@')) return 'Введите корректный email';
        return null;
      case 1:
        if (_delivery != DeliveryType.pickup) {
          if (_cityCtrl.text.trim().isEmpty) return 'Введите город';
          if (_streetCtrl.text.trim().isEmpty) return 'Введите улицу';
          if (_houseCtrl.text.trim().isEmpty) return 'Введите номер дома';
        }
        return null;
      default:
        return null;
    }
  }

  void _next() {
    final err = _validate();
    if (err != null) {
      setState(() => _stepError = err);
      return;
    }
    setState(() {
      _stepError = null;
      _step++;
    });
    _pageCtrl.animateToPage(
      _step,
      duration: const Duration(milliseconds: 350),
      curve: Curves.easeInOutCubic,
    );
  }

  void _back() {
    if (_step == 0) {
      Navigator.of(context).pop();
      return;
    }
    setState(() {
      _step--;
      _stepError = null;
    });
    _pageCtrl.animateToPage(
      _step,
      duration: const Duration(milliseconds: 350),
      curve: Curves.easeInOutCubic,
    );
  }

  Future<void> _confirm() async {
    if (_placing) return;
    final cart = context.read<CartProvider>();
    if (cart.items.isEmpty) {
      context.go('/cart');
      return;
    }
    // Заказ уходит на общий backend по JWT. Если сессия мертва (истёкший токен
    // → авто-выход через ApiClient.onUnauthorized), НЕ создаём «фантомный»
    // локальный заказ и не чистим корзину — просим войти заново.
    if (context.read<OrderProvider>().serverBacked &&
        !context.read<AuthProvider>().isLoggedIn) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Войдите в аккаунт, чтобы оформить заказ'),
          behavior: SnackBarBehavior.floating,
        ),
      );
      return;
    }
    setState(() => _placing = true);

    await Future.delayed(const Duration(milliseconds: 900));

    if (!mounted) return;
    final orders = context.read<OrderProvider>();

    final data = CheckoutData(
      name: _nameCtrl.text.trim(),
      phone: _phoneCtrl.text.trim(),
      email: _emailCtrl.text.trim(),
      deliveryType: _delivery,
      city: _delivery != DeliveryType.pickup ? _cityCtrl.text.trim() : null,
      street: _delivery != DeliveryType.pickup ? _streetCtrl.text.trim() : null,
      house: _delivery != DeliveryType.pickup ? _houseCtrl.text.trim() : null,
      apartment: _aptCtrl.text.trim().isNotEmpty ? _aptCtrl.text.trim() : null,
      postalCode: _postalCtrl.text.trim().isNotEmpty
          ? _postalCtrl.text.trim()
          : null,
      paymentType: _payment,
    );

    // Лояльность: ограничиваем списание актуальным максимумом на момент заказа
    final loyalty = context.read<LoyaltyProvider>();
    final orderTotal = cart.total + _deliveryCost;
    final redeem = _pointsToRedeem.clamp(0, loyalty.maxRedeemable(orderTotal));

    final order = orders.placeOrder(
      cart.items.toList(),
      data,
      pointsRedeemed: redeem,
    );

    // Дожидаемся РЕАЛЬНОЙ отправки заказа на сервер. Пока не подтверждена — НЕ чистим
    // корзину, НЕ списываем баллы и НЕ показываем «оформлен». При провале заказ уже
    // снят провайдером — предлагаем повторить, ничего не потеряв (корзина/баллы целы).
    final submitted = await (orders.lastSubmit ?? Future.value(true));
    if (!mounted) return;
    if (!submitted) {
      setState(() => _placing = false);
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text(
              'Не удалось оформить заказ. Проверьте соединение и попробуйте снова.'),
          behavior: SnackBarBehavior.floating,
        ),
      );
      return;
    }

    // Заказ принят сервером — завершаем покупку.
    cart.clear();

    if (redeem > 0) {
      // Трата баллов авторитетно идёт через общий backend (если он включён).
      final err = await loyalty.redeem(redeem, order.id);
      if (err != null && mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(err), behavior: SnackBarBehavior.floating),
        );
      }
    }
    if (!mounted) return;
    // Начисление за покупку считает СЕРВЕР при создании заказа (/orders, анти-чит
    // S-04 Phase 2). При serverBacked перечитываем баланс с сервера; в mock-режиме
    // начисляем локально для демо.
    if (loyalty.serverBacked) {
      await loyalty.load();
    } else {
      loyalty.earnForPurchase(
        order.total,
        isFirstOrder: orders.orders.length == 1,
        orderId: order.id,
      );
    }

    if (!mounted) return;
    // Save delivery address to profile
    final auth = context.read<AuthProvider>();
    if (auth.isLoggedIn &&
        _delivery != DeliveryType.pickup &&
        _cityCtrl.text.trim().isNotEmpty) {
      auth.addAddress(
        SavedAddress(
          city: _cityCtrl.text.trim(),
          street: _streetCtrl.text.trim(),
          house: _houseCtrl.text.trim(),
          apartment: _aptCtrl.text.trim().isNotEmpty
              ? _aptCtrl.text.trim()
              : null,
          postalCode: _postalCtrl.text.trim().isNotEmpty
              ? _postalCtrl.text.trim()
              : null,
        ),
      );
    }

    if (!mounted) return;
    // Заказ принят — дальше деньги. Экран оплаты сам решит, что показать:
    // без провайдера (dev) он сразу уводит на «заказ оформлен».
    context.go('/order-payment/${order.id}');
  }

  double get _deliveryCost => OrderProvider.costFor(_delivery);

  @override
  Widget build(BuildContext context) {
    final cart = context.watch<CartProvider>();
    if (cart.items.isEmpty) {
      return Scaffold(
        backgroundColor: AppColors.white,
        body: Column(
          children: [
            _Header(step: _step, onClose: () => context.go('/cart')),
            const Expanded(child: _EmptyCheckout()),
          ],
        ),
      );
    }

    return Scaffold(
      backgroundColor: AppColors.white,
      body: Column(
        children: [
          _Header(step: _step, onClose: () => Navigator.of(context).pop()),
          Expanded(
            child: PageView(
              controller: _pageCtrl,
              physics: const NeverScrollableScrollPhysics(),
              children: [
                _ContactStep(
                  nameCtrl: _nameCtrl,
                  phoneCtrl: _phoneCtrl,
                  emailCtrl: _emailCtrl,
                  error: _step == 0 ? _stepError : null,
                ),
                _DeliveryStep(
                  selected: _delivery,
                  onChanged: (t) => setState(() => _delivery = t),
                  cityCtrl: _cityCtrl,
                  streetCtrl: _streetCtrl,
                  houseCtrl: _houseCtrl,
                  aptCtrl: _aptCtrl,
                  postalCtrl: _postalCtrl,
                  error: _step == 1 ? _stepError : null,
                ),
                _PaymentStep(
                  selected: _payment,
                  onChanged: (p) => setState(() => _payment = p),
                ),
                _ReviewStep(
                  nameCtrl: _nameCtrl,
                  phoneCtrl: _phoneCtrl,
                  emailCtrl: _emailCtrl,
                  delivery: _delivery,
                  cityCtrl: _cityCtrl,
                  streetCtrl: _streetCtrl,
                  houseCtrl: _houseCtrl,
                  aptCtrl: _aptCtrl,
                  payment: _payment,
                  deliveryCost: _deliveryCost,
                  pointsToRedeem: _pointsToRedeem,
                  onRedeemChanged: (v) => setState(() => _pointsToRedeem = v),
                ),
              ],
            ),
          ),
          _NavBar(
            step: _step,
            loading: _placing,
            onBack: _back,
            onNext: _step < 3 ? _next : _confirm,
          ),
        ],
      ),
    );
  }
}

class _EmptyCheckout extends StatelessWidget {
  const _EmptyCheckout();

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 32),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Icon(
              Icons.shopping_bag_outlined,
              size: 64,
              color: AppColors.grey200,
            ),
            const SizedBox(height: 16),
            const RemoteText(
              'app.checkout.empty',
              'Оформлять пока нечего',
              textAlign: TextAlign.center,
              style: TextStyle(
                fontSize: 18,
                fontWeight: FontWeight.w700,
                color: AppColors.black,
              ),
            ),
            const SizedBox(height: 8),
            const RemoteText(
              'app.checkout.empty.subtitle',
              'Добавьте товары в корзину, чтобы перейти к доставке и оплате',
              textAlign: TextAlign.center,
              style: TextStyle(
                fontSize: 14,
                color: AppColors.grey600,
                height: 1.45,
              ),
            ),
            const SizedBox(height: 28),
            GestureDetector(
              onTap: () => context.go('/catalog'),
              child: Container(
                height: 52,
                color: AppColors.black,
                alignment: Alignment.center,
                child: RemoteText(
                  'app.checkout.toCatalog',
                  'ПЕРЕЙТИ В КАТАЛОГ',
                  style: TextStyle(
                    fontSize: 15,
                    fontWeight: FontWeight.w600,
                    color: AppColors.white,
                    letterSpacing: 2,
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    ).animate().fadeIn(duration: 300.ms).slideY(begin: 0.06);
  }
} // ─── Header + step indicator ──────────────────────────────────────────────────

class _Header extends StatelessWidget {
  final int step;
  final VoidCallback onClose;
  const _Header({required this.step, required this.onClose});

  static const _labels = ['КОНТАКТЫ', 'ДОСТАВКА', 'ОПЛАТА', 'ИТОГ'];
  static const _stepKeys = ['contacts', 'delivery', 'payment', 'review'];

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
                  RemoteText(
                    'app.checkout.title',
                    'ОФОРМЛЕНИЕ ЗАКАЗА',
                    style: TextStyle(
                      fontSize: 18,
                      fontWeight: FontWeight.w700,
                      color: Colors.white,
                      letterSpacing: 2,
                    ),
                  ),
                  const Spacer(),
                  GestureDetector(
                    onTap: onClose,
                    child: Container(
                      padding: const EdgeInsets.all(4),
                      child: const Icon(
                        Icons.close,
                        color: Colors.white,
                        size: 22,
                      ),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 20),
              Row(
                children: List.generate(4, (i) {
                  final done = i < step;
                  final current = i == step;
                  return Expanded(
                    child: Row(
                      children: [
                        Column(
                          children: [
                            AnimatedContainer(
                              duration: const Duration(milliseconds: 300),
                              width: 26,
                              height: 26,
                              decoration: BoxDecoration(
                                shape: BoxShape.circle,
                                color: done
                                    ? Colors.white
                                    : current
                                    ? Colors.transparent
                                    : Colors.transparent,
                                border: Border.all(
                                  color: done || current
                                      ? Colors.white
                                      : Colors.white24,
                                  width: current ? 2 : 1.5,
                                ),
                              ),
                              alignment: Alignment.center,
                              child: done
                                  ? const Icon(
                                      Icons.check,
                                      size: 13,
                                      color: AppColors.black,
                                    )
                                  : Text(
                                      '${i + 1}',
                                      style: TextStyle(
                                        fontSize: 11,
                                        fontWeight: FontWeight.w700,
                                        color: current
                                            ? Colors.white
                                            : Colors.white38,
                                      ),
                                    ),
                            ),
                            const SizedBox(height: 4),
                            RemoteText(
                              'app.checkout.step.${_stepKeys[i]}',
                              _labels[i],
                              style: TextStyle(
                                fontSize: 8,
                                fontWeight: FontWeight.w600,
                                letterSpacing: 0.5,
                                color: done || current
                                    ? Colors.white
                                    : Colors.white38,
                              ),
                            ),
                          ],
                        ),
                        if (i < 3)
                          Expanded(
                            child: AnimatedContainer(
                              duration: const Duration(milliseconds: 300),
                              height: 1,
                              margin: const EdgeInsets.only(bottom: 18),
                              color: i < step ? Colors.white : Colors.white24,
                            ),
                          ),
                      ],
                    ),
                  );
                }),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

// ─── Step 1: Контакты ─────────────────────────────────────────────────────────

class _ContactStep extends StatelessWidget {
  final TextEditingController nameCtrl;
  final TextEditingController phoneCtrl;
  final TextEditingController emailCtrl;
  final String? error;

  const _ContactStep({
    required this.nameCtrl,
    required this.phoneCtrl,
    required this.emailCtrl,
    required this.error,
  });

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(20, 28, 20, 20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const _StepTitle('app.checkout.title.contacts', 'Контактные данные'),
          const SizedBox(height: 6),
          const RemoteText(
            'app.checkout.contactsSubtitle',
            'Укажите данные для связи по заказу',
            style: TextStyle(fontSize: 13, color: AppColors.grey600),
          ),
          const SizedBox(height: 24),
          _Field(
            ctrl: nameCtrl,
            label: 'Имя',
            hint: 'Иван Иванов',
            icon: Icons.person_outline,
            cap: TextCapitalization.words,
          ),
          const SizedBox(height: 14),
          _Field(
            ctrl: phoneCtrl,
            label: 'Телефон',
            hint: '+7 (999) 000-00-00',
            icon: Icons.phone_outlined,
            type: TextInputType.phone,
          ),
          const SizedBox(height: 14),
          _Field(
            ctrl: emailCtrl,
            label: 'Email',
            hint: 'example@mail.ru',
            icon: Icons.mail_outline,
            type: TextInputType.emailAddress,
          ),
          if (error != null) ...[
            const SizedBox(height: 14),
            _ErrorBanner(error!),
          ],
        ],
      ),
    ).animate().fadeIn(duration: 300.ms);
  }
}

// ─── Step 2: Доставка ─────────────────────────────────────────────────────────

class _DeliveryStep extends StatelessWidget {
  final DeliveryType selected;
  final ValueChanged<DeliveryType> onChanged;
  final TextEditingController cityCtrl;
  final TextEditingController streetCtrl;
  final TextEditingController houseCtrl;
  final TextEditingController aptCtrl;
  final TextEditingController postalCtrl;
  final String? error;

  const _DeliveryStep({
    required this.selected,
    required this.onChanged,
    required this.cityCtrl,
    required this.streetCtrl,
    required this.houseCtrl,
    required this.aptCtrl,
    required this.postalCtrl,
    required this.error,
  });

  @override
  Widget build(BuildContext context) {
    final needAddress = selected != DeliveryType.pickup;
    return SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(20, 28, 20, 20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const _StepTitle('app.checkout.title.delivery', 'Способ доставки'),
          const SizedBox(height: 20),
          ..._options.map(
            (opt) => Padding(
              padding: const EdgeInsets.only(bottom: 10),
              child: _DeliveryOption(
                type: opt.$1,
                label: opt.$2,
                subtitle: opt.$3,
                price: opt.$4,
                selected: selected == opt.$1,
                onTap: () => onChanged(opt.$1),
              ),
            ),
          ),
          if (needAddress) ...[
            const SizedBox(height: 20),
            const _StepTitle('app.checkout.title.address', 'Адрес доставки'),
            const SizedBox(height: 16),
            _Field(
              ctrl: cityCtrl,
              label: 'Город',
              hint: 'Москва',
              icon: Icons.location_city_outlined,
            ),
            const SizedBox(height: 14),
            _Field(
              ctrl: streetCtrl,
              label: 'Улица',
              hint: 'ул. Ленина',
              icon: Icons.signpost_outlined,
            ),
            const SizedBox(height: 14),
            Row(
              children: [
                Expanded(
                  flex: 2,
                  child: _Field(
                    ctrl: houseCtrl,
                    label: 'Дом',
                    hint: '12А',
                    icon: Icons.home_outlined,
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: _Field(
                    ctrl: aptCtrl,
                    label: 'Кв.',
                    hint: '45',
                    icon: Icons.door_front_door_outlined,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 14),
            _Field(
              ctrl: postalCtrl,
              label: 'Индекс (необязательно)',
              hint: '101000',
              icon: Icons.markunread_mailbox_outlined,
              type: TextInputType.number,
            ),
          ],
          if (error != null) ...[
            const SizedBox(height: 14),
            _ErrorBanner(error!),
          ],
        ],
      ),
    ).animate().fadeIn(duration: 300.ms);
  }

  static const _options = [
    (
      DeliveryType.pickup,
      'Самовывоз',
      'г. Москва, ул. Спортивная, 5',
      'Бесплатно',
    ),
    (DeliveryType.courier, 'Курьер', '1–2 дня', '300 ₽'),
    (DeliveryType.cdek, 'СДЭК', '2–5 дней', '200 ₽'),
    (DeliveryType.russianPost, 'Почта России', '5–14 дней', '150 ₽'),
  ];
}

class _DeliveryOption extends StatelessWidget {
  final DeliveryType type;
  final String label;
  final String subtitle;
  final String price;
  final bool selected;
  final VoidCallback onTap;

  const _DeliveryOption({
    required this.type,
    required this.label,
    required this.subtitle,
    required this.price,
    required this.selected,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 200),
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 14),
        decoration: BoxDecoration(
          color: selected ? AppColors.black : AppColors.white,
          border: Border.all(
            color: selected ? AppColors.black : AppColors.grey200,
            width: selected ? 1.5 : 1,
          ),
        ),
        child: Row(
          children: [
            AnimatedContainer(
              duration: const Duration(milliseconds: 200),
              width: 18,
              height: 18,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: selected ? Colors.white : Colors.transparent,
                border: Border.all(
                  color: selected ? Colors.white : AppColors.grey400,
                  width: 1.5,
                ),
              ),
              child: selected
                  ? const Icon(Icons.circle, size: 8, color: AppColors.black)
                  : null,
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  RemoteText(
                    'app.checkout.opt.${type.name}.title',
                    label,
                    style: TextStyle(
                      fontSize: 14,
                      fontWeight: FontWeight.w700,
                      color: selected ? Colors.white : AppColors.black,
                    ),
                  ),
                  RemoteText(
                    'app.checkout.opt.${type.name}.subtitle',
                    subtitle,
                    style: TextStyle(
                      fontSize: 12,
                      color: selected ? Colors.white60 : AppColors.grey600,
                    ),
                  ),
                ],
              ),
            ),
            Text(
              price,
              style: TextStyle(
                fontSize: 14,
                fontWeight: FontWeight.w700,
                color: selected ? Colors.white : AppColors.black,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

// ─── Step 3: Оплата ───────────────────────────────────────────────────────────

class _PaymentStep extends StatelessWidget {
  final PaymentType selected;
  final ValueChanged<PaymentType> onChanged;

  const _PaymentStep({required this.selected, required this.onChanged});

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(20, 28, 20, 20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const _StepTitle('app.checkout.title.payment', 'Способ оплаты'),
          const SizedBox(height: 20),
          // Путь один — СБП (D-72): карт и оплаты при получении нет.
          _PaymentOption(
            type: PaymentType.sbp,
            label: 'СБП',
            subtitle: 'Система быстрых платежей',
            icon: Icons.qr_code_outlined,
            selected: selected == PaymentType.sbp,
            onTap: () => onChanged(PaymentType.sbp),
          ),
        ],
      ),
    ).animate().fadeIn(duration: 300.ms);
  }
}

class _PaymentOption extends StatelessWidget {
  final PaymentType type;
  final String label;
  final String subtitle;
  final IconData icon;
  final bool selected;
  final VoidCallback onTap;

  const _PaymentOption({
    required this.type,
    required this.label,
    required this.subtitle,
    required this.icon,
    required this.selected,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 200),
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 14),
        decoration: BoxDecoration(
          color: selected ? AppColors.black : AppColors.white,
          border: Border.all(
            color: selected ? AppColors.black : AppColors.grey200,
            width: selected ? 1.5 : 1,
          ),
        ),
        child: Row(
          children: [
            Icon(
              icon,
              size: 22,
              color: selected ? Colors.white : AppColors.grey600,
            ),
            const SizedBox(width: 14),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  RemoteText(
                    'app.checkout.opt.${type.name}.title',
                    label,
                    style: TextStyle(
                      fontSize: 14,
                      fontWeight: FontWeight.w700,
                      color: selected ? Colors.white : AppColors.black,
                    ),
                  ),
                  RemoteText(
                    'app.checkout.opt.${type.name}.subtitle',
                    subtitle,
                    style: TextStyle(
                      fontSize: 12,
                      color: selected ? Colors.white60 : AppColors.grey600,
                    ),
                  ),
                ],
              ),
            ),
            AnimatedContainer(
              duration: const Duration(milliseconds: 200),
              width: 18,
              height: 18,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: selected ? Colors.white : Colors.transparent,
                border: Border.all(
                  color: selected ? Colors.white : AppColors.grey400,
                  width: 1.5,
                ),
              ),
              child: selected
                  ? const Icon(Icons.circle, size: 8, color: AppColors.black)
                  : null,
            ),
          ],
        ),
      ),
    );
  }
}

// ─── Step 4: Итог (review) ────────────────────────────────────────────────────

class _ReviewStep extends StatelessWidget {
  final TextEditingController nameCtrl;
  final TextEditingController phoneCtrl;
  final TextEditingController emailCtrl;
  final DeliveryType delivery;
  final TextEditingController cityCtrl;
  final TextEditingController streetCtrl;
  final TextEditingController houseCtrl;
  final TextEditingController aptCtrl;
  final PaymentType payment;
  final double deliveryCost;
  final int pointsToRedeem;
  final ValueChanged<int> onRedeemChanged;

  const _ReviewStep({
    required this.nameCtrl,
    required this.phoneCtrl,
    required this.emailCtrl,
    required this.delivery,
    required this.cityCtrl,
    required this.streetCtrl,
    required this.houseCtrl,
    required this.aptCtrl,
    required this.payment,
    required this.deliveryCost,
    required this.pointsToRedeem,
    required this.onRedeemChanged,
  });

  String get _address {
    if (delivery == DeliveryType.pickup) return 'г. Москва, ул. Спортивная, 5';
    final parts = [
      cityCtrl.text,
      streetCtrl.text,
      houseCtrl.text,
    ].where((s) => s.isNotEmpty).join(', ');
    final apt = aptCtrl.text.isNotEmpty ? ', кв. ${aptCtrl.text}' : '';
    return '$parts$apt';
  }

  @override
  Widget build(BuildContext context) {
    final cart = context.watch<CartProvider>();
    final loyalty = context.watch<LoyaltyProvider>();
    final orderTotal = cart.total + deliveryCost;
    final maxRedeem = loyalty.maxRedeemable(orderTotal);
    // Если выбранное списание больше доступного (изменился состав) — обрезаем.
    final redeem = pointsToRedeem > maxRedeem ? maxRedeem : pointsToRedeem;
    final total = orderTotal - redeem;

    return SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(20, 28, 20, 20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const _StepTitle('app.checkout.title.review', 'Проверьте заказ'),
          const SizedBox(height: 20),

          // Cart items
          ...cart.items.map(
            (item) => Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: Row(
                children: [
                  SizedBox(
                    width: 52,
                    height: 64,
                    child: item.product.imageUrls.isNotEmpty
                        ? ProductImage(
                            path: item.product.imageUrls.first,
                            iconSize: 18,
                          )
                        : Container(color: AppColors.grey100),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          item.product.name,
                          style: const TextStyle(
                            fontSize: 13,
                            fontWeight: FontWeight.w600,
                          ),
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                        ),
                        Text(
                          '${item.size} · ${item.color} · ×${item.quantity}',
                          style: const TextStyle(
                            fontSize: 11,
                            color: AppColors.grey600,
                          ),
                        ),
                      ],
                    ),
                  ),
                  Text(
                    '${item.total.toInt()} ₽',
                    style: const TextStyle(
                      fontSize: 14,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ],
              ),
            ),
          ),

          const Divider(height: 24),

          _ReviewRow(
            label: 'Контакт',
            value: '${nameCtrl.text} · ${phoneCtrl.text}',
          ),
          const SizedBox(height: 8),
          _ReviewRow(
            label: 'Доставка',
            value: OrderProvider.deliveryLabel(delivery),
          ),
          const SizedBox(height: 4),
          _ReviewRow(label: 'Адрес', value: _address, small: true),
          const SizedBox(height: 8),
          _ReviewRow(
            label: 'Оплата',
            value: OrderProvider.paymentLabel(payment),
          ),

          // Списание баллов лояльности
          if (maxRedeem > 0) ...[
            const Divider(height: 24),
            _RedeemPointsTile(
              balance: loyalty.balance,
              maxRedeem: maxRedeem,
              applied: redeem > 0,
              onToggle: (on) => onRedeemChanged(on ? maxRedeem : 0),
            ),
          ] else if (loyalty.balance > 0) ...[
            const Divider(height: 24),
            Row(
              children: [
                const Icon(
                  Icons.stars_rounded,
                  size: 16,
                  color: AppColors.grey400,
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    'У вас ${loyalty.balance} баллов. Списать можно от '
                    '${LoyaltyAccount.minRedeem} при заказе крупнее',
                    style: const TextStyle(
                      fontSize: 12,
                      color: AppColors.grey600,
                    ),
                  ),
                ),
              ],
            ),
          ],

          const Divider(height: 24),

          _ReviewRow(label: 'Товары', value: '${cart.total.toInt()} ₽'),
          const SizedBox(height: 6),
          _ReviewRow(
            label: 'Доставка',
            value: deliveryCost == 0
                ? 'Бесплатно'
                : '${deliveryCost.toInt()} ₽',
          ),
          if (redeem > 0) ...[
            const SizedBox(height: 6),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                const RemoteText(
                  'app.checkout.pointsLabel',
                  'Баллы',
                  style: TextStyle(fontSize: 13, color: AppColors.grey600),
                ),
                Text(
                  '−$redeem ₽',
                  style: const TextStyle(
                    fontSize: 13,
                    fontWeight: FontWeight.w700,
                    color: Color(0xFF2E7D32),
                  ),
                ),
              ],
            ),
          ],
          const SizedBox(height: 10),
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              const RemoteText(
                'app.checkout.total',
                'Итого',
                style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
              ),
              Text(
                '${total.toInt()} ₽',
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
    ).animate().fadeIn(duration: 300.ms);
  }
}

class _RedeemPointsTile extends StatelessWidget {
  final int balance;
  final int maxRedeem;
  final bool applied;
  final ValueChanged<bool> onToggle;

  const _RedeemPointsTile({
    required this.balance,
    required this.maxRedeem,
    required this.applied,
    required this.onToggle,
  });

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: () => onToggle(!applied),
      behavior: HitTestBehavior.opaque,
      child: Container(
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: applied ? AppColors.black : AppColors.white,
          border: Border.all(
            color: applied ? AppColors.black : AppColors.grey200,
            width: applied ? 1.5 : 1,
          ),
        ),
        child: Row(
          children: [
            Icon(
              Icons.stars_rounded,
              size: 22,
              color: applied ? Colors.white : AppColors.black,
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    'Списать $maxRedeem баллов',
                    style: TextStyle(
                      fontSize: 14,
                      fontWeight: FontWeight.w700,
                      color: applied ? Colors.white : AppColors.black,
                    ),
                  ),
                  Text(
                    'Скидка −$maxRedeem ₽ · доступно $balance',
                    style: TextStyle(
                      fontSize: 12,
                      color: applied ? Colors.white60 : AppColors.grey600,
                    ),
                  ),
                ],
              ),
            ),
            // Mono-чекбокс
            Container(
              width: 22,
              height: 22,
              decoration: BoxDecoration(
                color: applied ? Colors.white : Colors.transparent,
                border: Border.all(
                  color: applied ? Colors.white : AppColors.grey400,
                  width: 1.5,
                ),
              ),
              child: applied
                  ? const Icon(Icons.check, size: 16, color: AppColors.black)
                  : null,
            ),
          ],
        ),
      ),
    );
  }
}

class _ReviewRow extends StatelessWidget {
  final String label;
  final String value;
  final bool small;

  const _ReviewRow({
    required this.label,
    required this.value,
    this.small = false,
  });

  @override
  Widget build(BuildContext context) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SizedBox(
          width: 80,
          child: Text(
            label,
            style: TextStyle(
              fontSize: small ? 12 : 13,
              color: AppColors.grey600,
            ),
          ),
        ),
        Expanded(
          child: Text(
            value,
            style: TextStyle(
              fontSize: small ? 12 : 13,
              fontWeight: small ? FontWeight.w400 : FontWeight.w600,
              color: AppColors.black,
            ),
          ),
        ),
      ],
    );
  }
}

// ─── Bottom nav bar ───────────────────────────────────────────────────────────

class _NavBar extends StatelessWidget {
  final int step;
  final bool loading;
  final VoidCallback onBack;
  final VoidCallback onNext;

  const _NavBar({
    required this.step,
    required this.loading,
    required this.onBack,
    required this.onNext,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: EdgeInsets.fromLTRB(
        20,
        12,
        20,
        12 + MediaQuery.of(context).padding.bottom,
      ),
      decoration: const BoxDecoration(
        color: AppColors.white,
        border: Border(top: BorderSide(color: AppColors.grey200)),
      ),
      child: Row(
        children: [
          if (step > 0)
            GestureDetector(
              onTap: onBack,
              child: Container(
                height: 52,
                width: 52,
                decoration: BoxDecoration(
                  border: Border.all(color: AppColors.grey200),
                ),
                child: const Icon(
                  Icons.arrow_back,
                  size: 20,
                  color: AppColors.black,
                ),
              ),
            ),
          if (step > 0) const SizedBox(width: 12),
          Expanded(
            child: GestureDetector(
              onTap: loading ? null : onNext,
              child: AnimatedContainer(
                duration: const Duration(milliseconds: 150),
                height: 52,
                color: loading ? AppColors.grey800 : AppColors.black,
                alignment: Alignment.center,
                child: loading
                    ? const SizedBox(
                        width: 22,
                        height: 22,
                        child: CircularProgressIndicator(
                          color: Colors.white,
                          strokeWidth: 2,
                        ),
                      )
                    : RemoteText(
                        step < 3 ? 'app.checkout.next' : 'app.checkout.confirm',
                        step < 3 ? 'ДАЛЕЕ' : 'ПОДТВЕРДИТЬ ЗАКАЗ',
                        style: TextStyle(
                          fontSize: 15,
                          fontWeight: FontWeight.w600,
                          color: Colors.white,
                          letterSpacing: 2,
                        ),
                      ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

// ─── Shared widgets ───────────────────────────────────────────────────────────

class _StepTitle extends StatelessWidget {
  final String contentKey;
  final String text;
  const _StepTitle(this.contentKey, this.text);

  @override
  Widget build(BuildContext context) {
    return RemoteText(
      contentKey,
      text,
      style: TextStyle(
        fontSize: 20,
        fontWeight: FontWeight.w700,
        letterSpacing: 1,
        color: AppColors.black,
      ),
    );
  }
}

class _Field extends StatefulWidget {
  final TextEditingController ctrl;
  final String label;
  final String hint;
  final IconData icon;
  final TextInputType? type;
  final TextCapitalization cap;

  const _Field({
    required this.ctrl,
    required this.label,
    required this.hint,
    required this.icon,
    this.type,
    this.cap = TextCapitalization.none,
  });

  @override
  State<_Field> createState() => _FieldState();
}

class _FieldState extends State<_Field> {
  bool _focused = false;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          widget.label.toUpperCase(),
          style: const TextStyle(
            fontSize: 10,
            fontWeight: FontWeight.w700,
            letterSpacing: 1.2,
            color: AppColors.grey600,
          ),
        ),
        const SizedBox(height: 6),
        AnimatedContainer(
          duration: const Duration(milliseconds: 200),
          decoration: BoxDecoration(
            border: Border.all(
              color: _focused ? AppColors.black : AppColors.grey200,
              width: _focused ? 1.5 : 1,
            ),
          ),
          child: Focus(
            onFocusChange: (f) => setState(() => _focused = f),
            child: TextField(
              controller: widget.ctrl,
              keyboardType: widget.type,
              textCapitalization: widget.cap,
              style: const TextStyle(fontSize: 15, color: AppColors.black),
              decoration: InputDecoration(
                hintText: widget.hint,
                hintStyle: const TextStyle(
                  color: AppColors.grey400,
                  fontSize: 14,
                ),
                prefixIcon: Icon(
                  widget.icon,
                  size: 18,
                  color: _focused ? AppColors.black : AppColors.grey400,
                ),
                border: InputBorder.none,
                enabledBorder: InputBorder.none,
                focusedBorder: InputBorder.none,
                contentPadding: const EdgeInsets.symmetric(vertical: 14),
              ),
            ),
          ),
        ),
      ],
    );
  }
}

class _ErrorBanner extends StatelessWidget {
  final String message;
  const _ErrorBanner(this.message);

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
      color: const Color(0xFFFFF0F0),
      child: Row(
        children: [
          const Icon(Icons.error_outline, size: 16, color: AppColors.red),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              message,
              style: const TextStyle(fontSize: 13, color: AppColors.red),
            ),
          ),
        ],
      ),
    ).animate().fadeIn(duration: 250.ms).shakeX(hz: 3, amount: 4);
  }
}
