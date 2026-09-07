import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_client.dart';
import '../../auth/data/auth_provider.dart';

/// Лента уведомлений экосистемы (общий backend). В Квартале — клубные события
/// (заявки/одобрения), а также любые уведомления аккаунта (например, статусы
/// заказов из Store — аккаунт единый). GET /notifications, POST /notifications/read.
class NotificationItem {
  final String id;
  final String title;
  final String body;
  final String type;
  final bool read;
  final DateTime? createdAt;

  const NotificationItem({
    required this.id,
    required this.title,
    required this.body,
    required this.type,
    required this.read,
    this.createdAt,
  });

  NotificationItem copyWith({bool? read}) => NotificationItem(
        id: id,
        title: title,
        body: body,
        type: type,
        read: read ?? this.read,
        createdAt: createdAt,
      );

  factory NotificationItem.fromJson(Map<String, dynamic> j) => NotificationItem(
        id: j['id']?.toString() ?? '',
        title: j['title']?.toString() ?? '',
        body: j['body']?.toString() ?? '',
        type: j['type']?.toString() ?? 'system',
        read: j['read'] == true,
        createdAt: DateTime.tryParse(j['createdAt']?.toString() ?? ''),
      );
}

class NotificationsState {
  final List<NotificationItem> items;
  final bool isLoading;
  final bool loaded;

  const NotificationsState({
    this.items = const [],
    this.isLoading = false,
    this.loaded = false,
  });

  int get unread => items.where((n) => !n.read).length;
  bool get hasUnread => unread > 0;

  NotificationsState copyWith({
    List<NotificationItem>? items,
    bool? isLoading,
    bool? loaded,
  }) =>
      NotificationsState(
        items: items ?? this.items,
        isLoading: isLoading ?? this.isLoading,
        loaded: loaded ?? this.loaded,
      );
}

class NotificationsNotifier extends StateNotifier<NotificationsState> {
  final Ref ref;

  NotificationsNotifier(this.ref) : super(const NotificationsState());

  final Dio _dio = ApiClient.create(headers: {'Content-Type': 'application/json', 'Connection': 'close'});

  Future<void> refresh() async {
    if (state.isLoading) return;
    final token = ref.read(authProvider).token;
    if (token == null || token.isEmpty) {
      state = const NotificationsState();
      return;
    }
    state = state.copyWith(isLoading: true);
    try {
      final response = await _dio.get<List<dynamic>>(
        '/notifications',
        options: Options(headers: {'Authorization': 'Bearer $token'}),
      );
      final items = (response.data ?? [])
          .whereType<Map<String, dynamic>>()
          .map(NotificationItem.fromJson)
          .toList();
      state = NotificationsState(items: items, isLoading: false, loaded: true);
    } catch (_) {
      state = state.copyWith(isLoading: false);
    }
  }

  Future<void> markAllRead() async {
    final token = ref.read(authProvider).token;
    if (token == null || token.isEmpty || !state.hasUnread) return;
    // Оптимистично помечаем прочитанными.
    state = state.copyWith(
      items: state.items.map((n) => n.read ? n : n.copyWith(read: true)).toList(),
    );
    try {
      await _dio.post<dynamic>(
        '/notifications/read',
        data: const {},
        options: Options(headers: {'Authorization': 'Bearer $token'}),
      );
    } catch (_) {
      // офлайн — отметятся при следующей синхронизации
    }
  }
}

final notificationsProvider =
    StateNotifierProvider<NotificationsNotifier, NotificationsState>((ref) {
  final notifier = NotificationsNotifier(ref);
  ref.listen<AuthState>(authProvider, (prev, next) {
    if (next.status == AuthStatus.authenticated && next.token != prev?.token) {
      notifier.refresh();
    }
  });
  if (ref.read(authProvider).status == AuthStatus.authenticated) {
    notifier.refresh();
  }
  return notifier;
});
