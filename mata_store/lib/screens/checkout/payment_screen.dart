import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';
import 'package:qr_flutter/qr_flutter.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../data/repositories/order_repository.dart';
import '../../providers/order_provider.dart';
import '../../theme/app_theme.dart';
import '../../widgets/remote_text.dart';

/// Оплата заказа по СБП.
///
/// Заказ уже создан и принят сервером — здесь только деньги. Backend отдаёт
/// ссылку `qr.nspk.ru`: на телефоне она открывает банковское приложение, на
/// широком экране показываем её QR-кодом (сканировать телефоном).
///
/// Статус спрашиваем у сервера сами: уведомление от банка приходит на backend,
/// а не в приложение, и может задержаться. Поэтому опрашиваем раз в три секунды
/// и дополнительно сразу же, как покупатель вернулся из банковского приложения —
/// иначе он смотрит на «ждём оплату» уже после того, как заплатил.
class PaymentScreen extends StatefulWidget {
  final String orderId;

  const PaymentScreen({required this.orderId, super.key});

  @override
  State<PaymentScreen> createState() => _PaymentScreenState();
}

enum _Stage { starting, awaiting, paid, canceled, failed }

class _PaymentScreenState extends State<PaymentScreen>
    with WidgetsBindingObserver {
  _Stage _stage = _Stage.starting;
  PaymentStart? _payment;
  String _error = '';
  Timer? _poll;
  bool _checking = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _start();
  }

  @override
  void dispose() {
    _poll?.cancel();
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    // Вернулись из банковского приложения — проверяем сразу, не дожидаясь тика.
    if (state == AppLifecycleState.resumed && _stage == _Stage.awaiting) {
      _check();
    }
  }

  Future<void> _start() async {
    final orders = context.read<OrderProvider>();
    try {
      final started = await orders.startPayment(widget.orderId);
      if (!mounted) return;
      if (started.status == 'paid') {
        _finish();
        return;
      }
      setState(() {
        _payment = started;
        _stage = _Stage.awaiting;
      });
      _poll = Timer.periodic(const Duration(seconds: 3), (_) => _check());
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _stage = _Stage.failed;
        _error = '$e';
      });
    }
  }

  Future<void> _check() async {
    if (_checking || !mounted) return;
    _checking = true;
    try {
      final status =
          await context.read<OrderProvider>().paymentStatus(widget.orderId);
      if (!mounted) return;
      if (status == 'paid') {
        _finish();
      } else if (status == 'canceled') {
        _poll?.cancel();
        setState(() => _stage = _Stage.canceled);
      }
    } catch (_) {
      // Нет сети или сервер молчит — не шумим, следующий тик попробует снова.
    } finally {
      _checking = false;
    }
  }

  void _finish() {
    _poll?.cancel();
    if (!mounted) return;
    setState(() => _stage = _Stage.paid);
    context.go('/order-success/${widget.orderId}');
  }

  Future<void> _openBank() async {
    final url = _payment?.confirmationUrl ?? '';
    if (url.isEmpty) return;
    final ok = await launchUrl(
      Uri.parse(url),
      mode: LaunchMode.externalApplication,
    );
    if (!ok && mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          // staw-static — служебное сообщение об ошибке, не контент витрины
          content: Text('Не удалось открыть приложение банка'),
          behavior: SnackBarBehavior.floating,
        ),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final wide = MediaQuery.sizeOf(context).width >= 720;
    return Scaffold(
      backgroundColor: AppColors.white,
      appBar: AppBar(
        backgroundColor: AppColors.white,
        elevation: 0,
        leading: IconButton(
          icon: const Icon(Icons.close, color: AppColors.black),
          onPressed: () => context.go('/orders'),
        ),
        title: const RemoteText(
          'app.payment.title',
          'ОПЛАТА',
          upper: true,
          style: TextStyle(
            fontSize: 15,
            fontWeight: FontWeight.w700,
            letterSpacing: 2,
            color: AppColors.black,
          ),
        ),
        centerTitle: true,
      ),
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 32),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: _body(wide),
            ),
          ),
        ),
      ),
    );
  }

  Widget _body(bool wide) {
    switch (_stage) {
      case _Stage.starting:
        return const _Waiting(key: ValueKey('starting'));
      case _Stage.paid:
        return const _Waiting(key: ValueKey('paid'));
      case _Stage.failed:
        return _Problem(
          contentKey: 'app.payment.failed',
          fallback: 'Не удалось начать оплату',
          detail: _error,
          onRetry: () {
            setState(() => _stage = _Stage.starting);
            _start();
          },
        );
      case _Stage.canceled:
        return _Problem(
          contentKey: 'app.payment.canceled',
          fallback: 'Оплата не прошла',
          detail: '',
          onRetry: () {
            setState(() => _stage = _Stage.starting);
            _start();
          },
        );
      case _Stage.awaiting:
        return _Awaiting(
          url: _payment?.confirmationUrl ?? '',
          showQr: wide,
          onPay: _openBank,
          onCheck: _check,
        );
    }
  }
}

class _Waiting extends StatelessWidget {
  const _Waiting({super.key});

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        const SizedBox(
          width: 34,
          height: 34,
          child: CircularProgressIndicator(strokeWidth: 2.4),
        ),
        const SizedBox(height: 20),
        const RemoteText(
          'app.payment.preparing',
          'Готовим оплату…',
          textAlign: TextAlign.center,
          style: TextStyle(fontSize: 15, color: AppColors.grey600),
        ),
      ],
    );
  }
}

class _Awaiting extends StatelessWidget {
  final String url;
  final bool showQr;
  final VoidCallback onPay;
  final VoidCallback onCheck;

  const _Awaiting({
    required this.url,
    required this.showQr,
    required this.onPay,
    required this.onCheck,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          width: 78,
          height: 78,
          decoration: const BoxDecoration(
            color: AppColors.lime,
            shape: BoxShape.circle,
          ),
          child: const Icon(Icons.bolt, size: 40, color: AppColors.black),
        ).animate().scale(duration: 500.ms, curve: Curves.easeOutBack),

        const SizedBox(height: 26),
        const RemoteText(
          'app.payment.sbp.title',
          'ОПЛАТА ПО СБП',
          upper: true,
          textAlign: TextAlign.center,
          style: TextStyle(
            fontSize: 22,
            fontWeight: FontWeight.w700,
            letterSpacing: 1.5,
            color: AppColors.black,
          ),
        ),
        const SizedBox(height: 10),
        RemoteText(
          showQr ? 'app.payment.sbp.hint.qr' : 'app.payment.sbp.hint.phone',
          showQr
              ? 'Отсканируйте код камерой телефона или приложением банка'
              : 'Нажмите «Оплатить» — откроется приложение вашего банка',
          textAlign: TextAlign.center,
          style: const TextStyle(fontSize: 14.5, color: AppColors.grey600),
        ),

        if (showQr && url.isNotEmpty) ...[
          const SizedBox(height: 26),
          Container(
            padding: const EdgeInsets.all(14),
            decoration: BoxDecoration(
              color: AppColors.white,
              border: Border.all(color: AppColors.grey200),
              borderRadius: BorderRadius.circular(18),
            ),
            child: QrImageView(
              data: url,
              size: 208,
              backgroundColor: AppColors.white,
              eyeStyle: const QrEyeStyle(
                eyeShape: QrEyeShape.square,
                color: AppColors.black,
              ),
              dataModuleStyle: const QrDataModuleStyle(
                dataModuleShape: QrDataModuleShape.square,
                color: AppColors.black,
              ),
            ),
          ),
        ],

        const SizedBox(height: 28),
        if (!showQr)
          SizedBox(
            width: double.infinity,
            child: ElevatedButton(
              onPressed: onPay,
              style: ElevatedButton.styleFrom(
                backgroundColor: AppColors.black,
                foregroundColor: AppColors.white,
                minimumSize: const Size(64, 54),
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(14),
                ),
              ),
              child: const RemoteText(
                'app.payment.sbp.pay',
                'ОПЛАТИТЬ',
                upper: true,
                style: TextStyle(
                  fontSize: 15,
                  fontWeight: FontWeight.w700,
                  letterSpacing: 1.4,
                  color: AppColors.white,
                ),
              ),
            ),
          ),

        const SizedBox(height: 18),
        Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const SizedBox(
              width: 15,
              height: 15,
              child: CircularProgressIndicator(strokeWidth: 1.8),
            ),
            const SizedBox(width: 10),
            Flexible(
              child: RemoteText(
                'app.payment.waiting',
                'Ждём подтверждение оплаты',
                style: const TextStyle(fontSize: 13.5, color: AppColors.grey600),
              ),
            ),
          ],
        ),
        const SizedBox(height: 6),
        TextButton(
          onPressed: onCheck,
          child: const RemoteText(
            'app.payment.check',
            'Я оплатил — проверить',
            style: TextStyle(fontSize: 14, color: AppColors.grey800),
          ),
        ),
      ],
    );
  }
}

class _Problem extends StatelessWidget {
  final String contentKey;
  final String fallback;
  final String detail;
  final VoidCallback onRetry;

  const _Problem({
    required this.contentKey,
    required this.fallback,
    required this.detail,
    required this.onRetry,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        const Icon(Icons.error_outline, size: 46, color: AppColors.grey400),
        const SizedBox(height: 18),
        RemoteText(
          contentKey,
          fallback,
          textAlign: TextAlign.center,
          style: const TextStyle(
            fontSize: 19,
            fontWeight: FontWeight.w700,
            color: AppColors.black,
          ),
        ),
        if (detail.isNotEmpty) ...[
          const SizedBox(height: 8),
          Text(
            // staw-static — техническая причина от сервера, не редактируемый текст
            detail,
            textAlign: TextAlign.center,
            style: const TextStyle(fontSize: 13, color: AppColors.grey600),
          ),
        ],
        const SizedBox(height: 22),
        SizedBox(
          width: double.infinity,
          child: ElevatedButton(
            onPressed: onRetry,
            style: ElevatedButton.styleFrom(
              backgroundColor: AppColors.black,
              foregroundColor: AppColors.white,
              minimumSize: const Size(64, 54),
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(14),
              ),
            ),
            child: const RemoteText(
              'app.payment.retry',
              'ПОПРОБОВАТЬ СНОВА',
              upper: true,
              style: TextStyle(
                fontSize: 15,
                fontWeight: FontWeight.w700,
                letterSpacing: 1.4,
                color: AppColors.white,
              ),
            ),
          ),
        ),
        const SizedBox(height: 10),
        TextButton(
          onPressed: () => context.go('/orders'),
          child: const RemoteText(
            'app.payment.later',
            'Оплатить позже',
            style: TextStyle(fontSize: 14, color: AppColors.grey600),
          ),
        ),
      ],
    );
  }
}
