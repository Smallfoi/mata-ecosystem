import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:kvartal_app/features/auth/data/auth_provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Телефон владельца, 22.11.2026: токен истёк, сервер на всё отвечал 401, а
/// Квартал оставался «вошедшим» — экраны падали с ошибкой («Не удалось
/// загрузить клубы»), на вход не уводило. Store в той же ситуации выходил.
class _Reply implements HttpClientAdapter {
  _Reply(this.status, {this.dropConnection = false, this.renewed});
  final int status;
  final bool dropConnection;
  final String? renewed;

  @override
  Future<ResponseBody> fetch(RequestOptions options,
      Stream<Uint8List>? requestStream, Future<void>? cancelFuture) async {
    if (dropConnection) {
      throw DioException.connectionError(
          requestOptions: options, reason: 'нет сети');
    }
    return ResponseBody.fromString(
      jsonEncode(status == 200
          ? {
              'id': 'u1',
              'name': 'Бегун',
              'email': '',
              if (renewed != null) 'renewedToken': renewed,
            }
          : {'detail': 'Не авторизован'}),
      status,
      headers: {
        Headers.contentTypeHeader: [Headers.jsonContentType],
      },
    );
  }

  @override
  void close({bool force = false}) {}
}

Dio _dio(_Reply reply) =>
    Dio(BaseOptions(baseUrl: 'http://test'))..httpClientAdapter = reply;

Future<AuthNotifier> _start(_Reply reply) async {
  final auth = AuthNotifier(dio: _dio(reply));
  // restoreSession асинхронный: префы, (недоступное в тесте) защищённое
  // хранилище, запрос. Даём ему отработать.
  for (var i = 0; i < 20; i++) {
    await pumpEventQueue();
  }
  return auth;
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  // Старый открытый ключ: защищённого хранилища в тестах нет, токен берётся
  // отсюда (миграция в restoreSession).
  setUp(() => SharedPreferences.setMockInitialValues(
      {'kvartal.auth.token.v1': 'dead-token'}));

  test('сервер отверг токен (401) — выходим из аккаунта', () async {
    final auth = await _start(_Reply(401));
    expect(auth.state.status, isNot(AuthStatus.authenticated));
    expect(auth.state.token, isNull);
  });

  test('нет сети — сессию сохраняем', () async {
    final auth = await _start(_Reply(0, dropConnection: true));
    expect(auth.state.status, AuthStatus.authenticated);
    expect(auth.state.token, 'dead-token');
  });

  test('токен действует — остаёмся во входе', () async {
    final auth = await _start(_Reply(200));
    expect(auth.state.status, AuthStatus.authenticated);
    expect(auth.state.user?.id, 'u1');
    expect(auth.state.token, 'dead-token');
  });

  test('сервер продлил вход — берём новый токен', () async {
    final auth = await _start(_Reply(200, renewed: 'fresh-token'));
    expect(auth.state.status, AuthStatus.authenticated);
    expect(auth.state.token, 'fresh-token');
  });
}
