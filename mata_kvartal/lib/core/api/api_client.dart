import 'package:dio/dio.dart';
import 'package:sentry_flutter/sentry_flutter.dart';

import 'api_config.dart';

/// Единая точка создания Dio (D-32).
///
/// Раньше каждый провайдер собирал себе свой `Dio(BaseOptions(...))` — двадцать
/// с лишним одинаковых копий. Это работало, но означало, что любое общее
/// поведение (перехватчик, заголовок, таймаут) пришлось бы дописывать двадцать
/// раз и один раз забыть.
///
/// Сейчас общее поведение ровно одно: **хлебные крошки для трекера ошибок**.
/// Без них падение в приложении выглядит как «упало где-то»; с ними в карточке
/// ошибки видно последние запросы — куда ходили, что ответили, сколько ждали.
/// Это половина работы по поиску причины.
///
/// Что НЕ попадает в крошку: тело запроса и ответа, заголовки, параметры строки
/// запроса. Там живут телефоны, токены и адреса — в трекер ошибок им нельзя
/// (152-ФЗ, та же причина, что и у вычистки на бэкенде).
class ApiClient {
  ApiClient._();

  /// Dio с общими настройками и крошками. Заменяет ручной `Dio(BaseOptions(...))`.
  static Dio create({Map<String, String>? headers}) {
    final dio = Dio(
      BaseOptions(
        baseUrl: ApiConfig.baseUrl,
        connectTimeout: ApiConfig.connectTimeout,
        receiveTimeout: ApiConfig.receiveTimeout,
        headers: headers ??
            const {'Content-Type': 'application/json', 'Connection': 'close'},
      ),
    );
    dio.interceptors.add(_BreadcrumbInterceptor());
    return dio;
  }
}

/// Путь без параметров: `/runs/abc123` → `/runs/…`.
///
/// Идентификаторы в адресе мешают дважды: во-первых, это данные пользователя,
/// во-вторых, трекер сгруппировал бы одну и ту же ошибку в сотни разных — по
/// одной на каждый id. Схлопываем, чтобы группировка шла по маршруту.
String _routeOf(String path) {
  final noQuery = path.split('?').first;
  return noQuery
      .split('/')
      .map((seg) {
        if (seg.isEmpty) return seg;
        final looksLikeId = RegExp(r'^[0-9a-fA-F_\-]{8,}$').hasMatch(seg) ||
            RegExp(r'^\d+$').hasMatch(seg);
        return looksLikeId ? '…' : seg;
      })
      .join('/');
}

class _BreadcrumbInterceptor extends Interceptor {
  @override
  void onResponse(Response<dynamic> response, ResponseInterceptorHandler handler) {
    _add(
      route: _routeOf(response.requestOptions.path),
      method: response.requestOptions.method,
      status: response.statusCode,
      level: SentryLevel.info,
    );
    handler.next(response);
  }

  @override
  void onError(DioException err, ErrorInterceptorHandler handler) {
    _add(
      route: _routeOf(err.requestOptions.path),
      method: err.requestOptions.method,
      status: err.response?.statusCode,
      // Тип ошибки Dio отличает «сервер ответил 500» от «сеть не дошла» —
      // при разборе это первое, что нужно знать.
      dioType: err.type.name,
      level: SentryLevel.error,
    );
    handler.next(err);
  }

  void _add({
    required String route,
    required String method,
    int? status,
    String? dioType,
    required SentryLevel level,
  }) {
    // Сбой крошки не должен ронять сетевой запрос — она вспомогательная.
    try {
      Sentry.addBreadcrumb(
        Breadcrumb(
          type: 'http',
          category: 'http',
          level: level,
          message: '$method $route${status == null ? '' : ' → $status'}',
          data: {
            'endpoint': route,
            'method': method,
            if (status != null) 'status': status,
            if (dioType != null) 'dio_type': dioType,
          },
        ),
      );
    } catch (_) {
      // молча: трекер не настроен или ещё не поднялся
    }
  }
}
