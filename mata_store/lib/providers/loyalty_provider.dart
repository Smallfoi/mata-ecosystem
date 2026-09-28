import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../data/api/api_client.dart';
import '../data/repositories/loyalty_repository.dart';
import '../models/loyalty.dart';

/// Состояние баллов лояльности. В проде синхронизируется с общим Loyalty Service
/// (баллы из Runner App «Квартал» видны и тратятся здесь).
class LoyaltyProvider extends ChangeNotifier {
  final SharedPreferences _prefs;
  final LoyaltyRepository _repo;

  /// true → баланс берётся с общего backend (по JWT, после логина).
  /// false → локальный сид (offline-прототип).
  final bool serverBacked;

  static const _txnsKey = 'loyalty_txns';
  static const _seededKey = 'loyalty_seeded';

  final List<LoyaltyTransaction> _txns = [];
  String _code = '';
  bool _lastLoggedIn = false;
  String _account = '';

  LoyaltyProvider(this._prefs, this._repo, {this.serverBacked = false}) {
    if (!serverBacked) _loadLocal();
    // serverBacked: данные приходят с backend после логина — см. syncAuth().
  }

  /// Вызывается из ProxyProvider при изменении состояния авторизации. [userId] —
  /// id аккаунта: при выходе ИЛИ смене аккаунта баллы прошлого аккаунта
  /// убираются (аудит C03), для нового загружаются свои.
  Future<void> syncAuth(bool loggedIn, {String? userId}) async {
    if (!serverBacked) return;
    final account = userId ?? '';
    if (loggedIn && (!_lastLoggedIn || account != _account)) {
      final switched = _lastLoggedIn;
      _lastLoggedIn = true;
      _account = account;
      if (switched) _clearAccount();
      await load();
    } else if (!loggedIn && _lastLoggedIn) {
      _lastLoggedIn = false;
      _account = '';
      _clearAccount();
    }
  }

  void _clearAccount() {
    _txns.clear();
    _code = '';
    notifyListeners();
  }

  /// Загрузка баланса с backend (единый аккаунт экосистемы).
  Future<void> load() async {
    final account = _account;
    try {
      final acc = await _repo.fetchAccount();
      // Пока шёл запрос, сменился аккаунт — чужие баллы не показываем.
      if (account != _account) return;
      _txns
        ..clear()
        ..addAll(acc.transactions);
      _code = acc.code;
      notifyListeners();
    } catch (_) {
      // backend недоступен — оставляем текущее состояние
    }
  }

  // ── Геттеры ──────────────────────────────────────────────────────────────
  List<LoyaltyTransaction> get transactions => List.unmodifiable(_txns);
  int get balance => _txns.fold(0, (s, t) => s + t.amount);
  String get code => _code;
  LoyaltyLevel get level => LoyaltyLevelX.forPoints(balance);
  LoyaltyAccount get account =>
      LoyaltyAccount(balance: balance, transactions: _txns, code: _code);

  /// Прогресс к следующему уровню (0..1) и сколько баллов осталось.
  double get levelProgress {
    final nxt = level.next;
    if (nxt == null) return 1;
    final from = level.threshold;
    final to = nxt.threshold;
    return ((balance - from) / (to - from)).clamp(0.0, 1.0);
  }

  int get pointsToNextLevel {
    final nxt = level.next;
    if (nxt == null) return 0;
    return (nxt.threshold - balance).clamp(0, nxt.threshold);
  }

  // ── Загрузка / сохранение ────────────────────────────────────────────────
  void _loadLocal() {
    final raw = _prefs.getString(_txnsKey);
    if (raw != null) {
      try {
        final list = jsonDecode(raw) as List;
        _txns.addAll(
          list.map((j) => LoyaltyTransaction.fromJson(j as Map<String, dynamic>)),
        );
      } catch (_) {}
    }
    // Первый запуск — засеять баллы, как будто заработаны в Runner App «Квартал».
    if (!(_prefs.getBool(_seededKey) ?? false)) {
      _seedDemo();
      _prefs.setBool(_seededKey, true);
    }
  }

  void _save() {
    _prefs.setString(_txnsKey, jsonEncode(_txns.map((t) => t.toJson()).toList()));
  }

  void _seedDemo() {
    final now = DateTime.now();
    final demo = [
      LoyaltyTransaction(
        id: 'seed-1',
        amount: 20,
        source: LoyaltySource.registration,
        description: 'Бонус за регистрацию',
        createdAt: now.subtract(const Duration(days: 14)),
      ),
      LoyaltyTransaction(
        id: 'seed-2',
        amount: 120,
        source: LoyaltySource.runnerRun,
        description: 'Пробежка 12.0 км',
        createdAt: now.subtract(const Duration(days: 9)),
      ),
      LoyaltyTransaction(
        id: 'seed-3',
        amount: 50,
        source: LoyaltySource.runnerTerritory,
        description: 'Захват территории: ул. Спортивная',
        createdAt: now.subtract(const Duration(days: 5)),
      ),
      LoyaltyTransaction(
        id: 'seed-4',
        amount: 200,
        source: LoyaltySource.runnerCompetition,
        description: 'Победа в забеге «Весенний круг»',
        createdAt: now.subtract(const Duration(days: 2)),
      ),
      LoyaltyTransaction(
        id: 'seed-5',
        amount: 40,
        source: LoyaltySource.runnerRun,
        description: 'Пробежка 4.0 км',
        createdAt: now.subtract(const Duration(hours: 6)),
      ),
    ];
    _txns.insertAll(0, demo);
    _save();
  }

  // ── Операции ─────────────────────────────────────────────────────────────
  void _add(int amount, LoyaltySource source, String description,
      {String? orderId}) {
    final tx = LoyaltyTransaction(
      id: 'tx-${DateTime.now().microsecondsSinceEpoch}',
      amount: amount,
      source: source,
      description: description,
      orderId: orderId,
      createdAt: DateTime.now(),
    );
    _txns.insert(0, tx);
    _save();
    notifyListeners();
    _repo.postTransaction(tx); // best-effort синк с backend
  }

  /// Начисление за покупку: +1 балл за каждые 10 ₽ (+50 за первый заказ).
  /// При serverBacked очки начисляет СЕРВЕР при создании заказа (/orders, анти-чит
  /// S-04 Phase 2) — клиент не минтит (иначе задвоит); возвращаем лишь ожидаемую
  /// сумму для UI, баланс подтянется через load() после заказа.
  int earnForPurchase(double orderTotal,
      {required bool isFirstOrder, String? orderId}) {
    if (serverBacked) {
      return (orderTotal / 10).floor() + (isFirstOrder ? 50 : 0);
    }
    final base = (orderTotal / 10).floor();
    if (base > 0) {
      _add(base, LoyaltySource.purchase, 'Покупка на ${orderTotal.toInt()} ₽',
          orderId: orderId);
    }
    if (isFirstOrder) {
      _add(50, LoyaltySource.registration, 'Бонус за первый заказ',
          orderId: orderId);
    }
    return base + (isFirstOrder ? 50 : 0);
  }

  /// Списание баллов при оформлении заказа. Возвращает null при успехе,
  /// иначе текст ошибки (например, «Недостаточно баллов»).
  /// При serverBacked баланс авторитетно считает backend (нельзя уйти в минус,
  /// списание идемпотентно по orderId); после успеха перечитываем баланс с сервера.
  Future<String?> redeem(int points, String orderId) async {
    if (points <= 0) return null;
    if (serverBacked) {
      try {
        await _repo.redeem(
          points: points,
          orderId: orderId,
          description: 'Оплата баллами заказа №$orderId',
        );
        await load();
        return null;
      } catch (e) {
        return _redeemError(e);
      }
    }
    // Офлайн-прототип — списываем локально.
    _add(-points, LoyaltySource.redeem, 'Оплата баллами заказа №$orderId',
        orderId: orderId);
    return null;
  }

  String _redeemError(Object e) {
    if (e is ApiException) {
      if (e.statusCode == 401) return 'Сессия истекла — войдите снова';
      try {
        final detail = (jsonDecode(e.message) as Map)['detail'];
        if (detail is String && detail.isNotEmpty) return detail;
      } catch (_) {}
      if (e.statusCode == 400) return 'Недостаточно баллов';
    }
    return 'Не удалось списать баллы. Попробуйте ещё раз.';
  }

  int maxRedeemable(double orderTotal) => account.maxRedeemable(orderTotal);
}
