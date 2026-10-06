import 'loyalty_v1.dart';

export 'loyalty_v1.dart';

/// Уровни лояльности (Часть 5 RECOMMENDATION.md / adiClub).
enum LoyaltyLevel { basic, silver, gold, platinum }

extension LoyaltyLevelX on LoyaltyLevel {
  String get label {
    switch (this) {
      case LoyaltyLevel.basic:
        return 'Базовый';
      case LoyaltyLevel.silver:
        return 'Серебро';
      case LoyaltyLevel.gold:
        return 'Золото';
      case LoyaltyLevel.platinum:
        return 'Платина';
    }
  }

  /// Ключ уровня в API (`basic` | `silver` | `gold` | `platinum`).
  String get key => name;

  /// Уровень из строки сервера; неизвестное значение — null.
  static LoyaltyLevel? fromKey(String? key) {
    for (final l in LoyaltyLevel.values) {
      if (l.name == key) return l;
    }
    return null;
  }

  // Привилегии уровней в сборку НЕ зашиваются (ТЗ v1 §6): ставка начисления и
  // потолок оплаты бонусами приходят с сервера (LoyaltyV1.levels), описание —
  // настраиваемый текст. Прежние «кэшбэк 1/2/3/5%», «бесплатная доставка»,
  // «VIP» — убраны: ни одна программа их не даёт.

  /// Порог уровня по баллам ПРЕЖНЕЙ программы (сервер без v1 / офлайн-прототип).
  /// В программе v1 пороги приходят с сервера.
  int get threshold {
    switch (this) {
      case LoyaltyLevel.basic:
        return 0;
      case LoyaltyLevel.silver:
        return 200;
      case LoyaltyLevel.gold:
        return 500;
      case LoyaltyLevel.platinum:
        return 1000;
    }
  }

  /// Следующий уровень (null для платины).
  LoyaltyLevel? get next {
    switch (this) {
      case LoyaltyLevel.basic:
        return LoyaltyLevel.silver;
      case LoyaltyLevel.gold:
        return LoyaltyLevel.platinum;
      case LoyaltyLevel.silver:
        return LoyaltyLevel.gold;
      case LoyaltyLevel.platinum:
        return null;
    }
  }

  static LoyaltyLevel forPoints(int points) {
    if (points >= 1000) return LoyaltyLevel.platinum;
    if (points >= 500) return LoyaltyLevel.gold;
    if (points >= 200) return LoyaltyLevel.silver;
    return LoyaltyLevel.basic;
  }
}

/// Источник операции с баллами (общий для экосистемы: Runner App + Store).
enum LoyaltySource {
  runnerRun,
  runnerTerritory,
  runnerCompetition,
  purchase,
  review,
  registration,
  birthday,
  referral,
  redeem,
}

extension LoyaltySourceX on LoyaltySource {
  String get label {
    switch (this) {
      case LoyaltySource.runnerRun:
        return 'Пробежка в «Квартал»';
      case LoyaltySource.runnerTerritory:
        return 'Захват территории';
      case LoyaltySource.runnerCompetition:
        return 'Победа в соревновании';
      case LoyaltySource.purchase:
        return 'Покупка';
      case LoyaltySource.review:
        return 'Отзыв с фото';
      case LoyaltySource.registration:
        return 'Регистрация';
      case LoyaltySource.birthday:
        return 'День рождения';
      case LoyaltySource.referral:
        return 'Приглашение друга';
      case LoyaltySource.redeem:
        return 'Списание баллов';
    }
  }

  bool get isRunner =>
      this == LoyaltySource.runnerRun ||
      this == LoyaltySource.runnerTerritory ||
      this == LoyaltySource.runnerCompetition;
}

class LoyaltyTransaction {
  final String id;
  final int amount; // + начисление, − списание
  final LoyaltySource source;
  final String description;
  final String? orderId;
  final DateTime createdAt;

  const LoyaltyTransaction({
    required this.id,
    required this.amount,
    required this.source,
    required this.description,
    this.orderId,
    required this.createdAt,
  });

  Map<String, dynamic> toJson() => {
        'id': id,
        'amount': amount,
        'source': source.name,
        'description': description,
        'orderId': orderId,
        'createdAt': createdAt.toIso8601String(),
      };

  factory LoyaltyTransaction.fromJson(Map<String, dynamic> j) =>
      LoyaltyTransaction(
        id: j['id'] as String,
        amount: j['amount'] as int,
        source: LoyaltySource.values.firstWhere(
          (e) => e.name == j['source'],
          orElse: () => LoyaltySource.purchase,
        ),
        description: j['description'] as String,
        orderId: j['orderId'] as String?,
        createdAt: DateTime.parse(j['createdAt'] as String),
      );
}

/// Аккаунт лояльности (баланс + уровень). В проде — Loyalty Service.
class LoyaltyAccount {
  final int balance;
  final List<LoyaltyTransaction> transactions;

  /// Постоянный 6-значный код лояльности клиента (для кассы/QR). Не меняется.
  final String code;

  /// Баллы за бег, которые ещё нельзя потратить: созревают 3 дня или заморожены
  /// на время проверки аккаунта (сервер, 28.09.2026). [balance] — тратимые.
  final int pending;

  /// Всего на счету (тратимые + [pending]); null — сервер старый, не прислал.
  final int? total;

  /// Ближайшая партия созревающих баллов.
  final int pendingNextAmount;
  final DateTime? pendingNextAt;

  /// Аккаунт на проверке — баллы за активность заморожены.
  final bool frozen;

  /// Уровень, присланный сервером (`level`); null — не прислал (офлайн).
  final LoyaltyLevel? serverLevel;

  /// Программа v1 (ТЗ 30.09.2026): кошелёк с лотами, уровни по статусным.
  /// null — сервер на прежней программе, всё как раньше.
  final LoyaltyV1? v1;

  const LoyaltyAccount({
    this.balance = 0,
    this.transactions = const [],
    this.code = '',
    this.pending = 0,
    this.total,
    this.pendingNextAmount = 0,
    this.pendingNextAt,
    this.frozen = false,
    this.serverLevel,
    this.v1,
  });

  bool get programV1 => v1 != null;

  /// Уровень v1 — с сервера (по статусным). Прежняя программа — по всему
  /// накопленному: созревание не понижает статус.
  LoyaltyLevel get level => v1?.level ?? LoyaltyLevelX.forPoints(total ?? balance);

  /// Правила списания (Часть 11.5): 1 балл = 1 ₽, макс 30% заказа, мин 50.
  static const int minRedeem = 50;
  static const double maxRedeemFraction = 0.30;

  /// Сколько баллов можно списать на заказ суммой [orderTotal] — ПРЕЖНЯЯ
  /// программа. В v1 максимум считает сервер по корзине (redeem-preview).
  int maxRedeemable(double orderTotal) {
    if (balance < minRedeem) return 0;
    final cap = (orderTotal * maxRedeemFraction).floor();
    return balance < cap ? balance : cap;
  }
}
