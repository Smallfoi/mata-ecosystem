import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:url_launcher/url_launcher.dart';

import '../theme/app_colors.dart';

/// Проверка обновлений тест-сборки (Android).
///
/// Сравнивает versionCode приложения с version.json в S3 (его пишет CI при
/// каждом релизе). Если на сервере версия новее — показывает баннер со ссылкой
/// на скачивание нового APK. Не критичная фича: любая ошибка/офлайн — тихо
/// пропускаем. iOS обновляется через TestFlight, поэтому проверка только Android.
/// Что лежит на раздаче: версия, номер сборки и ссылка на APK.
class UpdateInfo {
  final String versionName;
  final int versionCode;
  final String? apkUrl;
  const UpdateInfo({
    required this.versionName,
    required this.versionCode,
    this.apkUrl,
  });
}

class UpdateChecker {
  static const _versionUrl =
      'https://storage.yandexcloud.net/mata-media/app/kvartal/version.json';
  static const _prefsDismissedCode = 'update_dismissed_code';
  static bool _checkedThisSession = false;

  /// Читает version.json с раздачи. null — нет связи/ответ не разобран.
  /// Используют и баннер обновления, и экран «О приложении».
  static Future<UpdateInfo?> fetchLatest() async {
    try {
      final resp = await Dio().get<Map<String, dynamic>>(
        _versionUrl,
        queryParameters: {'t': DateTime.now().millisecondsSinceEpoch},
        options: Options(
          responseType: ResponseType.json,
          receiveTimeout: const Duration(seconds: 6),
          sendTimeout: const Duration(seconds: 6),
        ),
      );
      final data = resp.data;
      if (resp.statusCode != 200 || data == null) return null;
      return UpdateInfo(
        versionName: (data['versionName'] as String?) ?? '',
        versionCode: (data['versionCode'] as num?)?.toInt() ?? 0,
        apkUrl: (data['latestUrl'] ?? data['apkUrl']) as String?,
      );
    } catch (_) {
      return null;
    }
  }

  static Future<void> check(BuildContext context) async {
    if (_checkedThisSession) return;
    _checkedThisSession = true;
    if (Theme.of(context).platform != TargetPlatform.android) return;

    try {
      final info = await PackageInfo.fromPlatform();
      final current = int.tryParse(info.buildNumber) ?? 0;

      final latest = await fetchLatest();
      if (latest == null) return;
      final apkUrl = latest.apkUrl;
      if (latest.versionCode <= current || apkUrl == null) return;

      final prefs = await SharedPreferences.getInstance();
      if (prefs.getInt(_prefsDismissedCode) == latest.versionCode) return;

      if (!context.mounted) return;
      _showBanner(context, latest.versionName, apkUrl, latest.versionCode, prefs);
    } catch (_) {
      // тихо — обновление не должно ломать запуск
    }
  }

  static void _showBanner(
    BuildContext context,
    String versionName,
    String apkUrl,
    int code,
    SharedPreferences prefs,
  ) {
    final messenger = ScaffoldMessenger.of(context);
    messenger.showMaterialBanner(
      MaterialBanner(
        backgroundColor: AppColors.bgSurface,
        leading: Icon(Icons.system_update, color: AppColors.accent),
        content: Text(
          versionName.isNotEmpty
              ? 'Доступна новая версия $versionName. Обновить приложение?'
              : 'Доступно обновление приложения. Обновить?',
          style: TextStyle(color: AppColors.ink),
        ),
        actions: [
          TextButton(
            onPressed: () {
              prefs.setInt(_prefsDismissedCode, code);
              messenger.hideCurrentMaterialBanner();
            },
            child: Text('Позже', style: TextStyle(color: AppColors.muted)),
          ),
          TextButton(
            onPressed: () async {
              messenger.hideCurrentMaterialBanner();
              await launchUrl(
                Uri.parse(apkUrl),
                mode: LaunchMode.externalApplication,
              );
            },
            child:
                Text('Обновить', style: TextStyle(color: AppColors.accent)),
          ),
        ],
      ),
    );
  }
}
