import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:sport_store/data/api/api_client.dart';
import 'package:sport_store/data/repositories/auth_repository.dart';
import 'package:sport_store/providers/auth_provider.dart';

/// Маршруты, которые реально есть в backend/django_api/accounts/urls.py
/// (префикс /v1/auth/). Всё прочее сервер вернёт 404.
const _serverAuthRoutes = {
  'POST register',
  'POST login',
  'POST phone/request',
  'POST phone/verify',
  'POST phone/channel',
  'POST password/reset',
  'GET me',
  'PATCH me',
  'DELETE me',
};

/// Сервер-заглушка: пишет, куда ходил клиент, и отвечает по сценарию.
class _Server {
  final calls = <String>[];
  final bodies = <Map<String, dynamic>>[];
  int resetStatus = 200;

  late final client = MockClient((req) async {
    final path = req.url.path.replaceFirst(RegExp(r'^.*/auth/'), '');
    final key = '${req.method} $path';
    calls.add(key);
    bodies.add(req.body.isEmpty
        ? const {}
        : jsonDecode(req.body) as Map<String, dynamic>);
    if (!_serverAuthRoutes.contains(key)) {
      return http.Response('{"detail":"Not found"}', 404, request: req);
    }
    if (path == 'password/reset' && resetStatus != 200) {
      return http.Response(
          jsonEncode({'detail': 'Неверный код'}), resetStatus,
          request: req, headers: {'content-type': 'application/json'});
    }
    return http.Response(
      jsonEncode({
        'token': 'new-token',
        'user': {
          'id': 'u1',
          'name': 'Тест',
          'email': '',
          'phone': '+79990001122',
          'provider': 'phone',
        },
      }),
      200,
      request: req,
      headers: {'content-type': 'application/json; charset=utf-8'},
    );
  });
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  Future<(AuthProvider, ApiClient, _Server)> make() async {
    SharedPreferences.setMockInitialValues({});
    final prefs = await SharedPreferences.getInstance();
    final server = _Server();
    final api = ApiClient(client: server.client);
    final auth = AuthProvider(prefs, ApiAuthRepository(api));
    return (auth, api, server);
  }

  test('D01: сброс пароля идёт на существующий маршрут с кодом', () async {
    final (auth, api, server) = await make();
    final err =
        await auth.resetPasswordByPhone('+79990001122', '1234', 'secret1');

    expect(err, isNull);
    expect(server.calls, ['POST password/reset']);
    expect(server.bodies.single,
        {'phone': '+79990001122', 'code': '1234', 'password': 'secret1'});
    expect(auth.isLoading, isFalse);
    expect(auth.user?.id, 'u1');
    expect(api.authToken, 'new-token');
  });

  test('D01: отказ сервера — понятная ошибка, загрузка снята, сессия цела',
      () async {
    final (auth, api, server) = await make();
    // Вошли раньше (сброс открыт из профиля).
    await auth.resetPasswordByPhone('+79990001122', '1234', 'secret1');
    var expired = false;
    api.onUnauthorized = () => expired = true;

    server.resetStatus = 401;
    final err =
        await auth.resetPasswordByPhone('+79990001122', '0000', 'secret2');

    expect(err, isNotNull);
    expect(auth.isLoading, isFalse);
    expect(expired, isFalse,
        reason: 'неверный код — не «сессия истекла», из аккаунта не выкидываем');
    expect(auth.isLoggedIn, isTrue);
  });

  test('D01: все сценарии входа/пароля ходят только на существующие маршруты',
      () async {
    final (auth, _, server) = await make();
    await auth.requestSmsCode('+79990001122');
    await auth.registerByPhone('+79990001122', '1234', 'secret1', 'Тест');
    await auth.loginByPassword('+79990001122', 'secret1');
    await auth.resetPasswordByPhone('+79990001122', '1234', 'secret2');

    expect(server.calls.where((c) => !_serverAuthRoutes.contains(c)), isEmpty,
        reason: 'клиент не должен звать маршруты, которых нет на сервере');
    expect(auth.isLoading, isFalse);
  });
}
