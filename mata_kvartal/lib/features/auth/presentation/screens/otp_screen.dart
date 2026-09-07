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
  int _secondsLeft = 60;
  Timer? _timer;
  String? _localError;
  bool _resending = false;
  bool _toConsent = false;

  @override
  void initState() {
    super.initState();
    _startTimer();
  }

  void _startTimer() {
    _secondsLeft = 60;
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
    super.dispose();
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
    setState(() => _resending = true);
    final phone = ref.read(authProvider).phone;
    await ref.read(authProvider.notifier).sendCode(phone);
    if (!mounted) return;
    setState(() => _resending = false);
    _startTimer();
  }

  @override
  Widget build(BuildContext context) {
    final auth = ref.watch(authProvider);

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
                'Введи код',
                style: Theme.of(context).textTheme.headlineMedium?.copyWith(
                  fontWeight: FontWeight.w800,
                ),
              ),
              const SizedBox(height: 8),
              Text(
                'SMS отправлено на ${auth.phone}',
                style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                  color: AppColors.textSecondary,
                ),
              ),
              const SizedBox(height: 12),
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
