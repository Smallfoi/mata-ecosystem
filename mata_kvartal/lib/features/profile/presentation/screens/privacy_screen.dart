import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../../core/theme/app_colors.dart';
import '../../../auth/data/auth_provider.dart';
import '../../data/account_provider.dart';

/// Приватность и данные (LAUNCH_READINESS §2/§13): видимость + удаление аккаунта.
class PrivacyScreen extends ConsumerStatefulWidget {
  const PrivacyScreen({super.key});

  @override
  ConsumerState<PrivacyScreen> createState() => _PrivacyScreenState();
}

class _PrivacyScreenState extends ConsumerState<PrivacyScreen> {
  bool _deleting = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback(
      (_) => ref.read(accountProvider.notifier).loadPrivacy(),
    );
  }

  Future<void> _confirmDelete() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: AppColors.bgCard,
        title: Text('Удалить аккаунт?',
            style: TextStyle(color: AppColors.textPrimary)),
        content: Text(
          'Это навсегда удалит ваш аккаунт, баллы, территории, заказы, '
          'кроссовки и историю во всей экосистеме. Действие необратимо.',
          style: TextStyle(color: AppColors.textSecondary),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Отмена'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: Text('Удалить', style: TextStyle(color: AppColors.error)),
          ),
        ],
      ),
    );
    if (ok != true) return;

    setState(() => _deleting = true);
    final success = await ref.read(accountProvider.notifier).deleteAccount();
    if (!mounted) return;
    if (success) {
      await ref.read(authProvider.notifier).logout();
      if (mounted) context.go('/auth/phone');
    } else {
      setState(() => _deleting = false);
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Не удалось удалить аккаунт. Проверьте связь.')),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final privacy = ref.watch(accountProvider).privacy;

    return Scaffold(
      backgroundColor: AppColors.bgDark,
      appBar: AppBar(
        backgroundColor: AppColors.bgDark,
        title: const Text('Приватность и данные'),
      ),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            const _SectionTitle('Видимость'),
            const _Hint('По умолчанию всё закрыто — вас и ваши маршруты не видно другим.'),
            _PrivacyToggle(
              icon: CupertinoIcons.person_crop_circle,
              label: 'Открытый профиль',
              subtitle: 'Другие могут видеть ваш профиль',
              value: privacy.profilePublic,
              onChanged: (v) =>
                  ref.read(accountProvider.notifier).setPrivacy(profilePublic: v),
            ),
            _PrivacyToggle(
              icon: CupertinoIcons.map,
              label: 'Показывать маршруты и территории',
              subtitle: 'Ваши пробежки и зоны видны другим',
              value: privacy.routePublic,
              onChanged: (v) =>
                  ref.read(accountProvider.notifier).setPrivacy(routePublic: v),
            ),
            _PrivacyToggle(
              icon: CupertinoIcons.location_solid,
              label: 'Положение в реальном времени',
              subtitle: 'Видно, где вы находитесь сейчас',
              value: privacy.realtimePublic,
              onChanged: (v) =>
                  ref.read(accountProvider.notifier).setPrivacy(realtimePublic: v),
            ),
            const SizedBox(height: 24),
            const _SectionTitle('Данные'),
            const _Hint('Удаление аккаунта стирает все ваши данные без возможности '
                'восстановления (152-ФЗ).'),
            Container(
              decoration: BoxDecoration(
                color: AppColors.bgCard,
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: AppColors.error.withValues(alpha: 0.4)),
              ),
              child: ListTile(
                leading: _deleting
                    ? SizedBox(
                        width: 20,
                        height: 20,
                        child: CircularProgressIndicator(
                            strokeWidth: 2, color: AppColors.error),
                      )
                    : Icon(CupertinoIcons.trash, color: AppColors.error, size: 20),
                title: Text('Удалить аккаунт',
                    style: TextStyle(
                        color: AppColors.error, fontWeight: FontWeight.w700)),
                onTap: _deleting ? null : _confirmDelete,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _SectionTitle extends StatelessWidget {
  final String text;
  const _SectionTitle(this.text);
  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: 6, left: 4),
        child: Text(
          text.toUpperCase(),
          style: TextStyle(
            color: AppColors.textTertiary,
            fontSize: 12,
            fontWeight: FontWeight.w800,
            letterSpacing: 0.5,
          ),
        ),
      );
}

class _Hint extends StatelessWidget {
  final String text;
  const _Hint(this.text);
  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: 12, left: 4, right: 4),
        child: Text(text,
            style: TextStyle(color: AppColors.textTertiary, fontSize: 13)),
      );
}

class _PrivacyToggle extends StatelessWidget {
  final IconData icon;
  final String label;
  final String subtitle;
  final bool value;
  final ValueChanged<bool> onChanged;

  const _PrivacyToggle({
    required this.icon,
    required this.label,
    required this.subtitle,
    required this.value,
    required this.onChanged,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      decoration: BoxDecoration(
        color: AppColors.bgCard,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.separator),
      ),
      child: SwitchListTile(
        secondary: Icon(icon, color: AppColors.textPrimary, size: 20),
        title: Text(label,
            style: TextStyle(
                color: AppColors.textPrimary, fontWeight: FontWeight.w600)),
        subtitle: Text(subtitle,
            style: TextStyle(color: AppColors.textTertiary, fontSize: 12)),
        value: value,
        activeColor: AppColors.electricBlue,
        onChanged: onChanged,
      ),
    );
  }
}
