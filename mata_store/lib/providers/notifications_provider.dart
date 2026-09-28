import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../data/api/api_client.dart';
import '../models/app_notification.dart';

class NotificationsProvider extends ChangeNotifier {
  final SharedPreferences _prefs;

  /// true → лента берётся с общего backend (GET /notifications), источник правды.
  final ApiClient? api;
  final bool serverBacked;

  static const _key = 'notifications';

  final List<AppNotification> _items = [];
  bool _lastLoggedIn = false;
  String _account = '';

  NotificationsProvider(this._prefs, {this.api, this.serverBacked = false}) {
    _load();
  }

  List<AppNotification> get items => List.unmodifiable(_items);
  int get unreadCount => _items.where((n) => !n.read).length;
  bool get hasUnread => unreadCount > 0;

  /// Вызывается из ProxyProvider при изменении авторизации. [userId] — id
  /// аккаунта: при выходе ИЛИ смене аккаунта лента прошлого аккаунта стирается
  /// (аудит C03), для нового подтягивается своя.
  Future<void> syncAuth(bool loggedIn, {String? userId}) async {
    if (!serverBacked) return;
    final account = userId ?? '';
    if (loggedIn && (!_lastLoggedIn || account != _account)) {
      final switched = _lastLoggedIn;
      _lastLoggedIn = true;
      _account = account;
      if (switched) _clearLocal();
      await refresh();
    } else if (!loggedIn && _lastLoggedIn) {
      _lastLoggedIn = false;
      _account = '';
      _clearLocal();
    }
  }

  void _clearLocal() {
    _items.clear();
    _save();
    notifyListeners();
  }

  /// Лента уведомлений с общего бэкенда (статусы заказов и т.п.).
  Future<void> refresh() async {
    if (!serverBacked || api == null) return;
    final account = _account;
    try {
      final data = await api!.get('/notifications') as List;
      // Пока шёл запрос, сменился аккаунт — чужую ленту не показываем.
      if (account != _account) return;
      _items
        ..clear()
        ..addAll(
          data.whereType<Map<String, dynamic>>().map(AppNotification.fromJson),
        );
      _save();
      notifyListeners();
    } catch (_) {
      // офлайн — остаёмся на локальном кэше
    }
  }

  void _load() {
    final raw = _prefs.getString(_key);
    if (raw == null) return;
    try {
      final list = jsonDecode(raw) as List;
      _items.addAll(
        list.map((j) => AppNotification.fromJson(j as Map<String, dynamic>)),
      );
    } catch (_) {}
  }

  void _save() {
    _prefs.setString(_key, jsonEncode(_items.map((n) => n.toJson()).toList()));
  }

  void push(AppNotification notification) {
    _items.insert(0, notification);
    _save();
    notifyListeners();
  }

  Future<void> markAllRead() async {
    if (!hasUnread) return;
    for (var i = 0; i < _items.length; i++) {
      if (!_items[i].read) _items[i] = _items[i].copyWith(read: true);
    }
    _save();
    notifyListeners();
    if (serverBacked && api != null) {
      try {
        await api!.post('/notifications/read', body: const {});
      } catch (_) {
        // офлайн — отметятся при следующей синхронизации
      }
    }
  }

  void remove(String id) {
    _items.removeWhere((n) => n.id == id);
    _save();
    notifyListeners();
  }

  void clear() {
    _items.clear();
    _save();
    notifyListeners();
  }
}
