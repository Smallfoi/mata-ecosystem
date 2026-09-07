import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../../../../core/theme/app_colors.dart';
import '../../../../core/theme/app_theme.dart';
import '../../../../shared/widgets/kvartal_logo.dart';
import '../../../../shared/widgets/phone_mask.dart';
import '../../../profile/data/legal_provider.dart';
import '../../../profile/presentation/screens/legal_documents_screen.dart';
import '../../data/auth_provider.dart';
import 'welcome_screen.dart';

class PhoneScreen extends ConsumerStatefulWidget {
  const PhoneScreen({super.key});

  @override
  ConsumerState<PhoneScreen> createState() => _PhoneScreenState();
}

class _PhoneScreenState extends ConsumerState<PhoneScreen> {
  final _phoneCtrl = PhoneMaskController(hintColor: AppColors.disabled);

  @override
  void initState() {
    super.initState();
    // Ф3 «Вход в игру»: до первого логина — обещание и механика.
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      final prefs = await SharedPreferences.getInstance();
      if (!mounted) return;
      if (!(prefs.getBool(kWelcomeSeenKey) ?? false)) {
        context.go('/auth/welcome');
      }
    });
  }

  final _passCtrl = TextEditingController();
  final _nameCtrl = TextEditingController();
  String _mode = 'login'; // login | register | reset
  bool _obscure = true;

  @override
  void dispose() {
    _phoneCtrl.dispose();
    _passCtrl.dispose();
    _nameCtrl.dispose();
    super.dispose();
  }

  bool get _phoneOk => _phoneCtrl.text.replaceAll(RegExp(r'\D'), '').length == 10;
  String get _phone => '+7${_phoneCtrl.text.replaceAll(RegExp(r'\D'), '')}';

  void _setMode(String m) => setState(() {
        _mode = m;
        _passCtrl.clear();
      });

  Future<void> _submit() async {
    final auth = ref.read(authProvider.notifier);
    if (_mode == 'login') {
      if (!_phoneOk || _passCtrl.text.isEmpty) return;
      final ok = await auth.loginByPassword(_phone, _passCtrl.text);
      if (!ok || !mounted) return;
      // Роутер намеренно не уводит с /auth (гейт согласия решается здесь),
      // поэтому навигируем сами — как OTP-экран.
      var toConsent = false;
      final token = ref.read(authProvider).token;
      if (token != null) {
        try {
          final docs = await fetchLegalDocs(token: token);
          toConsent = pendingRequired(docs).isNotEmpty;
        } catch (_) {}
      }
      if (mounted) context.go(toConsent ? '/auth/consent' : '/map');
      return;
    }
    if (!_phoneOk || _passCtrl.text.length < 4) return;
    if (_mode == 'register' && _nameCtrl.text.trim().isEmpty) return;
    auth.setPending(purpose: _mode, name: _nameCtrl.text.trim(), password: _passCtrl.text);
    await auth.sendCode(_phone);
    if (mounted) context.go('/auth/otp');
  }

  /// Оформление поля — язык сайта: белая заливка, тонкая рамка `line`, на фокусе
  /// акцент. Без тяжёлых рамок и внутренних разделителей.
  InputDecoration _dec(
    String hint, {
    Widget? prefixIcon,
    Widget? suffixIcon,
  }) {
    OutlineInputBorder b(Color c, double w) => OutlineInputBorder(
          borderRadius: BorderRadius.circular(14),
          borderSide: BorderSide(color: c, width: w),
        );
    return InputDecoration(
      hintText: hint,
      hintStyle: TextStyle(color: AppColors.disabled),
      filled: true,
      fillColor: AppColors.panel,
      prefixIcon: prefixIcon,
      prefixIconConstraints: const BoxConstraints(minWidth: 0, minHeight: 0),
      suffixIcon: suffixIcon,
      isDense: true,
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 18),
      enabledBorder: b(AppColors.line, 1),
      border: b(AppColors.line, 1),
      focusedBorder: b(AppColors.accentInk, 1.6),
    );
  }

  @override
  Widget build(BuildContext context) {
    final auth = ref.watch(authProvider);
    final isLoading = auth.isLoading;
    final canSubmit = _mode == 'login'
        ? (_phoneOk && _passCtrl.text.isNotEmpty)
        : (_phoneOk &&
            _passCtrl.text.length >= 4 &&
            (_mode != 'register' || _nameCtrl.text.trim().isNotEmpty));
    final inputStyle = Theme.of(context)
        .textTheme
        .titleMedium
        ?.copyWith(color: AppColors.ink);

    return Scaffold(
      backgroundColor: AppColors.bg,
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const SizedBox(height: 24),
              // Знак как иконка приложения: тёмный бейдж, лаймовая территория —
              // видно на молочном фоне и читается ядовито-зелёным.
              Container(
                width: 76,
                height: 76,
                decoration: BoxDecoration(
                  color: AppColors.graphite,
                  borderRadius: BorderRadius.circular(22),
                  boxShadow: [
                    BoxShadow(
                      color: AppColors.graphite.withValues(alpha: 0.18),
                      blurRadius: 24,
                      offset: const Offset(0, 10),
                    ),
                  ],
                ),
                child: Center(
                  child: KvartalLogoMark(
                    size: 46,
                    outline: AppColors.onDark,
                    fill: AppColors.lime,
                    animated: false,
                  ),
                ),
              ),
              const SizedBox(height: 20),
              Text(
                'КВАРТАЛ',
                style: Theme.of(context).textTheme.displayMedium?.copyWith(
                      fontFamily: AppTheme.fontDisplay,
                      color: AppColors.ink,
                      fontWeight: FontWeight.w800,
                      letterSpacing: 2,
                    ),
              ),
              const SizedBox(height: 8),
              Text(
                _mode == 'login'
                    ? 'Вход по телефону и паролю'
                    : _mode == 'register'
                        ? 'Регистрация'
                        : 'Сброс пароля',
                style: Theme.of(context).textTheme.bodyLarge?.copyWith(color: AppColors.muted),
              ),
              const SizedBox(height: 28),
              if (_mode == 'register') ...[
                TextField(
                  controller: _nameCtrl,
                  style: inputStyle,
                  decoration: _dec('Имя'),
                  onChanged: (_) => setState(() {}),
                ),
                const SizedBox(height: 12),
              ],
              TextField(
                controller: _phoneCtrl,
                keyboardType: TextInputType.phone,
                inputFormatters: const [PhoneMaskFormatter()],
                style: inputStyle?.copyWith(letterSpacing: 1.5),
                decoration: _dec(
                  '', // подсказку-маску рисует сам PhoneMaskController
                  prefixIcon: Padding(
                    padding: const EdgeInsets.fromLTRB(16, 0, 10, 0),
                    child: Text('+7', style: inputStyle?.copyWith(fontWeight: FontWeight.w600)),
                  ),
                ),
                onChanged: (_) => setState(() {}),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: _passCtrl,
                obscureText: _obscure,
                style: inputStyle,
                decoration: _dec(
                  _mode == 'reset' ? 'Новый пароль' : 'Пароль',
                  suffixIcon: IconButton(
                    icon: Icon(
                      _obscure ? Icons.visibility_off_outlined : Icons.visibility_outlined,
                      color: AppColors.muted,
                      size: 22,
                    ),
                    onPressed: () => setState(() => _obscure = !_obscure),
                    tooltip: _obscure ? 'Показать пароль' : 'Скрыть пароль',
                  ),
                ),
                onChanged: (_) => setState(() {}),
              ),
              if (auth.error != null) ...[
                const SizedBox(height: 12),
                Text(auth.error!, style: TextStyle(color: AppColors.error, fontSize: 13)),
              ],
              const SizedBox(height: 22),
              SizedBox(
                width: double.infinity,
                height: 56,
                child: FilledButton(
                  onPressed: canSubmit && !isLoading ? _submit : null,
                  child: isLoading
                      ? const SizedBox(width: 24, height: 24, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                      : Text(_mode == 'login' ? 'Войти' : 'Получить SMS-код',
                          style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
                ),
              ),
              const SizedBox(height: 12),
              if (_mode == 'login') ...[
                Center(child: TextButton(onPressed: () => _setMode('register'), child: Text('Нет аккаунта? Регистрация', style: TextStyle(color: AppColors.accentInk)))),
                Center(child: TextButton(onPressed: () => _setMode('reset'), child: Text('Забыл пароль?', style: TextStyle(color: AppColors.muted)))),
              ] else
                Center(child: TextButton(onPressed: () => _setMode('login'), child: Text('Уже есть аккаунт? Войти', style: TextStyle(color: AppColors.accentInk)))),
              const SizedBox(height: 8),
              Center(
                child: GestureDetector(
                  onTap: () => Navigator.of(context).push(
                    MaterialPageRoute(builder: (_) => const LegalDocumentsScreen()),
                  ),
                  behavior: HitTestBehavior.opaque,
                  child: Text(
                    'Условия использования и документы',
                    textAlign: TextAlign.center,
                    style: Theme.of(context).textTheme.bodySmall?.copyWith(
                          color: AppColors.disabled,
                          decoration: TextDecoration.underline,
                        ),
                  ),
                ),
              ),
              const SizedBox(height: 16),
            ],
          ),
        ),
      ),
    );
  }
}
