import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:sport_store/data/api/api_client.dart';
import 'package:sport_store/data/repositories/auth_repository.dart';

/// Продление входа (22.11.2026): `/auth/me` присылает `renewedToken`, когда
/// старому токену осталось меньше половины срока. Клиент обязан взять его —
/// иначе раз в 30 дней покупателя выкидывало на вход.
ApiClient _api(Map<String, dynamic> me) => ApiClient(
      client: MockClient((req) async => http.Response(
            jsonEncode(me),
            200,
            request: req,
            headers: {'content-type': 'application/json'},
          )),
    );

void main() {
  const user = {'id': 'u1', 'name': 'Покупатель', 'email': 'u1@t.dev'};

  test('сервер продлил вход — клиент берёт и сохраняет новый токен', () async {
    final api = _api({...user, 'renewedToken': 'fresh'});
    String? persisted;
    api.authToken = 'old';
    api.onTokenChanged = (t) => persisted = t;

    final me = await ApiAuthRepository(api).fetchMe();

    expect(me.id, 'u1');
    expect(api.authToken, 'fresh');
    expect(persisted, 'fresh', reason: 'токен должен уйти в хранилище');
  });

  test('без продления токен не трогаем', () async {
    final api = _api(user);
    var changed = false;
    api.authToken = 'old';
    api.onTokenChanged = (_) => changed = true;

    await ApiAuthRepository(api).fetchMe();

    expect(api.authToken, 'old');
    expect(changed, isFalse);
  });
}
