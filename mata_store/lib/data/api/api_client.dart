import 'dart:convert';
import 'package:http/http.dart' as http;
import 'package:http_parser/http_parser.dart' show MediaType;
import 'package:sentry_flutter/sentry_flutter.dart';
import 'api_config.dart';

/// Тонкая обёртка над HTTP для общения с backend.
///
/// Используется реальными `Api*Repository`. Добавляет базовый URL, заголовки,
/// таймаут и разбор JSON. Аутентификация (токен) подставляется через [authToken].
class ApiException implements Exception {
  final int statusCode;
  final String message;
  ApiException(this.statusCode, this.message);

  /// В текст исключения тело ответа НЕ кладём (D-32).
  ///
  /// Именно `toString()` уезжает в трекер ошибок, когда исключение никто не
  /// поймал. А в теле ответа сервера бывает всё: телефон, почта, адрес заказа.
  /// Для показа пользователю и разбора в коде есть поле `message` — оно осталось
  /// нетронутым; наружу уходит только код ответа, которого для диагностики
  /// достаточно.
  @override
  String toString() => 'ApiException($statusCode)';
}

/// Путь без идентификаторов: `/orders/1042` → `/orders/…`.
///
/// Номер заказа в крошке — и данные пользователя, и помеха: трекер разбил бы
/// одну ошибку на сотни карточек, по одной на каждый номер.
String _routeOf(Uri? url) {
  if (url == null) return '?';
  return url.path
      .split('/')
      .map((seg) => seg.isNotEmpty &&
              (RegExp(r'^\d+$').hasMatch(seg) ||
                  RegExp(r'^[0-9a-fA-F_\-]{8,}$').hasMatch(seg))
          ? '…'
          : seg)
      .join('/');
}

class ApiClient {
  final http.Client _client;
  String? _authToken;

  /// Вызывается при изменении токена — для персиста JWT (см. main.dart).
  void Function(String? token)? onTokenChanged;

  /// Вызывается, когда сервер отверг токен (401 при наличии токена) — сессия
  /// истекла/недействительна. Подписчик (AuthProvider через main.dart) должен
  /// выйти из аккаунта и предложить войти заново. Без этого протухший токен
  /// «залипает»: приложение думает, что залогинено, и молча ловит 401 везде.
  void Function()? onUnauthorized;

  ApiClient({http.Client? client}) : _client = client ?? http.Client();

  String? get authToken => _authToken;
  set authToken(String? value) {
    _authToken = value;
    onTokenChanged?.call(value);
  }

  Map<String, String> get _headers => {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        if (authToken != null) 'Authorization': 'Bearer $authToken',
      };

  Uri _uri(String path, [Map<String, dynamic>? query]) {
    final base = Uri.parse('${ApiConfig.baseUrl}$path');
    if (query == null || query.isEmpty) return base;
    return base.replace(
      queryParameters: query.map((k, v) => MapEntry(k, '$v')),
    );
  }

  Future<dynamic> get(String path, {Map<String, dynamic>? query}) async {
    final res = await _client
        .get(_uri(path, query), headers: _headers)
        .timeout(ApiConfig.timeout);
    return _decode(res);
  }

  Future<dynamic> post(String path, {Object? body}) async {
    final res = await _client
        .post(_uri(path), headers: _headers, body: jsonEncode(body))
        .timeout(ApiConfig.timeout);
    return _decode(res);
  }

  Future<dynamic> put(String path, {Object? body}) async {
    final res = await _client
        .put(_uri(path), headers: _headers, body: jsonEncode(body))
        .timeout(ApiConfig.timeout);
    return _decode(res);
  }

  Future<dynamic> patch(String path, {Object? body}) async {
    final res = await _client
        .patch(_uri(path), headers: _headers, body: jsonEncode(body))
        .timeout(ApiConfig.timeout);
    return _decode(res);
  }

  Future<dynamic> delete(String path) async {
    final res = await _client
        .delete(_uri(path), headers: _headers)
        .timeout(ApiConfig.timeout);
    return _decode(res);
  }

  /// Multipart-загрузка файла (поле `image`) — для серверного аватара.
  Future<dynamic> uploadImage(String path, String filePath) async {
    final req = http.MultipartRequest('POST', _uri(path));
    if (authToken != null) {
      req.headers['Authorization'] = 'Bearer $authToken';
    }
    // Явный Content-Type картинки: пакет `http` иначе шлёт
    // `application/octet-stream`, и backend (проверяет `image/*`) отклоняет
    // загрузку аватара 400-ой. Тип определяем по расширению файла.
    req.files.add(await http.MultipartFile.fromPath(
      'image',
      filePath,
      contentType: _imageMediaType(filePath),
    ));
    final streamed = await req.send().timeout(ApiConfig.timeout);
    return _decode(await http.Response.fromStream(streamed));
  }

  MediaType _imageMediaType(String filePath) {
    final ext = filePath.toLowerCase().split('.').last;
    switch (ext) {
      case 'png':
        return MediaType('image', 'png');
      case 'webp':
        return MediaType('image', 'webp');
      case 'gif':
        return MediaType('image', 'gif');
      case 'heic':
        return MediaType('image', 'heic');
      default:
        return MediaType('image', 'jpeg');
    }
  }

  dynamic _decode(http.Response res) {
    _breadcrumb(res);
    if (res.statusCode >= 200 && res.statusCode < 300) {
      if (res.body.isEmpty) return null;
      return jsonDecode(utf8.decode(res.bodyBytes));
    }
    // Токен есть, но сервер вернул 401 → он недействителен/протух. Сообщаем
    // подписчику (авто-выход), только когда токен был — иначе это просто
    // запрос гостя к защищённому эндпоинту, а не «истёкшая сессия».
    if (res.statusCode == 401 && authToken != null) {
      onUnauthorized?.call();
    }
    throw ApiException(res.statusCode, res.body);
  }

  /// След запроса для карточки ошибки (D-32): куда ходили и что ответили.
  /// Ни тела, ни заголовков, ни параметров — только маршрут, метод и код.
  void _breadcrumb(http.Response res) {
    try {
      final ok = res.statusCode >= 200 && res.statusCode < 300;
      final method = res.request?.method ?? 'GET';
      final route = _routeOf(res.request?.url);
      Sentry.addBreadcrumb(Breadcrumb(
        type: 'http',
        category: 'http',
        level: ok ? SentryLevel.info : SentryLevel.error,
        message: '$method $route → ${res.statusCode}',
        data: {
          'endpoint': route,
          'method': method,
          'status': res.statusCode,
        },
      ));
    } catch (_) {
      // трекер не настроен — крошка не обязана работать
    }
  }

  void close() => _client.close();
}
