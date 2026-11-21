import 'package:dio/dio.dart';
import 'package:sentry_flutter/sentry_flutter.dart';

import 'api_config.dart';
import 'shared_adapter_web.dart'
    if (dart.library.io) 'shared_adapter_io.dart';

/// Единая точка создания Dio (D-32).
///
/// Раньше каждый провайдер собирал себе свой `Dio(BaseOptions(...))` — двадцать
/// с лишним одинаковых копий. Это работало, но означало, что любое общее
/// поведение (перехватчик, заголовок, таймаут) пришлось бы дописывать двадцать
/// раз и один раз забыть.
///
/// Общее поведение:
/// - **один пул соединений** (21.11.2026, этап 2 оптимизации). Раньше у каждого
///   из ~30 Dio был свой пул, а заголовок `Connection: close` запрещал повторно
///   использовать соединение вовсе: каждый запрос платил новое TCP+TLS-рукопожатие
///   до сервера в Москве — 200–400 мс из Якутска. Теперь все Dio делят один
///   адаптер, соединение живёт и переиспользуется;
/// - **повтор GET при обрыве** соединения (один раз): страховка, ради которой когда-то
///   и ставили `Connection: close` (PITFALLS «Dio + keep-alive поверх adb reverse»);
/// - **хлебные крошки для трекера ошибок**.
/// Без них падение в приложении выглядит как «упало где-то»; с ними в карточке
/// ошибки видно последние запросы — куда ходили, что ответили, сколько ждали.
/// Это половина работы по поиску причины.
///
/// Что НЕ попадает в крошку: тело запроса и ответа, заголовки, параметры строки
/// запроса. Там живут телефоны, токены и адреса — в трекер ошибок им нельзя
/// (152-ФЗ, та же причина, что и у вычистки на бэкенде).
class ApiClient {
  ApiClient._();

  /// Общий адаптер (пул соединений) для всех Dio приложения.
  static final HttpClientAdapter _adapter = createSharedAdapter();

  /// Dio с общими настройками и крошками. Заменяет ручной `Dio(BaseOptions(...))`.
  ///
  /// [baseUrl] — для сторонних сервисов (погода); по умолчанию — наш API.
  static Dio create({Map<String, String>? headers, String? baseUrl}) {
    // `Connection` из переданных заголовков выкидываем: закрывать соединение после
    // каждого запроса — ровно то, от чего мы ушли (см. выше).
    final clean = Map<String, String>.of(
      headers ?? const {'Content-Type': 'application/json'},
    )..removeWhere((k, _) => k.toLowerCase() == 'connection');
    final dio = Dio(
      BaseOptions(
        baseUrl: baseUrl ?? ApiConfig.baseUrl,
        connectTimeout: ApiConfig.connectTimeout,
        receiveTimeout: ApiConfig.receiveTimeout,
        headers: clean,
      ),
    );
    dio.httpClientAdapter = _adapter;
    dio.interceptors
      ..add(_BreadcrumbInterceptor())
      ..add(_RetryOnDroppedConnection(dio));
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

/// Один повтор GET/HEAD, если соединение оборвалось до ответа.
///
/// Живое соединение сервер может закрыть ровно в момент нашего запроса — тогда
/// Dio видит «Connection closed before full header». GET безопасно повторить: он
/// ничего не меняет. POST/PUT/DELETE не повторяем — запрос мог дойти до сервера.
class _RetryOnDroppedConnection extends Interceptor {
  _RetryOnDroppedConnection(this._dio);
  final Dio _dio;
  static const _flag = 'retriedDroppedConnection';

  static bool isDropped(DioException e) {
    if (e.type == DioExceptionType.connectionError) return true;
    if (e.type != DioExceptionType.unknown) return false;
    final text = '${e.error ?? ''} ${e.message ?? ''}'.toLowerCase();
    return text.contains('connection closed') ||
        text.contains('connection reset') ||
        text.contains('broken pipe');
  }

  @override
  Future<void> onError(DioException err, ErrorInterceptorHandler handler) async {
    final o = err.requestOptions;
    final safe = o.method == 'GET' || o.method == 'HEAD';
    if (!safe || o.extra[_flag] == true || !isDropped(err)) {
      handler.next(err);
      return;
    }
    o.extra[_flag] = true;
    try {
      handler.resolve(await _dio.fetch<dynamic>(o));
    } on DioException catch (e) {
      handler.next(e);
    }
  }
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
