import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_client.dart';
import '../../auth/data/auth_provider.dart';
import '../../friends/data/friends_provider.dart';

/// Защита от другого человека: чёрный список и жалобы (§9–§10 готовности).
///
/// Блокировка на сервере хранится односторонне, а действует в обе стороны:
/// после неё мы друг для друга исчезаем из поиска, подсказок и совпадений по
/// контактам, а дружба рвётся. Разблокировка видимость возвращает, дружбу — нет.

class BlockedUser {
  final String userId;
  final String name;
  final String? avatarPath;

  const BlockedUser({required this.userId, required this.name, this.avatarPath});

  factory BlockedUser.fromJson(Map<String, dynamic> j) => BlockedUser(
        userId: j['userId']?.toString() ?? '',
        name: (j['name']?.toString().isNotEmpty ?? false)
            ? j['name'].toString()
            : 'Бегун',
        avatarPath: (j['avatarPath'] as String?)?.isNotEmpty == true
            ? j['avatarPath'] as String
            : null,
      );

  String get initial => name.trim().isEmpty ? '?' : name.trim()[0].toUpperCase();
}

class ReportReason {
  final String code;
  final String title;
  const ReportReason(this.code, this.title);
}

final _dio = ApiClient.create();

Options _auth(String token) => Options(headers: {'Authorization': 'Bearer $token'});

/// Кого я заблокировал.
final blockedProvider = FutureProvider.autoDispose<List<BlockedUser>>((ref) async {
  final token = ref.watch(authProvider.select((s) => s.token));
  if (token == null || token.isEmpty) return const [];
  final res = await _dio.get<List<dynamic>>('/me/blocks', options: _auth(token));
  return (res.data ?? const [])
      .whereType<Map<String, dynamic>>()
      .map(BlockedUser.fromJson)
      .toList();
});

/// Причины жалобы берём с сервера, чтобы приложение и админка не разошлись
/// в формулировках: модератор разбирает по тем же словам, что видел человек.
final reportReasonsProvider =
    FutureProvider.autoDispose<List<ReportReason>>((ref) async {
  final token = ref.watch(authProvider.select((s) => s.token));
  if (token == null || token.isEmpty) return const [];
  final res = await _dio.get<List<dynamic>>('/reports/reasons', options: _auth(token));
  return (res.data ?? const [])
      .whereType<Map<String, dynamic>>()
      .map((j) => ReportReason(
            j['code']?.toString() ?? '',
            j['title']?.toString() ?? '',
          ))
      .where((r) => r.code.isNotEmpty)
      .toList();
});

final moderationActionsProvider =
    Provider<ModerationActions>((ref) => ModerationActions(ref));

class ModerationActions {
  ModerationActions(this._ref);
  final Ref _ref;

  String? get _token => _ref.read(authProvider).token;

  /// Заблокировать. true — получилось; дальше список друзей и подсказки
  /// перечитываем: человек должен исчезнуть сразу, а не после перезахода.
  Future<bool> block(String userId) async {
    final t = _token;
    if (t == null) return false;
    try {
      await _dio.post<dynamic>('/me/blocks',
          data: {'userId': userId}, options: _auth(t));
      _ref.invalidate(blockedProvider);
      _ref.invalidate(friendsProvider);
      _ref.invalidate(friendSuggestionsProvider);
      return true;
    } catch (_) {
      return false;
    }
  }

  Future<bool> unblock(String userId) async {
    final t = _token;
    if (t == null) return false;
    try {
      await _dio.delete<dynamic>('/me/blocks/$userId', options: _auth(t));
      _ref.invalidate(blockedProvider);
      return true;
    } catch (_) {
      return false;
    }
  }

  /// Пожаловаться. Возвращает текст для показа человеку: null — отправлено.
  Future<String?> report({
    required String targetType, // user | club
    required String targetId,
    required String reason,
    String comment = '',
  }) async {
    final t = _token;
    if (t == null) return 'Нужно войти в аккаунт';
    try {
      await _dio.post<dynamic>(
        '/reports',
        data: {
          'targetType': targetType,
          'targetId': targetId,
          'reason': reason,
          if (comment.trim().isNotEmpty) 'comment': comment.trim(),
        },
        options: _auth(t),
      );
      return null;
    } on DioException catch (e) {
      // Сервер отвечает понятной фразой — показываем её, а не «ошибка 429».
      final d = e.response?.data;
      if (d is Map && d['detail'] is String) return d['detail'] as String;
      return 'Не удалось отправить — попробуйте позже';
    } catch (_) {
      return 'Не удалось отправить — попробуйте позже';
    }
  }
}
