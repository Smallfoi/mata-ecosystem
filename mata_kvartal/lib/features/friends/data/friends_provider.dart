import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

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
}
