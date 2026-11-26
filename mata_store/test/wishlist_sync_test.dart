import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:sport_store/models/product.dart';
import 'package:sport_store/providers/wishlist_provider.dart';

/// Сервер избранного «по аккаунтам» (аудит сайта 26.11.2026, пункт 6).
class _Remote implements FavoritesRemote {
  final Map<String, List<String>> byUser = {};
  String current = '';
  List<String> get _mine => byUser.putIfAbsent(current, () => []);

  @override
  Future<List<String>> fetch() async => List.of(_mine);
  @override
  Future<List<String>> merge(List<String> keys) async {
    for (final k in keys) {
      if (!_mine.contains(k)) _mine.add(k);
    }
    return List.of(_mine);
  }

  @override
  Future<List<String>> add(String key) async => merge([key]);
  @override
  Future<List<String>> remove(String key) async {
    _mine.remove(key);
    return List.of(_mine);
  }
}

Product _p(String id) => Product.fromModelCard({'key': id, 'name': id, 'price': 1000});

void main() {
  test('гость → вход: избранное гостя уходит в аккаунт, в телефоне очищается', () async {
    SharedPreferences.setMockInitialValues({
      'wishlist_ids': jsonEncode(['A']),
    });
    final prefs = await SharedPreferences.getInstance();
    final remote = _Remote()..byUser['u1'] = ['B'];
    final w = WishlistProvider(prefs, remote: remote);
    expect(w.ids, {'A'});

    remote.current = 'u1';
    await w.syncAuth(true, userId: 'u1');
    expect(w.ids, {'A', 'B'});
    expect(remote.byUser['u1'], containsAll(['A', 'B']));
    expect(prefs.getString('wishlist_ids'), isNull);
  });

  test('в аккаунте сердце сохраняется на сервере; выход — чужое не остаётся', () async {
    SharedPreferences.setMockInitialValues({});
    final prefs = await SharedPreferences.getInstance();
    final remote = _Remote()..current = 'u1';
    final w = WishlistProvider(prefs, remote: remote);
    await w.syncAuth(true, userId: 'u1');

    w.toggle(_p('C'));
    await Future<void>.delayed(Duration.zero);
    expect(remote.byUser['u1'], ['C']);

    await w.syncAuth(false);
    expect(w.ids, isEmpty);

    // Другой аккаунт видит своё.
    remote.current = 'u2';
    await w.syncAuth(true, userId: 'u2');
    expect(w.ids, isEmpty);
  });

  test('без сервера (офлайн-прототип) — как раньше, только в телефоне', () async {
    SharedPreferences.setMockInitialValues({});
    final prefs = await SharedPreferences.getInstance();
    final w = WishlistProvider(prefs);
    w.toggle(_p('D'));
    await w.syncAuth(true, userId: 'u1');
    expect(w.ids, {'D'});
  });
}
