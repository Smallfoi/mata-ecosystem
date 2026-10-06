import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../../../core/api/api_config.dart';
import '../../../core/storage/account_scope.dart';
import '../../auth/data/auth_provider.dart';
import 'loyalty_v1.dart';

export 'loyalty_v1.dart';

/// Баллы лояльности — общий счёт экосистемы (тот же backend, что и аккаунт).
/// Квартал начисляет баллы за бег/территории, Store их тратит. Здесь — чтение
/// общего баланса через GET /loyalty/account (источник правды — backend).
class LoyaltyTxn {
  final int amount;
  final String source;
  final String description;
  final String? createdAt;

  const LoyaltyTxn({
    required this.amount,
    required this.source,
    required this.description,
    this.createdAt,
  });

  factory LoyaltyTxn.fromJson(Map<String, dynamic> json) => LoyaltyTxn(
    amount: (json['amount'] as num?)?.toInt() ?? 0,
    source: json['source']?.toString() ?? '',
    description: json['description']?.toString() ?? '',
    createdAt: json['createdAt']?.toString(),
  );
}

class LoyaltyState {
  final int balance;
  final String level;
  final List<LoyaltyTxn> transactions;
  final bool isLoading;
  final bool loaded;
  final String? error;

  /// Постоянный 6-значный код лояльности клиента (для кассы/QR). Не меняется.
  final String code;

  /// Баллы за бег, которые ещё нельзя потратить: созревают 3 дня или заморожены
  /// на время проверки аккаунта (сервер, 28.09.2026). [balance] — тратимые.
  final int pending;

  /// Ближайшая партия созревающих баллов: сколько и когда станут доступны.
  final int pendingNextAmount;
  final DateTime? pendingNextAt;

  /// Аккаунт на проверке — баллы за активность заморожены до решения.
  final bool frozen;

  /// Программа v1 (ТЗ 30.09.2026): кошелёк с лотами, уровни по статусным.
  /// null — сервер на прежней программе, всё как раньше.
  final LoyaltyV1? v1;

  const LoyaltyState({
    this.balance = 0,
    this.level = 'basic',
    this.transactions = const [],
    this.isLoading = false,
    this.loaded = false,
    this.error,
    this.code = '',
    this.pending = 0,
    this.pendingNextAmount = 0,
    this.pendingNextAt,
    this.frozen = false,
    this.v1,
  });

  bool get programV1 => v1 != null;

  LoyaltyState copyWith({
    int? balance,
    String? level,
    List<LoyaltyTxn>? transactions,
    bool? isLoading,
    bool? loaded,
    String? error,
    bool clearError = false,
    String? code,
    int? pending,
    int? pendingNextAmount,
    DateTime? pendingNextAt,
    bool clearPendingNextAt = false,
    bool? frozen,
    LoyaltyV1? v1,
    bool clearV1 = false,
  }) => LoyaltyState(
    balance: balance ?? this.balance,
    level: level ?? this.level,
    transactions: transactions ?? this.transactions,
    isLoading: isLoading ?? this.isLoading,
    loaded: loaded ?? this.loaded,
    error: clearError ? null : error ?? this.error,
    code: code ?? this.code,
    pending: pending ?? this.pending,
    pendingNextAmount: pendingNextAmount ?? this.pendingNextAmount,
    pendingNextAt: clearPendingNextAt
        ? null
        : pendingNextAt ?? this.pendingNextAt,
    frozen: frozen ?? this.frozen,
    v1: clearV1 ? null : v1 ?? this.v1,
  );

  /// Русское название уровня по порогам экосистемы (0/200/500/1000).
  String get levelTitle => switch (level) {
    'platinum' => 'Платина',
    'gold' => 'Золото',
    'silver' => 'Серебро',
    _ => 'Базовый',
  };
}

class LoyaltyNotifier extends StateNotifier<LoyaltyState> {
  final Ref ref;

  LoyaltyNotifier(this.ref) : super(const LoyaltyState());

  final Dio _dio = Dio(
    BaseOptions(
      baseUrl: ApiConfig.baseUrl,
      connectTimeout: ApiConfig.connectTimeout,
      receiveTimeout: ApiConfig.receiveTimeout,
      // 'Connection: close' — каждый запрос на свежем соединении. Иначе Dio
      // переиспользует keep-alive, который uvicorn закрывает по таймауту, и
      // поверх adb reverse это даёт "Connection closed before full header".
      headers: {'Content-Type': 'application/json', 'Connection': 'close'},
    ),
  );

  static const _pendingKey = 'kvartal.loyalty.pending.v1';

  Future<void> refresh() async {
    if (state.isLoading) return; // дедуп: не пускаем два запроса разом
    final token = ref.read(authProvider).token;
    if (token == null || token.isEmpty) {
      state = const LoyaltyState();
      return;
    }
    state = state.copyWith(isLoading: true, clearError: true);
    // Сначала досылаем накопленные офлайн-начисления, затем читаем баланс.
    await _flushPending(token);
    try {
      final response = await _dio.get<Map<String, dynamic>>(
        '/loyalty/account',
        options: Options(headers: {'Authorization': 'Bearer $token'}),
      );
      final data = response.data ?? {};
      final txns = (data['transactions'] as List? ?? [])
          .whereType<Map<String, dynamic>>()
          .map(LoyaltyTxn.fromJson)
          .toList();
      state = state.copyWith(
        balance: (data['balance'] as num?)?.toInt() ?? 0,
        level: data['level']?.toString() ?? 'basic',
        code: data['code']?.toString() ?? '',
        // Новые поля сервера (28.09.2026); старый сервер их не шлёт → 0/null.
        pending: (data['pending'] as num?)?.toInt() ?? 0,
        pendingNextAmount: (data['pendingNextAmount'] as num?)?.toInt() ?? 0,
        pendingNextAt: DateTime.tryParse(
          data['pendingNextAt']?.toString() ?? '',
        )?.toLocal(),
        clearPendingNextAt: data['pendingNextAt'] == null,
        frozen: data['frozen'] == true,
        // Программа v1: старый сервер блока не шлёт → прежний экран.
        v1: LoyaltyV1.fromAccount(data),
        clearV1: LoyaltyV1.fromAccount(data) == null,
        transactions: txns,
        isLoading: false,
        loaded: true,
        clearError: true,
      );
    } catch (_) {
      state = state.copyWith(isLoading: false, error: 'Не удалось загрузить баллы');
    }
  }

  /// Начислить баллы в общий счёт экосистемы. Начисление кладётся в локальную
  /// очередь и сразу пытается уйти на backend; при офлайне остаётся в очереди и
  /// долетит при следующем refresh (открытие профиля / повторный вход), когда
  /// связь вернётся. Backend идемпотентен по runId+source — повтор не задвоит.
  Future<void> award({
    required int amount,
    required String source,
    required String description,
    String? runId,
  }) async {
    if (amount <= 0) return;
    await _enqueue({
      'amount': amount,
      'source': source,
      'description': description,
      'runId': runId,
    });
    await refresh();
  }

  Future<void> _enqueue(Map<String, dynamic> item) async {
    final prefs = await SharedPreferences.getInstance();
    // Владелец — кто вошёл сейчас (C03): под другим аккаунтом не отправится.
    final list = _readPending(prefs)
      ..add(withOwner(item, ref.read(authProvider).user?.id));
    await prefs.setString(_pendingKey, jsonEncode(list));
  }

  List<Map<String, dynamic>> _readPending(SharedPreferences prefs) {
    final raw = prefs.getString(_pendingKey);
    if (raw == null || raw.isEmpty) return [];
    try {
      return (jsonDecode(raw) as List)
          .whereType<Map<String, dynamic>>()
          .toList();
    } catch (_) {
      return [];
    }
  }

  /// Досылает накопленные начисления по порядку. На первой сетевой ошибке
  /// останавливается и сохраняет остаток — повторим при следующем refresh.
  Future<void> _flushPending(String token) async {
    final prefs = await SharedPreferences.getInstance();
    final all = _readPending(prefs);
    if (all.isEmpty) return;
    // Только свои начисления (C03): чужие ждут входа своего владельца.
    final me = ref.read(authProvider).user?.id;
    final pending = all.where((e) => isOwnedBy(e, me)).toList();
    final remaining = all.where((e) => !isOwnedBy(e, me)).toList();
    for (var i = 0; i < pending.length; i++) {
      try {
        await _dio.post<Map<String, dynamic>>(
          '/loyalty/transactions',
          data: withoutOwner(pending[i]),
          options: Options(headers: {'Authorization': 'Bearer $token'}),
        );
      } on DioException catch (e) {
        final code = e.response?.statusCode;
        if (code != null && code >= 400 && code < 500) {
          // Сервер отклонил навсегда (напр. источник теперь считает сам сервер —
          // runnerRun, анти-чит S-04, 403). Выкидываем из очереди, не зацикливаемся.
          continue;
        }
        remaining.addAll(pending.sublist(i)); // офлайн/5xx — остаток оставляем
        break;
      } catch (_) {
        remaining.addAll(pending.sublist(i));
        break;
      }
    }
    await prefs.setString(_pendingKey, jsonEncode(remaining));
  }
}

final loyaltyProvider =
    StateNotifierProvider<LoyaltyNotifier, LoyaltyState>((ref) {
  final notifier = LoyaltyNotifier(ref);
  // Подтягиваем баланс, когда пользователь авторизовался (или уже авторизован).
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
