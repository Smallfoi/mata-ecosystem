import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../../../core/services/update_checker.dart';
import '../../../../core/theme/app_colors.dart';
import '../../../../shared/widgets/kvartal_logo.dart';

/// «О приложении»: какая версия стоит у тебя и какая лежит на раздаче.
///
/// Версия берётся из самой сборки (`package_info_plus`), а не из константы в
/// коде: константу забывают поднять, и экран начинает врать. Номер сборки — тот
/// же versionCode, что печатает CI и показывает страница тест-сборок, поэтому
/// тестеру и владельцу видно одно и то же число.
class AboutAppScreen extends StatefulWidget {
  const AboutAppScreen({super.key});

  @override
  State<AboutAppScreen> createState() => _AboutAppScreenState();
}

class _AboutAppScreenState extends State<AboutAppScreen> {
  static const _testersPage = 'https://mata-club.ru/app.html';

  PackageInfo? _info;
  UpdateInfo? _latest;
  bool _checking = false;
  String? _checkNote;

  @override
  void initState() {
    super.initState();
    PackageInfo.fromPlatform().then((i) {
      if (mounted) setState(() => _info = i);
    });
  }

  Future<void> _check() async {
    setState(() {
      _checking = true;
      _checkNote = null;
    });
    final latest = await UpdateChecker.fetchLatest();
    if (!mounted) return;
    final current = int.tryParse(_info?.buildNumber ?? '') ?? 0;
    setState(() {
      _checking = false;
      _latest = latest;
      _checkNote = latest == null
          ? 'Не удалось проверить — нет связи с сервером обновлений'
          : (latest.versionCode > current
              ? 'Доступна версия ${latest.versionName} (сборка ${latest.versionCode})'
              : 'У вас последняя версия');
    });
  }

  Future<void> _open(String url) async {
    await launchUrl(Uri.parse(url), mode: LaunchMode.externalApplication);
  }

  @override
  Widget build(BuildContext context) {
    final version = _info?.version ?? '—';
    final build = _info?.buildNumber ?? '—';
    final hasUpdate =
        (_latest?.versionCode ?? 0) > (int.tryParse(build) ?? 0);

    return Scaffold(
      backgroundColor: AppColors.bgDark,
      appBar: AppBar(
        backgroundColor: AppColors.bgDark,
        title: const Text('О приложении'),
      ),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            const SizedBox(height: 8),
            Center(
              child: Column(
                children: [
                  const KvartalLogoMark(size: 56, animated: false, glow: false),
                  const SizedBox(height: 12),
                  Text(
                    'КВАРТАЛ',
                    style: TextStyle(
                      fontSize: 24,
                      fontWeight: FontWeight.w800,
                      letterSpacing: 1,
                      color: AppColors.textPrimary,
                    ),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    'Бег, территории и баллы экосистемы МАТА',
                    textAlign: TextAlign.center,
                    style: TextStyle(fontSize: 13, color: AppColors.muted),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 24),
            _Card(
              children: [
                _Row(label: 'Версия', value: version),
                const _Divider(),
                _Row(label: 'Сборка', value: build),
              ],
            ),
            const SizedBox(height: 12),
            _Card(
              children: [
                ListTile(
                  contentPadding: const EdgeInsets.symmetric(horizontal: 16),
                  leading: Icon(
                    CupertinoIcons.arrow_down_circle,
                    color: AppColors.textPrimary,
                  ),
                  title: Text(
                    _checking ? 'Проверяю…' : 'Проверить обновление',
                    style: TextStyle(
                      fontSize: 15,
                      fontWeight: FontWeight.w600,
                      color: AppColors.textPrimary,
                    ),
                  ),
                  subtitle: _checkNote == null
                      ? null
                      : Text(
                          _checkNote!,
                          style: TextStyle(
                            fontSize: 13,
                            color: hasUpdate
                                ? AppColors.accentInk
                                : AppColors.muted,
                          ),
                        ),
                  onTap: _checking ? null : _check,
                ),
                if (hasUpdate && _latest?.apkUrl != null) ...[
                  const _Divider(),
                  ListTile(
                    contentPadding: const EdgeInsets.symmetric(horizontal: 16),
                    leading: Icon(
                      CupertinoIcons.cloud_download,
                      color: AppColors.accentInk,
                    ),
                    title: Text(
                      'Скачать новую версию',
                      style: TextStyle(
                        fontSize: 15,
                        fontWeight: FontWeight.w600,
                        color: AppColors.accentInk,
                      ),
                    ),
                    onTap: () => _open(_latest!.apkUrl!),
                  ),
                ],
              ],
            ),
            const SizedBox(height: 12),
            _Card(
              children: [
                ListTile(
                  contentPadding: const EdgeInsets.symmetric(horizontal: 16),
                  leading: Icon(
                    CupertinoIcons.device_phone_portrait,
                    color: AppColors.textPrimary,
                  ),
                  title: Text(
                    'Страница тест-сборок',
                    style: TextStyle(
                      fontSize: 15,
                      fontWeight: FontWeight.w600,
                      color: AppColors.textPrimary,
                    ),
                  ),
                  subtitle: Text(
                    'mata-club.ru/app.html',
                    style: TextStyle(fontSize: 13, color: AppColors.muted),
                  ),
                  onTap: () => _open(_testersPage),
                ),
              ],
            ),
            const SizedBox(height: 24),
            Center(
              child: Text(
                '© МАТА. Экосистема: Квартал · Store · сайт',
                style: TextStyle(fontSize: 12, color: AppColors.muted),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _Card extends StatelessWidget {
  final List<Widget> children;
  const _Card({required this.children});

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        color: AppColors.bgCard,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.separator),
      ),
      child: Column(children: children),
    );
  }
}

class _Divider extends StatelessWidget {
  const _Divider();

  @override
  Widget build(BuildContext context) =>
      Divider(height: 1, thickness: 1, color: AppColors.separator);
}

class _Row extends StatelessWidget {
  final String label;
  final String value;
  const _Row({required this.label, required this.value});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(
            label,
            style: TextStyle(fontSize: 15, color: AppColors.muted),
          ),
          Text(
            value,
            style: TextStyle(
              fontSize: 15,
              fontWeight: FontWeight.w700,
              color: AppColors.textPrimary,
            ),
          ),
        ],
      ),
    );
  }
}
