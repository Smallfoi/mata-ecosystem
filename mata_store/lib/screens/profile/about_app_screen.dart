import 'package:flutter/material.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../services/update_checker.dart';
import '../../theme/app_theme.dart';
import '../../widgets/remote_text.dart';

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
          ? 'Не удалось проверить — нет связи с сервером обновлений' // staw-static
          : (latest.versionCode > current
              ? 'Доступна версия ${latest.versionName} (сборка ${latest.versionCode})' // staw-static
              : 'У вас последняя версия'); // staw-static
    });
  }

  Future<void> _open(String url) async {
    await launchUrl(Uri.parse(url), mode: LaunchMode.externalApplication);
  }

  @override
  Widget build(BuildContext context) {
    final version = _info?.version ?? '—';
    final build = _info?.buildNumber ?? '—';
    final hasUpdate = (_latest?.versionCode ?? 0) > (int.tryParse(build) ?? 0);

    return Scaffold(
      backgroundColor: AppColors.white,
      appBar: AppBar(
        title: const RemoteText(
          'app.about.title',
          'О ПРИЛОЖЕНИИ',
          style: TextStyle(
            fontSize: 20,
            fontWeight: FontWeight.w700,
            letterSpacing: 3,
          ),
        ),
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          const SizedBox(height: 8),
          Center(
            child: Column(
              children: [
                Container(
                  width: 64,
                  height: 64,
                  decoration: BoxDecoration(
                    color: AppColors.black,
                    borderRadius: BorderRadius.circular(16),
                  ),
                  child: const Icon(
                    Icons.shopping_bag_outlined,
                    color: AppColors.lime,
                    size: 30,
                  ),
                ),
                const SizedBox(height: 12),
                const RemoteText(
                  'app.about.name',
                  'МАТА STORE',
                  style: TextStyle(
                    fontSize: 22,
                    fontWeight: FontWeight.w800,
                    letterSpacing: 2,
                    color: AppColors.black,
                  ),
                ),
                const SizedBox(height: 4),
                const RemoteText(
                  'app.about.tagline',
                  'Магазин экосистемы МАТА: одежда, обувь, аксессуары',
                  style: TextStyle(fontSize: 14, color: AppColors.grey600),
                  textAlign: TextAlign.center,
                ),
              ],
            ),
          ),
          const SizedBox(height: 24),
          _Card(
            children: [
              _Row(labelKey: 'app.about.version', label: 'Версия', value: version),
              const _Divider(),
              _Row(labelKey: 'app.about.build', label: 'Сборка', value: build),
            ],
          ),
          const SizedBox(height: 12),
          _Card(
            children: [
              ListTile(
                leading: const Icon(
                  Icons.system_update_outlined,
                  color: AppColors.black,
                ),
                title: _checking
                    ? const Text(   // staw-static: служебное состояние кнопки
                        'Проверяю…',
                        style: TextStyle(
                          fontSize: 15,
                          fontWeight: FontWeight.w600,
                          color: AppColors.black,
                        ),
                      )
                    : const RemoteText(
                        'app.about.checkUpdate',
                        'Проверить обновление',
                        style: TextStyle(
                          fontSize: 15,
                          fontWeight: FontWeight.w600,
                          color: AppColors.black,
                        ),
                      ),
                subtitle: _checkNote == null
                    ? null
                    : Text(
                        _checkNote!,
                        style: TextStyle(
                          fontSize: 14,
                          color: hasUpdate
                              ? AppColors.success
                              : AppColors.grey600,
                        ),
                      ),
                onTap: _checking ? null : _check,
              ),
              if (hasUpdate && _latest?.apkUrl != null) ...[
                const _Divider(),
                ListTile(
                  leading: const Icon(
                    Icons.download_outlined,
                    color: AppColors.success,
                  ),
                  title: const RemoteText(
                    'app.about.download',
                    'Скачать новую версию',
                    style: TextStyle(
                      fontSize: 15,
                      fontWeight: FontWeight.w600,
                      color: AppColors.success,
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
                leading: const Icon(
                  Icons.phone_android_outlined,
                  color: AppColors.black,
                ),
                title: const RemoteText(
                  'app.about.testers',
                  'Страница тест-сборок',
                  style: TextStyle(
                    fontSize: 15,
                    fontWeight: FontWeight.w600,
                    color: AppColors.black,
                  ),
                ),
                subtitle: const Text(
                  'mata-club.ru/app.html', // staw-static
                  style: TextStyle(fontSize: 14, color: AppColors.grey600),
                ),
                onTap: () => _open(_testersPage),
              ),
            ],
          ),
          const SizedBox(height: 24),
          const Center(
            child: RemoteText(
              'app.about.footer',
              '© МАТА. Экосистема: Квартал · Store · сайт',
              style: TextStyle(fontSize: 14, color: AppColors.grey600),
            ),
          ),
        ],
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
        color: AppColors.grey100,
        borderRadius: BorderRadius.circular(12),
      ),
      child: Column(children: children),
    );
  }
}

class _Divider extends StatelessWidget {
  const _Divider();

  @override
  Widget build(BuildContext context) =>
      const Divider(height: 1, thickness: 1, color: AppColors.grey200);
}

class _Row extends StatelessWidget {
  final String labelKey;
  final String label;
  final String value;
  const _Row({
    required this.labelKey,
    required this.label,
    required this.value,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          RemoteText(
            labelKey,
            label,
            style: const TextStyle(fontSize: 15, color: AppColors.grey600),
          ),
          Text(
            value,
            style: const TextStyle(
              fontSize: 15,
              fontWeight: FontWeight.w700,
              color: AppColors.black,
            ),
          ),
        ],
      ),
    );
  }
}
