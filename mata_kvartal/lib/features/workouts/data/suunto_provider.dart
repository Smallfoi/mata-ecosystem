import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../../core/api/api_client.dart';
import '../../auth/data/auth_provider.dart';

/// Подключение часов Suunto (D-108).
///
/// Вход в чужой аккаунт открываем во ВНЕШНЕМ браузере, а не внутри приложения:
/// человек должен видеть адресную строку Suunto и вводить пароль там, где ему
/// это привычно. Внутреннее окно для чужого входа — дурной тон и повод для
/// отказа со стороны партнёра.
///
/// После разрешения доступа Suunto возвращает человека на наш адрес, тот
/// отвечает страницей «Готово, вернитесь в приложение». Поэтому состояние мы не
/// ловим из браузера, а перечитываем с сервера, когда человек вернулся.
class SuuntoState {
  /// Ключи на сервере есть — значит подключение можно предлагать.
  final bool available;
  final bool connected;
  final DateTime? lastSyncAt;
  final bool busy;
  final String? error;

  const SuuntoState({
    this.available = false,
    this.connected = false,
    this.lastSyncAt,
    this.busy = false,
    this.error,
  });

  SuuntoState copyWith({
    bool? available,
    bool? connected,
    DateTime? lastSyncAt,
    bool? busy,
    String? error,
    bool clearError = false,
  }) => SuuntoState(
    available: available ?? this.available,
    connected: connected ?? this.connected,
    lastSyncAt: lastSyncAt ?? this.lastSyncAt,
    busy: busy ?? this.busy,
    error: clearError ? null : (error ?? this.error),
  );
}

class SuuntoController extends StateNotifier<SuuntoState> {
  SuuntoController(this.ref) : super(const SuuntoState()) {
    refresh();
  }

  final Ref ref;
  final Dio _dio = ApiClient.create(
    headers: const {'Content-Type': 'application/json', 'Connection': 'close'},
  );

  Options get _auth => Options(
    headers: {'Authorization': 'Bearer ${ref.read(authProvider).token ?? ''}'},
  );

  Future<void> refresh() async {
    final token = ref.read(authProvider).token;
    if (token == null || token.isEmpty) return;
    try {
      final res = await _dio.get<Map<String, dynamic>>(
        '/integrations/suunto/account',
        options: _auth,
      );
      final data = res.data ?? const {};
      final ms = (data['lastSyncAtMs'] as num?)?.toInt();
      state = state.copyWith(
        available: data['configured'] == true,
        connected: data['connected'] == true,
        lastSyncAt: ms == null ? null : DateTime.fromMillisecondsSinceEpoch(ms),
        clearError: true,
      );
    } catch (_) {
      // Нет сети — не повод пугать человека: экран просто покажет прежнее.
    }
  }

  /// Открыть страницу разрешения доступа. Ссылку выдаёт наш сервер: в ней
  /// подписанный идентификатор человека, без него Suunto некому вернуть ответ.
  Future<void> connect() async {
    state = state.copyWith(busy: true, clearError: true);
    try {
      final res = await _dio.get<Map<String, dynamic>>(
        '/integrations/suunto/connect',
        options: _auth,
      );
      final url = (res.data ?? const {})['url']?.toString() ?? '';
      if (url.isEmpty) throw StateError('пустая ссылка');
      final ok = await launchUrl(Uri.parse(url), mode: LaunchMode.externalApplication);
      if (!ok) throw StateError('браузер не открылся');
    } on DioException catch (e) {
      state = state.copyWith(
        error: e.response?.statusCode == 503
            ? 'Подключение Suunto ещё не настроено на сервере'
            : 'Не удалось открыть страницу Suunto',
      );
    } catch (_) {
      state = state.copyWith(error: 'Не удалось открыть страницу Suunto');
    } finally {
      state = state.copyWith(busy: false);
    }
  }

  Future<void> disconnect() async {
    state = state.copyWith(busy: true, clearError: true);
    try {
      await _dio.delete<dynamic>('/integrations/suunto/disconnect', options: _auth);
      state = state.copyWith(connected: false, lastSyncAt: null);
    } catch (_) {
      state = state.copyWith(error: 'Не удалось отключить часы');
    } finally {
      state = state.copyWith(busy: false);
    }
  }
}

final suuntoProvider = StateNotifierProvider<SuuntoController, SuuntoState>(
  (ref) => SuuntoController(ref),
);
