import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../data/api/api_client.dart';
import '../models/product.dart';

/// Избранное на сервере (`/v1/favorites`, аудит сайта 26.11.2026, пункт 6): одно на
/// сайт и приложение — по аккаунту. Ключ — модель витрины (`Product.id` = key).
abstract class FavoritesRemote {
  Future<List<String>> fetch();
  Future<List<String>> merge(List<String> keys);
  Future<List<String>> add(String key);
  Future<List<String>> remove(String key);
}

class ApiFavoritesRemote implements FavoritesRemote {
  final ApiClient _api;
  ApiFavoritesRemote(this._api);

  static List<String> _keys(dynamic r) => (r is Map && r['keys'] is List)
      ? (r['keys'] as List).map((e) => '$e').toList()
      : const [];

  @override
  Future<List<String>> fetch() async => _keys(await _api.get('/favorites'));
  @override
  Future<List<String>> merge(List<String> keys) async =>
      _keys(await _api.post('/favorites/merge', body: {'keys': keys}));
  @override
  Future<List<String>> add(String key) async =>
      _keys(await _api.put('/favorites/${Uri.encodeComponent(key)}'));
  @override
  Future<List<String>> remove(String key) async =>
      _keys(await _api.delete('/favorites/${Uri.encodeComponent(key)}'));
}

/// Гость копит избранное в телефоне; вошёл — оно сливается в аккаунт и в телефоне
/// очищается: после выхода чужое избранное не остаётся (как корзина и баллы, C03).
class WishlistProvider extends ChangeNotifier {
  final SharedPreferences _prefs;
  final FavoritesRemote? _remote;
  static const _key = 'wishlist_ids'; // гость
  static const _accKey = 'wishlist_acc'; // зеркало аккаунта — показать сразу при запуске

  Set<String> _ids = {};
  bool _loggedIn = false;
  String _account = '';

  WishlistProvider(this._prefs, {FavoritesRemote? remote}) : _remote = remote {
    _ids = _load(_key);
  }

  Set<String> _load(String key) {
    final raw = _prefs.getString(key);
    if (raw == null) return {};
    try {
      return Set<String>.from(jsonDecode(raw) as List);
    } catch (_) {
      return {};
    }
  }

  void _save() {
    _prefs.setString(_loggedIn ? _accKey : _key, jsonEncode(_ids.toList()));
  }

  Set<String> get ids => Set.unmodifiable(_ids);
  bool contains(String productId) => _ids.contains(productId);
  int get count => _ids.length;

  void _apply(List<String> keys) {
    _ids = keys.toSet();
    _save();
    notifyListeners();
  }

  /// Из ProxyProvider при смене входа. Вход — список гостя уходит в аккаунт
  /// (merge), дальше источник — сервер. Выход или другой аккаунт — чистим.
  Future<void> syncAuth(bool loggedIn, {String? userId}) async {
    final remote = _remote;
    if (remote == null) return;
    final account = userId ?? '';
    if (loggedIn && (!_loggedIn || account != _account)) {
      final guest = _loggedIn ? <String>[] : _load(_key).toList();
      _loggedIn = true;
      _account = account;
      _ids = _load(_accKey);
      notifyListeners();
      try {
        final keys =
            guest.isEmpty ? await remote.fetch() : await remote.merge(guest);
        await _prefs.remove(_key);
        _apply(keys);
      } catch (_) {
        // Нет сети — показываем зеркало; список гостя не трогаем, сольём в следующий раз.
      }
    } else if (!loggedIn && _loggedIn) {
      _loggedIn = false;
      _account = '';
      await _prefs.remove(_accKey);
      _ids = _load(_key);
      notifyListeners();
    }
  }

  void toggle(Product product) {
    final id = product.id;
    final add = !_ids.contains(id);
    if (add) {
      _ids.add(id);
    } else {
      _ids.remove(id);
    }
    _save();
    notifyListeners();
    final remote = _remote;
    if (_loggedIn && remote != null) {
      (add ? remote.add(id) : remote.remove(id))
          .then(_apply)
          .catchError((Object _) {});
    }
  }
}
