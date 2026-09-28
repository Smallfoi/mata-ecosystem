import 'package:flutter/foundation.dart' show kReleaseMode;

/// Конфигурация источника данных — по сервисам (walking skeleton).
///
/// Экосистема подключается к общему backend инкрементально: сейчас реальные
/// **Auth + Loyalty** (единый аккаунт и баллы), а Catalog/Order пока на mock.
/// Каждый сервис включается отдельным флагом — это и есть «шагающий скелет».
///
/// Переход сервиса на backend: поднять эндпоинт, включить флаг. Экраны не меняются.
class ApiConfig {
  /// Базовый URL общего backend.
  /// Эмулятор Android: 'http://10.0.2.2:8000/v1'. Реальный телефон: IP ПК в LAN.
  /// Release-сборки → боевой backend; debug → локальный dev.
  /// Переопределить: --dart-define=SPORT_STORE_API_BASE_URL=https://.../v1
  static const String _prodBaseUrl = 'https://api.mata-club.ru/v1';
  static const String _devBaseUrl = 'http://127.0.0.1:8000/v1';
  static const String baseUrl = String.fromEnvironment(
    'SPORT_STORE_API_BASE_URL',
    defaultValue: kReleaseMode ? _prodBaseUrl : _devBaseUrl,
  );

  /// Превью-режим (сборка для админ-превью: flutter build web --dart-define=PREVIEW=1).
  /// Каталог запрашивается с ?preview=1 — показываются и черновики (неопубликованные).
  static const bool preview = bool.fromEnvironment('PREVIEW');

  /// Пропуск к черновикам: сервер отдаёт их только сотруднику. Конструктор
  /// (/admin/merch/) кладёт подписанный токен в адрес фрейма (`?pt=...`), а мы
  /// пересылаем его API как `preview_token`. Вне превью-сборки — пусто.
  static String get previewToken {
    if (!preview) return '';
    try {
      return Uri.base.queryParameters['pt'] ?? '';
    } catch (_) {
      return '';
    }
  }

  /// Per-service rollout. true → реальный API, false → mock.
  static const bool useApiAuth = true;
  static const bool useApiLoyalty = true;
  static const bool useApiCatalog = true;
  static const bool useApiOrder = true;
  static const bool useApiNotifications = true;

  /// Нужен ли вообще HTTP-клиент (хотя бы один сервис на API).
  static bool get anyApi =>
      useApiAuth ||
      useApiLoyalty ||
      useApiCatalog ||
      useApiOrder ||
      useApiNotifications;

  static const Duration timeout = Duration(seconds: 15);

  /// Относительный media-URL (`/media/...`) → абсолютный (origin без `/v1`).
  /// Для серверного аватара (единый для экосистемы). http/пусто — как есть.
  static String resolveMedia(String? url) {
    if (url == null || url.isEmpty || url.startsWith('http')) return url ?? '';
    final origin = baseUrl.replaceFirst(RegExp(r'/v1/?$'), '');
    return url.startsWith('/') ? '$origin$url' : '$origin/$url';
  }

  /// true — это серверный аватар (URL), а не локальный файл устройства (legacy).
  static bool isRemoteAvatar(String? path) =>
      path != null && (path.startsWith('http') || path.startsWith('/media'));
}
