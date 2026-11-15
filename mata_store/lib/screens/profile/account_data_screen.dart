import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../providers/auth_provider.dart';
import '../../theme/app_theme.dart';
import '../../widgets/remote_text.dart';

/// Конфиденциальность и данные (LAUNCH_READINESS §2/§13): видимость профиля
/// (общая настройка аккаунта) + удаление аккаунта. Аккаунт единый с «Кварталом».
class AccountDataScreen extends StatefulWidget {
  const AccountDataScreen({super.key});

  @override
  State<AccountDataScreen> createState() => _AccountDataScreenState();
}

class _AccountDataScreenState extends State<AccountDataScreen> {
  bool _profilePublic = false;
  bool _loading = true;
  bool _deleting = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final value = await context.read<AuthProvider>().getProfilePublic();
    if (!mounted) return;
    setState(() {
      _profilePublic = value;
      _loading = false;
    });
  }

  Future<void> _toggle(bool value) async {
    setState(() => _profilePublic = value); // оптимистично
    final result = await context.read<AuthProvider>().setProfilePublic(value);
    if (mounted) setState(() => _profilePublic = result);
  }

  Future<void> _confirmDelete() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        shape: const RoundedRectangleBorder(borderRadius: BorderRadius.zero),
        title: const RemoteText('app.account.deleteDialog.title', 'Удалить аккаунт?'),
        content: const RemoteText(
          'app.account.deleteDialog.body',
          'Это навсегда удалит ваш аккаунт, баллы, заказы и историю во всей '
          'экосистеме (включая «Квартал»). Действие необратимо.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(false),
            child: const RemoteText('app.account.deleteDialog.cancel', 'Отмена', style: TextStyle(color: AppColors.grey600)),
          ),
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(true),
            child: const RemoteText('app.account.deleteDialog.confirm', 'Удалить', style: TextStyle(color: AppColors.red)),
          ),
        ],
      ),
    );
    if (ok != true || !mounted) return;

    setState(() => _deleting = true);
    final success = await context.read<AuthProvider>().deleteAccount();
    if (!mounted) return;
    if (success) {
      Navigator.of(context).pop(); // назад в профиль (теперь гостевой)
    } else {
      setState(() => _deleting = false);
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Не удалось удалить аккаунт. Проверьте связь.')),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.white,
      appBar: AppBar(
        title: const RemoteText('app.account.title', 'Конфиденциальность и данные'),
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : ListView(
              padding: const EdgeInsets.all(16),
              children: [
                const _SectionTitle('Видимость'),
                Container(
                  decoration: BoxDecoration(
                    border: Border.all(color: AppColors.grey200),
                  ),
                  child: SwitchListTile(
                    title: const RemoteText('app.account.publicProfile', 'Открытый профиль',
                        style: TextStyle(fontWeight: FontWeight.w600)),
                    subtitle: const RemoteText('app.account.publicProfileSub', 'Другие могут видеть ваш профиль в экосистеме'),
                    value: _profilePublic,
                    activeColor: AppColors.black,
                    onChanged: _toggle,
                  ),
                ),
                const Padding(
                  padding: EdgeInsets.only(top: 8, left: 4, right: 4),
                  child: RemoteText(
                    'app.account.privacyHint',
                    'Видимость маршрутов и положения в реальном времени настраивается '
                    'в приложении «Квартал» (аккаунт общий).',
                    style: TextStyle(color: AppColors.grey600, fontSize: 14),
                  ),
                ),
                const SizedBox(height: 28),
                const _SectionTitle('Данные'),
                const Padding(
                  padding: EdgeInsets.only(bottom: 12, left: 4, right: 4),
                  child: Text(
                    'Удаление аккаунта стирает все ваши данные без возможности '
                    'восстановления (152-ФЗ).',
                    style: TextStyle(color: AppColors.grey600, fontSize: 14),
                  ),
                ),
                OutlinedButton.icon(
                  onPressed: _deleting ? null : _confirmDelete,
                  style: OutlinedButton.styleFrom(
                    foregroundColor: AppColors.red,
                    side: const BorderSide(color: AppColors.red),
                    shape: const RoundedRectangleBorder(borderRadius: BorderRadius.zero),
                    padding: const EdgeInsets.symmetric(vertical: 16),
                  ),
                  icon: _deleting
                      ? const SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(
                              strokeWidth: 2, color: AppColors.red),
                        )
                      : const Icon(Icons.delete_outline, size: 20),
                  label: const RemoteText('app.account.deleteAccount', 'Удалить аккаунт',
                      style: TextStyle(fontWeight: FontWeight.w700)),
                ),
              ],
            ),
    );
  }
}

class _SectionTitle extends StatelessWidget {
  final String text;
  const _SectionTitle(this.text);
  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: 8, left: 2),
        child: Text(
          text.toUpperCase(),
          style: const TextStyle(
            color: AppColors.grey600,
            fontSize: 12,
            fontWeight: FontWeight.w800,
            letterSpacing: 0.5,
          ),
        ),
      );
}
