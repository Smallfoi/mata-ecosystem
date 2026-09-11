import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:provider/provider.dart';
import '../../data/api/api_client.dart';
import '../../data/repositories/auth_repository.dart';
import '../../providers/auth_provider.dart';
import '../../theme/app_theme.dart';
import '../../widgets/mata_logo.dart';
import '../../widgets/otp_verify_boxes.dart';
import '../../widgets/phone_mask.dart';
import '../../widgets/remote_text.dart';
import '../profile/legal_documents_screen.dart';

class AuthScreen extends StatefulWidget {
  final bool startWithRegister;
  const AuthScreen({super.key, this.startWithRegister = false});

  @override
  State<AuthScreen> createState() => _AuthScreenState();
}

class _AuthScreenState extends State<AuthScreen> {
  late bool _isLogin;
  bool _reset = false;    // режим «Забыл пароль?» (внутри «Входа»)
  bool _smsSent = false;  // SMS-код отправлен (регистрация/сброс)
  bool _busy = false;
  String? _error;

  // Вход по ТЕЛЕФОН+ПАРОЛЬ; регистрация — телефон+пароль+SMS-подтверждение (#8).
  final _nameCtrl = TextEditingController();
  final _passCtrl = TextEditingController();
  // Маска телефона: образец «912 345-67-89» виден сразу и не исчезает при вводе.
  final _phoneCtrl = PhoneMaskController(
    hintColor: AppColors.black.withValues(alpha: 0.32),
  );

  @override
  void initState() {
    super.initState();
    _isLogin = !widget.startWithRegister;
  }

  @override
  void dispose() {
    _nameCtrl.dispose();
    _passCtrl.dispose();
    _phoneCtrl.dispose();
    super.dispose();
  }

  String get _phone => '+7${_phoneCtrl.text.replaceAll(RegExp(r'\D'), '')}';
  bool get _phoneOk => _phoneCtrl.text.replaceAll(RegExp(r'\D'), '').length >= 10;

  // Переключение Вход/Регистрация — мягкий фейд.
  void _toggle(bool isLogin) {
    setState(() {
      _isLogin = isLogin;
      _reset = false;
      _smsSent = false;
      _error = null;
      _passCtrl.clear();
    });
  }

  void _startReset() {
    setState(() {
      _reset = true;
      _smsSent = false;
      _error = null;
      _passCtrl.clear();
    });
  }

  // ВХОД: телефон + пароль (без OTP).
  Future<void> _submitLogin() async {
    if (_busy) return;
    setState(() {
      _error = null;
      _busy = true;
    });
    final err = await context.read<AuthProvider>().loginByPassword(_phone, _passCtrl.text);
    if (!mounted) return;
    setState(() => _busy = false);
    if (err != null) {
      setState(() => _error = err);
      return;
    }
    await _afterLogin();
  }

  // Запросить SMS-код (регистрация/сброс).
  Future<void> _requestSms() async {
    if (_busy) return;
    setState(() => _error = null);
    if (!_reset && _nameCtrl.text.trim().isEmpty) {
      setState(() => _error = 'Введите имя');
      return;
    }
    if (!_phoneOk) {
      setState(() => _error = 'Введите номер полностью');
      return;
    }
    if (_passCtrl.text.length < 4) {
      setState(() => _error = 'Пароль — минимум 4 символа');
      return;
    }
    setState(() => _busy = true);
    final err = await context.read<AuthProvider>().requestSmsCode(_phone);
    if (!mounted) return;
    setState(() => _busy = false);
    if (err != null) {
      setState(() => _error = err);
      return;
    }
    setState(() => _smsSent = true);
  }

  /// Проверка кода (OtpVerifyBoxes) → регистрация или сброс пароля.
  Future<bool> _verifyCode(String code) async {
    if (mounted) setState(() => _error = null);
    final auth = context.read<AuthProvider>();
    final err = _reset
        ? await auth.resetPasswordByPhone(_phone, code, _passCtrl.text)
        : await auth.registerByPhone(_phone, code, _passCtrl.text, _nameCtrl.text.trim());
    if (err != null) {
      _phoneError = err;
      return false;
    }
    return true;
  }

  String? _phoneError;

  void _onPhoneFailed() {
    if (!mounted) return;
    setState(() => _error = _phoneError ?? 'Не удалось');
  }

  Future<void> _onPhoneVerified() async {
    if (!mounted) return;
    await _afterLogin();
  }

  /// После успешного входа: если есть непринятые обязательные документы —
  /// показываем гейт согласия вместо закрытия экрана. Иначе — закрываем вход.
  Future<void> _afterLogin() async {
    final hasPending = await hasPendingRequiredLegal(
      context.read<ApiClient?>(),
    );
    if (!mounted) return;
    if (hasPending) {
      Navigator.of(context).pushReplacement(
        MaterialPageRoute(builder: (_) => const ConsentGateScreen()),
      );
    } else {
      Navigator.of(context).pop();
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.white,
      body: Column(
        children: [
          _BlackHeader(
            isLogin: _isLogin,
            onToggle: _toggle,
            onClose: () => Navigator.of(context).pop(),
          ),
          Expanded(
            child: SingleChildScrollView(
              padding: const EdgeInsets.fromLTRB(24, 28, 24, 24),
              child: AnimatedSwitcher(
                duration: const Duration(milliseconds: 300),
                switchInCurve: Curves.easeOut,
                switchOutCurve: Curves.easeIn,
                transitionBuilder: (child, anim) => FadeTransition(
                  opacity: anim,
                  child: SlideTransition(
                    position: Tween<Offset>(
                      begin: const Offset(0, 0.05),
                      end: Offset.zero,
                    ).animate(anim),
                    child: child,
                  ),
                ),
                child: (_isLogin && !_reset)
                    ? _LoginForm(
                        key: const ValueKey('login'),
                        phoneCtrl: _phoneCtrl,
                        passCtrl: _passCtrl,
                        error: _error,
                        busy: _busy,
                        onSubmit: _submitLogin,
                        onForgot: _startReset,
                      )
                    : _SmsForm(
                        key: ValueKey(_reset ? 'reset' : 'register'),
                        reset: _reset,
                        nameCtrl: _nameCtrl,
                        phoneCtrl: _phoneCtrl,
                        passCtrl: _passCtrl,
                        error: _error,
                        busy: _busy,
                        smsSent: _smsSent,
                        onRequestSms: _requestSms,
                        onVerify: _verifyCode,
                        onVerified: _onPhoneVerified,
                        onFailed: _onPhoneFailed,
                      ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

// ─── Black header with tabs ───────────────────────────────────────────────────

class _BlackHeader extends StatelessWidget {
  final bool isLogin;
  final ValueChanged<bool> onToggle;
  final VoidCallback onClose;

  const _BlackHeader({
    required this.isLogin,
    required this.onToggle,
    required this.onClose,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      color: AppColors.black,
      child: SafeArea(
        bottom: false,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(24, 8, 24, 0),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Align(
                alignment: Alignment.centerRight,
                child: GestureDetector(
                  onTap: onClose,
                  child: Container(
                    padding: const EdgeInsets.all(6),
                    child: const Icon(
                      Icons.close,
                      color: Colors.white,
                      size: 22,
                    ),
                  ),
                ),
              ),
              const SizedBox(height: 8),
              Center(
                child: MataLogo(
                  width: 168,
                  color: const Color(0xFFE9EAE5),
                  accent: AppColors.lime,
                ),
              ).animate().fadeIn(duration: 400.ms).slideX(begin: -0.1),
              const SizedBox(height: 14),
              RemoteText(
                'app.auth.tagline',
                'Рядом с тобой в любом состоянии',
                textAlign: TextAlign.center,
                style: GoogleFonts.robotoSerif(
                  fontSize: 13,
                  fontStyle: FontStyle.italic,
                  fontWeight: FontWeight.w200,
                  color: AppColors.lavender,
                ),
              ).animate().fadeIn(duration: 400.ms, delay: 60.ms),
              const SizedBox(height: 4),
              RemoteText(
                isLogin
                    ? 'app.auth.subtitleLogin'
                    : 'app.auth.subtitleRegister',
                isLogin
                    ? 'Войдите, чтобы управлять заказами'
                    : 'Создайте аккаунт и получите скидку 10%',
                style: const TextStyle(
                  fontSize: 13,
                  color: Color(0xFF888888),
                  height: 1.4,
                ),
              ).animate().fadeIn(duration: 400.ms, delay: 100.ms),
              const SizedBox(height: 28),
              _TabBar(isLogin: isLogin, onToggle: onToggle),
            ],
          ),
        ),
      ),
    );
  }
}

class _TabBar extends StatelessWidget {
  final bool isLogin;
  final ValueChanged<bool> onToggle;

  const _TabBar({required this.isLogin, required this.onToggle});

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        _Tab(
          labelKey: 'app.auth.tabLogin',
          label: 'ВХОД',
          isActive: isLogin,
          onTap: () => onToggle(true),
        ),
        const SizedBox(width: 28),
        _Tab(
          labelKey: 'app.auth.tabRegister',
          label: 'РЕГИСТРАЦИЯ',
          isActive: !isLogin,
          onTap: () => onToggle(false),
        ),
      ],
    );
  }
}

class _Tab extends StatelessWidget {
  final String labelKey;
  final String label;
  final bool isActive;
  final VoidCallback onTap;

  const _Tab({
    required this.labelKey,
    required this.label,
    required this.isActive,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          RemoteText(
            labelKey,
            label,
            style: TextStyle(
              fontSize: 15,
              fontWeight: FontWeight.w600,
              letterSpacing: 1.5,
              color: isActive ? Colors.white : const Color(0xFF666666),
            ),
          ),
          const SizedBox(height: 6),
          AnimatedContainer(
            duration: const Duration(milliseconds: 250),
            height: 2,
            width: isActive ? label.length * 9.5 : 0,
            color: Colors.white,
          ),
          const SizedBox(height: 2),
        ],
      ),
    );
  }
}

// ─── Login form: вход только по номеру телефона (единый аккаунт) ─────────────

// Основная кнопка формы (с индикатором загрузки).
class _PrimaryButton extends StatelessWidget {
  final String label;
  final bool busy;
  final Future<void> Function() onPressed;
  const _PrimaryButton({required this.label, required this.busy, required this.onPressed});

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 52,
      child: ElevatedButton(
        onPressed: busy ? null : () => onPressed(),
        style: ElevatedButton.styleFrom(
          backgroundColor: AppColors.black,
          foregroundColor: AppColors.white,
          disabledBackgroundColor: AppColors.grey400,
          shape: const RoundedRectangleBorder(),
          elevation: 0,
        ),
        child: busy
            ? const SizedBox(
                width: 20, height: 20,
                child: CircularProgressIndicator(strokeWidth: 2, color: AppColors.white),
              )
            : Text(label.toUpperCase(),
                style: const TextStyle(fontWeight: FontWeight.w700, letterSpacing: 1.2, fontSize: 14)),
      ),
    );
  }
}

// ─── Вход: телефон + пароль (+ «Забыл пароль?») ──────────────────────────────
class _LoginForm extends StatelessWidget {
  final TextEditingController phoneCtrl;
  final TextEditingController passCtrl;
  final String? error;
  final bool busy;
  final Future<void> Function() onSubmit;
  final VoidCallback onForgot;

  const _LoginForm({
    super.key,
    required this.phoneCtrl,
    required this.passCtrl,
    required this.error,
    required this.busy,
    required this.onSubmit,
    required this.onForgot,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const RemoteText(
          'app.auth.phoneHint',
          'Вход по телефону и паролю',
          style: TextStyle(fontSize: 15, fontWeight: FontWeight.w600, letterSpacing: 1.2, color: AppColors.black),
        ),
        const SizedBox(height: 14),
        _InputField(
          controller: phoneCtrl, label: 'Телефон', hint: '', prefixText: '+7 ',
          keyboardType: TextInputType.phone, inputFormatters: const [PhoneMaskFormatter()],
          icon: Icons.phone_outlined,
        ),
        const SizedBox(height: 14),
        _InputField(controller: passCtrl, label: 'Пароль', hint: '', icon: Icons.lock_outline, obscureText: true),
        if (error != null) ...[const SizedBox(height: 12), _ErrorBanner(message: error!)],
        const SizedBox(height: 20),
        _PrimaryButton(label: 'Войти', busy: busy, onPressed: onSubmit),
        const SizedBox(height: 6),
        Center(
          child: TextButton(
            onPressed: onForgot,
            child: const Text('Забыл пароль?', style: TextStyle(color: AppColors.grey600, fontSize: 13)), // staw-static
          ),
        ),
      ],
    );
  }
}

// ─── Регистрация / сброс пароля: поля → SMS-код → OTP V5 ─────────────────────
class _SmsForm extends StatelessWidget {
  final bool reset;
  final TextEditingController nameCtrl;
  final TextEditingController phoneCtrl;
  final TextEditingController passCtrl;
  final String? error;
  final bool busy;
  final bool smsSent;
  final Future<void> Function() onRequestSms;
  final Future<bool> Function(String code) onVerify;
  final VoidCallback onVerified;
  final VoidCallback onFailed;

  const _SmsForm({
    super.key,
    required this.reset,
    required this.nameCtrl,
    required this.phoneCtrl,
    required this.passCtrl,
    required this.error,
    required this.busy,
    required this.smsSent,
    required this.onRequestSms,
    required this.onVerify,
    required this.onVerified,
    required this.onFailed,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (!reset) ...[
          _InputField(
            controller: nameCtrl, label: 'Имя', hint: 'Иван Иванов',
            icon: Icons.person_outline, textCapitalization: TextCapitalization.words,
          ),
          const SizedBox(height: 14),
        ],
        _InputField(
          controller: phoneCtrl, label: 'Телефон', hint: '', prefixText: '+7 ',
          keyboardType: TextInputType.phone, inputFormatters: const [PhoneMaskFormatter()],
          icon: Icons.phone_outlined,
        ),
        const SizedBox(height: 14),
        _InputField(
          controller: passCtrl, label: reset ? 'Новый пароль' : 'Пароль', hint: '',
          icon: Icons.lock_outline, obscureText: true,
        ),
        if (error != null) ...[const SizedBox(height: 12), _ErrorBanner(message: error!)],
        const SizedBox(height: 20),
        if (!smsSent)
          _PrimaryButton(label: 'Получить код', busy: busy, onPressed: onRequestSms)
        else ...[
          // Ввод кода — хореография «OTP V5» (стандарт анимаций экосистемы МАТА).
          OtpVerifyBoxes(
            hasError: error != null,
            onSubmit: onVerify,
            onSuccess: onVerified,
            onFailed: onFailed,
          ),
          const SizedBox(height: 6),
          Center(
            child: Text(
              _codeHint(context.watch<AuthProvider>().codeInfo),
              textAlign: TextAlign.center,
              style: TextStyle(fontSize: 12, color: AppColors.grey400, fontFeatures: const [FontFeature.tabularFigures()]),
            ),
          ),
        ],
        const SizedBox(height: 14),
        const RemoteText(
          'app.auth.consent',
          'Продолжая, вы соглашаетесь с условиями использования и политикой конфиденциальности',
          textAlign: TextAlign.center,
          style: TextStyle(fontSize: 11, color: AppColors.grey400, height: 1.5),
        ),
        const SizedBox(height: 6),
        Center(
          child: GestureDetector(
            onTap: () => Navigator.of(context).push(
              MaterialPageRoute(builder: (_) => const LegalDocumentsScreen()),
            ),
            behavior: HitTestBehavior.opaque,
            child: const Padding(
              padding: EdgeInsets.symmetric(vertical: 4, horizontal: 8),
              child: RemoteText(
                'app.auth.openDocs',
                'Открыть документы',
                style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: AppColors.black, decoration: TextDecoration.underline),
              ),
            ),
          ),
        ),
        const SizedBox(height: 8),
      ],
    );
  }
}

// ─── Shared UI components ─────────────────────────────────────────────────────

class _InputField extends StatefulWidget {
  final TextEditingController controller;
  final String label;
  final String hint;
  final IconData icon;
  final TextInputType? keyboardType;
  final TextCapitalization textCapitalization;
  final String? prefixText;
  final List<TextInputFormatter>? inputFormatters;
  final bool obscureText;

  const _InputField({
    required this.controller,
    required this.label,
    required this.hint,
    required this.icon,
    this.keyboardType,
    this.textCapitalization = TextCapitalization.none,
    this.prefixText,
    this.inputFormatters,
    this.obscureText = false,
  });

  @override
  State<_InputField> createState() => _InputFieldState();
}

class _InputFieldState extends State<_InputField> {
  bool _focused = false;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          widget.label.toUpperCase(),
          style: const TextStyle(
            fontSize: 11,
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
              controller: widget.controller,
              keyboardType: widget.keyboardType,
              textCapitalization: widget.textCapitalization,
              inputFormatters: widget.inputFormatters,
              obscureText: widget.obscureText,
              style: const TextStyle(
                fontSize: 15,
                color: AppColors.black,
                fontWeight: FontWeight.w400,
              ),
              decoration: InputDecoration(
                hintText: widget.hint,
                // Образец в подсказке — ТОТ ЖЕ шрифт/размер, что «+7» и
                // вводимые цифры; «образцовость» передаёт только прозрачность
                // (замечание владельца: высота/размер не должны отличаться).
                hintStyle: TextStyle(
                  color: AppColors.black.withValues(alpha: 0.32),
                  fontSize: 15,
                  fontWeight: FontWeight.w400,
                ),
                // Несъёмный префикс («+7 ») живёт в prefixIcon — в отличие от
                // prefixText он виден ВСЕГДА, а не только при фокусе
                // (замечание владельца). Начертание — как у вводимых цифр.
                prefixIcon: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const SizedBox(width: 12),
                    Icon(
                      widget.icon,
                      size: 18,
                      color: _focused ? AppColors.black : AppColors.grey400,
                    ),
                    if (widget.prefixText != null) ...[
                      const SizedBox(width: 10),
                      Text(
                        widget.prefixText!,
                        style: const TextStyle(
                          fontSize: 15,
                          color: AppColors.black,
                          fontWeight: FontWeight.w400,
                        ),
                      ),
                    ] else
                      const SizedBox(width: 12),
                  ],
                ),
                prefixIconConstraints: const BoxConstraints(
                  minWidth: 44,
                  minHeight: 44,
                ),
                border: InputBorder.none,
                enabledBorder: InputBorder.none,
                focusedBorder: InputBorder.none,
                filled: false,
                contentPadding: const EdgeInsets.symmetric(
                  horizontal: 0,
                  vertical: 14,
                ),
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
  const _ErrorBanner({required this.message});

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

/// Подсказка под полем кода: боевой ли вход и каким каналом придёт код (D-50).
/// Служебный текст, не контент витрины.
String _codeHint(SmsCodeInfo info) {
  if (!info.smsEnabled) return 'Тестовый код: 1234';
  if (info.isCall) return 'Сейчас позвоним — код это последние 4 цифры номера';
  return 'Код отправлен по SMS';
}
