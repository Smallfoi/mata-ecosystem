import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:kvartal_app/core/api/api_client.dart';

/// Этап 2 оптимизации (21.11.2026): соединение живёт и переиспользуется, а
/// оборванное соединение страхуется одним повтором GET (ради этой страховки
/// раньше ставили `Connection: close` и платили рукопожатие на каждый запрос).

class _FlakyAdapter implements HttpClientAdapter {
  _FlakyAdapter({this.failFirst = 1});
  int failFirst;
  final seen = <RequestOptions>[];

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    seen.add(options);
    if (failFirst > 0) {
      failFirst--;
      throw DioException(
        requestOptions: options,
        type: DioExceptionType.unknown,
        error: const HttpExceptionLike('Connection closed before full header was received'),
      );
    }
    return ResponseBody.fromString(
      jsonEncode({'ok': true}),
      200,
      headers: {
        Headers.contentTypeHeader: [Headers.jsonContentType],
      },
    );
  }

  @override
  void close({bool force = false}) {}
}

class HttpExceptionLike implements Exception {
  const HttpExceptionLike(this.message);
  final String message;
  @override
  String toString() => message;
}

Dio _dio(_FlakyAdapter adapter, {Map<String, String>? headers}) =>
    ApiClient.create(headers: headers)..httpClientAdapter = adapter;

void main() {
  test('заголовка Connection: close больше нет, даже если его передали', () {
    final dio = ApiClient.create(
      headers: const {'Content-Type': 'application/json', 'Connection': 'close'},
    );
    expect(
      dio.options.headers.keys.map((k) => k.toLowerCase()),
      isNot(contains('connection')),
    );
  });

  test('оборванный GET повторяется один раз и проходит', () async {
    final adapter = _FlakyAdapter(failFirst: 1);
    final res = await _dio(adapter).get<Map<String, dynamic>>('/health');
    expect(res.data, {'ok': true});
    expect(adapter.seen.length, 2);
  });

  test('второй обрыв подряд — ошибка, без бесконечных повторов', () async {
    final adapter = _FlakyAdapter(failFirst: 5);
    await expectLater(_dio(adapter).get<dynamic>('/health'), throwsA(isA<DioException>()));
    expect(adapter.seen.length, 2);
  });

  test('POST не повторяется: запрос мог уже дойти до сервера', () async {
    final adapter = _FlakyAdapter(failFirst: 1);
    await expectLater(
      _dio(adapter).post<dynamic>('/runs', data: {'km': 5}),
      throwsA(isA<DioException>()),
    );
    expect(adapter.seen.length, 1);
  });
}
