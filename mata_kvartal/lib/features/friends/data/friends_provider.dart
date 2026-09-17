import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:latlong2/latlong.dart';

import '../../../core/api/api_client.dart';
import '../../auth/data/auth_provider.dart';

/// Друзья (D-82, этап 2a): граф взаимных друзей. Заявка → подтверждение → друзья.
///
/// СТАРТОВЫЙ ФЛАГ: раздел выключен, пока не соберём весь этап 2 (карта друзей +
/// приватность). Включить = `kFriends = true` (и пересборка). Пока false — вход
/// в раздел не показываем.
const bool kFriends = false;

/// status: none | outgoing | incoming | friends
class FriendSummary {
  final String userId;
  final String name;
  final String? avatarPath;
  final String status;

  const FriendSummary({
    required this.userId,
    required this.name,
    this.avatarPath,
    this.status = 'none',
  });

  factory FriendSummary.fromJson(Map<String, dynamic> j) => FriendSummary(
        userId: j['userId']?.toString() ?? '',
        name: (j['name']?.toString().isNotEmpty ?? false)
            ? j['name'].toString()
            : 'Бегун',
        avatarPath: (j['avatarPath'] as String?)?.isNotEmpty == true
            ? j['avatarPath'] as String
            : null,
        status: j['status']?.toString() ?? 'none',
      );

  String get initial => name.trim().isEmpty ? '?' : name.trim()[0].toUpperCase();
}

class FriendsData {
  final List<FriendSummary> friends;
  final List<FriendSummary> incoming;
  final List<FriendSummary> outgoing;
  const FriendsData({
    this.friends = const [],
    this.incoming = const [],
    this.outgoing = const [],
  });
}

final _friendsDio = ApiClient.create();

List<FriendSummary> _parse(dynamic list) =>
    ((list as List?) ?? const [])
        .whereType<Map<String, dynamic>>()
        .map(FriendSummary.fromJson)
        .toList();

Options _auth(String token) => Options(headers: {'Authorization': 'Bearer $token'});

/// Мои друзья + входящие/исходящие заявки.
final friendsProvider = FutureProvider.autoDispose<FriendsData>((ref) async {
  final token = ref.watch(authProvider).token;
  if (token == null || token.isEmpty) return const FriendsData();
  final res = await _friendsDio.get<Map<String, dynamic>>(
    '/friends',
    options: _auth(token),
  );
  final d = res.data ?? const {};
  return FriendsData(
    friends: _parse(d['friends']),
    incoming: _parse(d['incoming']),
    outgoing: _parse(d['outgoing']),
  );
});

/// Поиск людей по имени (для «по нику/ссылке»). Пусто при запросе < 2 символов.
final friendSearchProvider =
    FutureProvider.autoDispose.family<List<FriendSummary>, String>((ref, q) async {
  final token = ref.watch(authProvider).token;
  if (token == null || q.trim().length < 2) return const [];
  final res = await _friendsDio.get<Map<String, dynamic>>(
    '/friends/search',
    queryParameters: {'q': q.trim()},
    options: _auth(token),
  );
  return _parse((res.data ?? const {})['results']);
});

/// Подсказки: пока одноклубники, ещё не в друзьях.
final friendSuggestionsProvider =
    FutureProvider.autoDispose<List<FriendSummary>>((ref) async {
  final token = ref.watch(authProvider).token;
  if (token == null) return const [];
  final res = await _friendsDio.get<Map<String, dynamic>>(
    '/friends/suggestions',
    options: _auth(token),
  );
  return _parse((res.data ?? const {})['suggestions']);
});

final friendsActionsProvider =
    Provider<FriendsActions>((ref) => FriendsActions(ref));

/// Действия над дружбой: после каждого — обновляем списки.
class FriendsActions {
  FriendsActions(this._ref);
  final Ref _ref;

  String? get _token => _ref.read(authProvider).token;

  void _refresh() {
    _ref.invalidate(friendsProvider);
    _ref.invalidate(friendSuggestionsProvider);
  }

  Future<void> request(String userId) async {
    final t = _token;
    if (t == null) return;
    await _friendsDio.post<dynamic>('/friends/request',
        data: {'userId': userId}, options: _auth(t));
    _refresh();
  }

  Future<void> accept(String userId) async {
    final t = _token;
    if (t == null) return;
    await _friendsDio.post<dynamic>('/friends/$userId/accept',
        data: const {}, options: _auth(t));
    _refresh();
  }

  Future<void> reject(String userId) async {
    final t = _token;
    if (t == null) return;
    await _friendsDio.post<dynamic>('/friends/$userId/reject',
        data: const {}, options: _auth(t));
    _refresh();
  }

  Future<void> remove(String userId) async {
    final t = _token;
    if (t == null) return;
    await _friendsDio.delete<dynamic>('/friends/$userId', options: _auth(t));
    _refresh();
  }

  /// Обновить приватность карты друзей (visible / hideHours / home / homeHidden).
  Future<void> updatePrefs(Map<String, dynamic> patch) async {
    final t = _token;
    if (t == null) return;
    await _friendsDio.put<dynamic>('/friends/prefs',
        data: patch, options: _auth(t));
    _ref.invalidate(friendPrefsProvider);
    _ref.invalidate(friendPositionsProvider);
  }

  /// «Маяк» (D-84): точный трек 1–3 доверенным на `hours` часов.
  Future<void> startBeacon(double hours, List<String> trusted) async {
    final t = _token;
    if (t == null) return;
    await _friendsDio.post<dynamic>('/friends/beacon',
        data: {'hours': hours, 'trusted': trusted}, options: _auth(t));
    _ref.invalidate(friendPrefsProvider);
  }

  Future<void> stopBeacon() async {
    final t = _token;
    if (t == null) return;
    await _friendsDio.post<dynamic>('/friends/beacon',
        data: const {'off': true}, options: _auth(t));
    _ref.invalidate(friendPrefsProvider);
  }

  /// Отправить свою позицию (пока открыта карта). Сервер сам огрубит и решит,
  /// хранить ли (видимость/Тень/зона дома). Ошибку глотаем — не ради этого бег.
  Future<void> sendPosition(double lat, double lng, {String? status}) async {
    final t = _token;
    if (t == null) return;
    try {
      await _friendsDio.post<dynamic>('/friends/position',
          data: {'lat': lat, 'lng': lng, if (status != null) 'status': status},
          options: _auth(t));
    } catch (_) {}
  }
}


// ── Карта друзей (D-83, этап 2b/2c): приватность + позиции ────────────────────

/// Настройки приватности карты друзей. По умолчанию меня не видит никто.
class FriendMapPrefs {
  final bool visible;
  final String precision; // hex | exact
  final DateTime? hideUntil;
  final bool inShadow;
  final bool homeSet;
  final bool homeHidden;
  final bool beaconActive;
  final DateTime? beaconUntil;
  final List<String> beaconTrusted;

  const FriendMapPrefs({
    this.visible = false,
    this.precision = 'hex',
    this.hideUntil,
    this.inShadow = false,
    this.homeSet = false,
    this.homeHidden = true,
    this.beaconActive = false,
    this.beaconUntil,
    this.beaconTrusted = const [],
  });

  factory FriendMapPrefs.fromJson(Map<String, dynamic> j) => FriendMapPrefs(
        visible: j['visible'] == true,
        precision: j['precision']?.toString() ?? 'hex',
        hideUntil: j['hideUntil'] != null
            ? DateTime.tryParse(j['hideUntil'].toString())
            : null,
        inShadow: j['inShadow'] == true,
        homeSet: j['homeSet'] == true,
        homeHidden: j['homeHidden'] != false,
        beaconActive: j['beaconActive'] == true,
        beaconUntil: j['beaconUntil'] != null
            ? DateTime.tryParse(j['beaconUntil'].toString())
            : null,
        beaconTrusted: ((j['beaconTrusted'] as List?) ?? const [])
            .map((e) => e.toString())
            .toList(),
      );
}

class FriendPosition {
  final String userId;
  final String name;
  final String? avatarPath;
  final double lat;
  final double lng;
  final String status;
  final bool beacon;

  const FriendPosition({
    required this.userId,
    required this.name,
    required this.lat,
    required this.lng,
    this.avatarPath,
    this.status = '',
    this.beacon = false,
  });

  LatLng get point => LatLng(lat, lng);
  String get initial => name.trim().isEmpty ? '?' : name.trim()[0].toUpperCase();

  factory FriendPosition.fromJson(Map<String, dynamic> j) => FriendPosition(
        userId: j['userId']?.toString() ?? '',
        name: (j['name']?.toString().isNotEmpty ?? false)
            ? j['name'].toString()
            : 'Бегун',
        avatarPath: (j['avatarPath'] as String?)?.isNotEmpty == true
            ? j['avatarPath'] as String
            : null,
        lat: (j['lat'] as num?)?.toDouble() ?? 0,
        lng: (j['lng'] as num?)?.toDouble() ?? 0,
        status: j['status']?.toString() ?? '',
        beacon: j['beacon'] == true,
      );
}

/// Мои настройки приватности карты друзей.
final friendPrefsProvider = FutureProvider.autoDispose<FriendMapPrefs>((ref) async {
  final token = ref.watch(authProvider).token;
  if (token == null) return const FriendMapPrefs();
  final res = await _friendsDio.get<Map<String, dynamic>>(
    '/friends/prefs', options: _auth(token));
  return FriendMapPrefs.fromJson(res.data ?? const {});
});

/// Позиции взаимных друзей (огрублённые до гекса). Пусто, если я в «Тени».
final friendPositionsProvider =
    FutureProvider.autoDispose<List<FriendPosition>>((ref) async {
  if (!kFriends) return const [];
  final token = ref.watch(authProvider).token;
  if (token == null) return const [];
  final res = await _friendsDio.get<Map<String, dynamic>>(
    '/friends/positions', options: _auth(token));
  return ((res.data ?? const {})['positions'] as List? ?? const [])
      .whereType<Map<String, dynamic>>()
      .map(FriendPosition.fromJson)
      .toList();
});
