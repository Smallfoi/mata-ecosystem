import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import '../../../../core/theme/app_colors.dart';
import '../../../profile/data/legal_provider.dart';
import '../../data/auth_provider.dart';
import '../widgets/otp_verify_boxes.dart';

class OtpScreen extends ConsumerStatefulWidget {
  const OtpScreen({super.key});

  @override
  ConsumerState<OtpScreen> createState() => _OtpScreenState();
}

class _OtpScreenState extends ConsumerState<OtpScreen> {
  // Совпадает с паузой сервера между кодами (D-76): раньше новый код не дадут.
  static const _resendSeconds = 90;
  int _secondsLeft = _resendSeconds;
  // Канал может смениться сам: если код не ввели за 90 секунд, SIGMA переводит
  // звонок на SimPush, а он бывает бескодовым (D-78). Спрашиваем сервер, пока ждём.
  static const _pollSeconds = 3;
  Timer? _timer;
  Timer? _poll;
  bool _confirming = false;
  String? _localError;
  bool _resending = false;
  bool _toConsent = false;

  @override
  void initState() {
    super.initState();
    _startTimer();
    _startPolling();
  }

  void _startTimer() {
    _secondsLeft = _resendSeconds;
    _timer?.cancel();
    _timer = Timer.periodic(const Duration(seconds: 1), (t) {
      if (!mounted) {
        t.cancel();
        return;
      }
      if (_secondsLeft <= 1) {
        t.cancel();
        setState(() => _secondsLeft = 0);
      } else {
        setState(() => _secondsLeft--);
      }
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    _poll?.cancel();
    super.dispose();
  }

  void _startPolling() {
    // В разработке канала нет вовсе — код всегда 1234, спрашивать нечего.
    if (!ref.read(authProvider).smsEnabled) return;
    _poll = Timer.periodic(const Duration(seconds: _pollSeconds), (t) async {
      if (!mounted) {
        t.cancel();
        return;
      }
      await ref.read(authProvider.notifier).refreshChannel();
      if (!mounted) return;
      final auth = ref.read(authProvider);
      if (auth.codeType == 'codeless' && auth.channelStatus == 'confirmed') {
        t.cancel();
        await _confirmWithoutCode();
      }
    });
  }

  /// Бескодовый канал: человек подтвердил вход на самом телефоне, вводить нечего —
  /// заканчиваем вход пустым кодом, сервер спросит результат у провайдера.
  Future<void> _confirmWithoutCode() async {
    if (_confirming) return;
    setState(() => _confirming = true);
    final ok = await _submit('');
    if (!mounted) return;
    if (ok) {
      _onSuccess();
      return;
    }
    setState(() {
      _confirming = false;
      _localError = ref.read(authProvider).error;
    });
    _startPolling();  // подтверждение ещё не дошло — продолжаем ждать
  }

  /// Проверка кода на сервере; вызывается виджетом OtpVerifyBoxes.
  /// Пока играет разлёт+вращение, здесь успевает пройти verify и (при успехе)
  /// проверка непринятых обязательных документов — гейт согласия.
  Future<bool> _submit(String code) async {
    if (mounted) setState(() => _localError = null);
    final success = await ref.read(authProvider.notifier).completeWithCode(code);
    if (!success) return false;

    // Fail-open: любая ошибка проверки документов не должна запирать вход.
    _toConsent = false;
    final token = ref.read(authProvider).token;
    if (token != null) {
      try {
        final docs = await fetchLegalDocs(token: token);
        _toConsent = pendingRequired(docs).isNotEmpty;
      } catch (_) {
        _toConsent = false;
      }
    }
    return true;
  }

  void _onSuccess() {
    if (!mounted) return;
    context.go(_toConsent ? '/auth/consent' : '/map');
  }

  void _onFailed() {
    if (!mounted) return;
    setState(() => _localError = ref.read(authProvider).error);
  }

  Future<void> _resend() async {
    setState(() {
      _resending = true;
      _localError = null;
    });
    final phone = ref.read(authProvider).phone;
    final sent = await ref.read(authProvider.notifier).sendCode(phone);
    if (!mounted) return;
    setState(() {
      _resending = false;
      if (!sent) _localError = ref.read(authProvider).error;
    });
    if (sent) _startTimer();
  }

  /// Как придёт код: сервер говорит, боевой ли вход и каким каналом (D-50).
  String _codeHint(AuthState auth) {
    if (!auth.smsEnabled) return 'Код отправлен на ${auth.phone}';
    if (auth.codeType == 'codeless') {
      return 'Запрос пришёл на ${auth.phone}. Подтвердите вход на телефоне';
    }
    if (auth.channelType.toLowerCase().contains('call')) {
      return 'Сейчас позвоним на ${auth.phone}. Код — последние 4 цифры номера';
    }
    return 'SMS отправлено на ${auth.phone}';
  }

  @override
  Widget build(BuildContext context) {
    final auth = ref.watch(authProvider);
    final codeless = auth.codeType == 'codeless';

    return Scaffold(
      backgroundColor: AppColors.bgDark,
      appBar: AppBar(
        backgroundColor: Colors.transparent,
        elevation: 0,
        leading: IconButton(
          icon: const Icon(Icons.arrow_back),
          onPressed: () => context.go('/auth/phone'),
        ),
      ),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const SizedBox(height: 16),
              Text(
                codeless ? 'Подтверди вход' : 'Введи код',
                style: Theme.of(context).textTheme.headlineMedium?.copyWith(
                  fontWeight: FontWeight.w800,
                ),
              ),
              const SizedBox(height: 8),
              Text(
                _codeHint(auth),
                style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                  color: AppColors.textSecondary,
                ),
              ),
              const SizedBox(height: 12),
              if (codeless)
                _WaitingOnPhone(busy: _confirming)
              else
                OtpVerifyBoxes(
                  hasError: _localError != null,
                  onSubmit: _submit,
                  onSuccess: _onSuccess,
                  onFailed: _onFailed,
                ),
              if (_localError != null) ...[
                const SizedBox(height: 8),
                Center(
                  child: Text(
                    _localError!,
                    style: TextStyle(
                      color: AppColors.error,
                      fontSize: 14,
                    ),
                  ),
                ),
              ],
              const SizedBox(height: 16),
              if (_resending)
                Center(
                  child: CircularProgressIndicator(
                    color: AppColors.electricBlue,
                  ),
                )
              else if (_secondsLeft > 0)
                Center(
                  child: Text(
                    'Отправить снова через $_secondsLeft с',
                    style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                      color: AppColors.textSecondary,
                    ),
                  ),
                )
              else
                Center(
                  child: TextButton(
                    onPressed: _resend,
                    child: const Text('Отправить снова'),
                  ),
                ),
              const Spacer(),
              // Тестовый код — только пока вход не боевой: с настоящим звонком 1234 не пройдёт.
              if (!auth.smsEnabled)
              Center(
                child: Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 14,
                    vertical: 8,
                  ),
                  decoration: BoxDecoration(
                    color: AppColors.bgCard,
                    borderRadius: BorderRadius.circular(10),
                    border: Border.all(color: AppColors.bgElevated),
                  ),
                  child: Text(
                    'Тестовый код: 1234',
                    style: TextStyle(
                      color: AppColors.textDisabled,
                      fontSize: 13,
                      fontFamily: 'monospace',
                    ),
                  ),
                ),
              ),
              const SizedBox(height: 24),
            ],
          ),
        ),
      ),
    );
  }
}

/// Бескодовый канал (SimPush): подтверждение приходит на сам телефон, поля кода нет.
class _WaitingOnPhone extends StatelessWidget {
  const _WaitingOnPhone({required this.busy});

  final bool busy;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 22),
      decoration: BoxDecoration(
        color: AppColors.bgCard,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AppColors.bgElevated),
      ),
      child: Row(
        children: [
          SizedBox(
            width: 26,
            height: 26,
            child: CircularProgressIndicator(
              strokeWidth: 2.4,
              color: AppColors.electricBlue,
            ),
          ),
          const SizedBox(width: 16),
          Expanded(
            child: Text(
              busy
                  ? 'Проверяем подтверждение…'
                  : 'Подтвердите вход на телефоне — запрос уже пришёл',
              style: Theme.of(context).textTheme.bodyMedium,
            ),
          ),
        ],
      ),
    );
  }
}
