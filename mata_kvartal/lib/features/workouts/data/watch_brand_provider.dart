import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../../core/api/api_client.dart';
import '../../auth/data/auth_provider.dart';

/// Прямое подключение часов — Suunto и COROS (D-108; COROS с 22.11.2026).
///
/// У марок разный транспорт на сервере (Suunto шлёт уведомление, COROS мы
/// опрашиваем), но для приложения путь один: ссылка от нашего сервера → вход
/// у марки → состояние с сервера. Поэтому один контроллер на марку.
///
/// Вход в чужой аккаунт открываем во ВНЕШНЕМ браузере, а не внутри приложения:
/// человек должен видеть адресную строку марки и вводить пароль там, где ему
/// это привычно. Внутреннее окно для чужого входа — дурной тон и повод для
/// отказа со стороны партнёра.
///
/// После разрешения доступа марка возвращает человека на наш адрес, тот
/// отвечает страницей «Готово, вернитесь в приложение». Поэтому состояние мы не
/// ловим из браузера, а перечитываем с сервера, когда человек вернулся.
class WatchBrand {
  /// Часть адреса на сервере: /integrations/<source>/…
  final String source;

  /// Как марка называется у человека: «Suunto», «COROS».
  final String label;

  /// Что сказать на кнопке подключения — у каждой марки своя выгода.
  final String pitch;

  const WatchBrand(this.source, this.label, this.pitch);

  static const suunto = WatchBrand(
    'suunto',
    'Suunto',
    'Тренировки с часов придут сами, с маршрутом и пульсом — '
        'даже если телефон остался дома.',
  );
  static const coros = WatchBrand(
    'coros',
    'COROS',
    'Тренировки с часов подтянутся сами, с маршрутом и пульсом — '
        'обычно в течение получаса после пробежки.',
  );
}

class WatchState {
  /// Ключи на сервере есть — значит подключение можно предлагать.
  final bool available;
  final bool connected;
  final DateTime? lastSyncAt;
  final bool busy;
  final String? error;

  const WatchState({
    this.available = false,
    this.connected = false,
    this.lastSyncAt,
    this.busy = false,
    this.error,
  });

  WatchState copyWith({
    bool? available,
    bool? connected,
    DateTime? lastSyncAt,
    bool? busy,
    String? error,
    bool clearError = false,
  }) => WatchState(
    available: available ?? this.available,
    connected: connected ?? this.connected,
    lastSyncAt: lastSyncAt ?? this.lastSyncAt,
    busy: busy ?? this.busy,
    error: clearError ? null : (error ?? this.error),
  );
}

class WatchController extends StateNotifier<WatchState> {
  WatchController(this.ref, this.brand) : super(const WatchState()) {
    refresh();
  }

  final Ref ref;
  final WatchBrand brand;
  final Dio _dio = ApiClient.create(
    headers: const {'Content-Type': 'application/json'},
  );

  Options get _auth => Options(
    headers: {'Authorization': 'Bearer ${ref.read(authProvider).token ?? ''}'},
  );

  Future<void> refresh() async {
    final token = ref.read(authProvider).token;
    if (token == null || token.isEmpty) return;
    try {
      final res = await _dio.get<Map<String, dynamic>>(
        '/integrations/${brand.source}/account',
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
  /// подписанный идентификатор человека, без него марке некому вернуть ответ.
  Future<void> connect() async {
    state = state.copyWith(busy: true, clearError: true);
    try {
      final res = await _dio.get<Map<String, dynamic>>(
        '/integrations/${brand.source}/connect',
        options: _auth,
      );
      final url = (res.data ?? const {})['url']?.toString() ?? '';
      if (url.isEmpty) throw StateError('пустая ссылка');
      final ok = await launchUrl(Uri.parse(url), mode: LaunchMode.externalApplication);
      if (!ok) throw StateError('браузер не открылся');
    } on DioException catch (e) {
      state = state.copyWith(
        error: e.response?.statusCode == 503
            ? 'Подключение ${brand.label} сейчас недоступно — попробуйте позже'
            : 'Не удалось открыть страницу ${brand.label}',
      );
    } catch (_) {
      state = state.copyWith(error: 'Не удалось открыть страницу ${brand.label}');
    } finally {
      state = state.copyWith(busy: false);
    }
  }

  Future<void> disconnect() async {
    state = state.copyWith(busy: true, clearError: true);
    try {
      await _dio.delete<dynamic>('/integrations/${brand.source}/disconnect', options: _auth);
      state = state.copyWith(connected: false, lastSyncAt: null);
    } catch (_) {
      state = state.copyWith(error: 'Не удалось отключить часы');
    } finally {
      state = state.copyWith(busy: false);
    }
  }
}

final watchBrandProvider =
    StateNotifierProvider.family<WatchController, WatchState, WatchBrand>(
      (ref, brand) => WatchController(ref, brand),
    );
