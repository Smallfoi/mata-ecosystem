// Программа лояльности v1 (ТЗ владельца 30.09.2026, этап 3 — клиенты).
//
// Всё, что здесь показывается, приходит с сервера (GET /v1/loyalty/account →
// `v1`, POST /v1/loyalty/redeem-preview). Пороги уровней, ставки, потолок
// оплаты и минимум списания — настройки сервера, в сборку не зашиваются.
// Сервер на прежней программе (`programV1` нет или false) → этих объектов нет,
// экраны работают как раньше.
import 'loyalty.dart';

int _int(Object? v, [int fallback = 0]) =>
    v is num ? v.toInt() : (int.tryParse('${v ?? ''}') ?? fallback);

int? _intOrNull(Object? v) => v is num ? v.toInt() : int.tryParse('${v ?? ''}');

double _double(Object? v, [double fallback = 0]) =>
    v is num ? v.toDouble() : (double.tryParse('${v ?? ''}') ?? fallback);

DateTime? _date(Object? v) =>
    v == null ? null : DateTime.tryParse(v.toString())?.toLocal();

String _two(int v) => v.toString().padLeft(2, '0');

/// «12.10» — день и месяц.
String loyaltyDayMonth(DateTime d) => '${_two(d.day)}.${_two(d.month)}';

/// «12.10.2027».
String loyaltyDate(DateTime d) => '${loyaltyDayMonth(d)}.${d.year}';

/// 60000 → «60 000».
String loyaltyGroup(int n) {
  final s = n.abs().toString();
  final b = StringBuffer(n < 0 ? '-' : '');
  for (var i = 0; i < s.length; i++) {
    if (i > 0 && (s.length - i) % 3 == 0) b.write(' ');
    b.write(s[i]);
  }
  return b.toString();
}

/// 0.06 → «6», 0.075 → «7,5».
String loyaltyPercent(double share) {
  final p = (share * 1000).round() / 10;
  return p == p.roundToDouble()
      ? p.toInt().toString()
      : p.toString().replaceAll('.', ',');
}

/// бонус / бонуса / бонусов.
String bonusWord(int n) {
  final a = n.abs() % 100;
  final b = a % 10;
  if (a > 10 && a < 20) return 'бонусов';
  if (b == 1) return 'бонус';
  if (b >= 2 && b <= 4) return 'бонуса';
  return 'бонусов';
}

/// «до Серебра» — уровень в родительном падеже.
String levelGenitive(LoyaltyLevel l) => switch (l) {
      LoyaltyLevel.basic => 'Базового',
      LoyaltyLevel.silver => 'Серебра',
      LoyaltyLevel.gold => 'Золота',
      LoyaltyLevel.platinum => 'Платины',
    };

/// Уровень с действующими настройками сервера (`v1.levels`).
class LoyaltyLevelInfo {
  final LoyaltyLevel level;
  final String title;
  final int threshold;
  final int minSpend;
  final double purchaseRate;
  final double redeemCeiling;
  final int expiryMonths;

  const LoyaltyLevelInfo({
    required this.level,
    required this.title,
    this.threshold = 0,
    this.minSpend = 0,
    this.purchaseRate = 0,
    this.redeemCeiling = 0,
    this.expiryMonths = 0,
  });

  static LoyaltyLevelInfo? fromJson(Object? raw) {
    if (raw is! Map) return null;
    final level = LoyaltyLevelX.fromKey(raw['key']?.toString());
    if (level == null) return null;
    return LoyaltyLevelInfo(
      level: level,
      title: raw['title']?.toString() ?? level.label,
      threshold: _int(raw['threshold']),
      minSpend: _int(raw['minSpend']),
      purchaseRate: _double(raw['purchaseRate']),
      redeemCeiling: _double(raw['redeemCeiling']),
      expiryMonths: _int(raw['expiryMonths']),
    );
  }

  /// Привилегии — только то, что реально даёт сервер: ставка начисления и
  /// потолок оплаты бонусами. Пусто — сервер этих чисел не прислал.
  String get perkText {
    final parts = <String>[
      if (purchaseRate > 0)
        '${loyaltyPercent(purchaseRate)}% бонусами с покупок',
      if (redeemCeiling > 0)
        'оплата бонусами до ${loyaltyPercent(redeemCeiling)}% заказа',
    ];
    return parts.join(' · ');
  }

  /// «от 500 статусных» / «от 5 000 статусных и 60 000 ₽ покупок за год».
  String get conditionText {
    if (threshold <= 0) return 'с первого бонуса';
    final spend = minSpend > 0
        ? ' и ${loyaltyGroup(minSpend)} ₽ покупок за год'
        : '';
    return 'от ${loyaltyGroup(threshold)} статусных$spend';
  }
}

/// Лот — одно начисление со своим сроком (ТЗ §2).
class LoyaltyLot {
  final String id;
  final int amount;
  final int remaining;
  final String state; // held | available
  final String source;
  final DateTime? accruedAt;
  final DateTime? availableAt;
  final DateTime? expiresAt;

  const LoyaltyLot({
    required this.id,
    this.amount = 0,
    this.remaining = 0,
    this.state = 'available',
    this.source = '',
    this.accruedAt,
    this.availableAt,
    this.expiresAt,
  });

  factory LoyaltyLot.fromJson(Map j) => LoyaltyLot(
        id: '${j['id'] ?? ''}',
        amount: _int(j['amount']),
        remaining: _int(j['remaining']),
        state: j['state']?.toString() ?? 'available',
        source: j['source']?.toString() ?? '',
        accruedAt: _date(j['accruedAt']),
        availableAt: _date(j['availableAt']),
        expiresAt: _date(j['expiresAt']),
      );

  bool get held => state == 'held';

  String get sourceLabel => switch (source) {
        'purchase' => 'Покупка',
        'run' || 'accrue_run' || 'runnerRun' => 'Пробежка',
        'capture' || 'accrue_capture' || 'runnerTerritory' => 'Захват квартала',
        'stage' || 'accrue_stage' => 'Победа в этапе',
        'referral' || 'accrue_referral' => 'Приглашение друга',
        'signup' || 'accrue_signup' || 'registration' => 'Бонус за регистрацию',
        'manual' => 'Начисление МАТА',
        'migration' => 'Перенос баланса',
        'legacy_activity' => 'Бег и захваты',
        'legacy' || 'legacy_history' => 'Начисление до новой программы',
        'debt' => 'Долг после возврата',
        _ => 'Бонусы',
      };

  /// «ожидает · доступно с 12.10.2026» / «сгорят 01.03.2027».
  String get dateLine {
    if (held) {
      final at = availableAt;
      return at == null
          ? 'ожидает получения заказа'
          : 'ожидает · доступно с ${loyaltyDate(at)}';
    }
    final exp = expiresAt;
    return exp == null ? 'без срока' : 'сгорят ${loyaltyDate(exp)}';
  }
}

/// Кошелёк программы v1 (`v1` в ответе /loyalty/account).
class LoyaltyV1 {
  final int available; // может быть < 0 — долг после возврата товара
  final int redeemable;
  final int held;
  final int statusPoints;
  final int purchases365;
  final LoyaltyLevel level;
  final DateTime? levelUntil;
  final int? nextLevelThreshold;
  final int platinumMinSpend;
  final int redeemMin;
  final double redeemCeiling;
  final DateTime? heldNextAt;
  final int heldNextAmount;
  final DateTime? expiringAt;
  final int expiringAmount;
  final List<LoyaltyLevelInfo> levels;
  final List<LoyaltyLot> lots;

  const LoyaltyV1({
    this.available = 0,
    this.redeemable = 0,
    this.held = 0,
    this.statusPoints = 0,
    this.purchases365 = 0,
    this.level = LoyaltyLevel.basic,
    this.levelUntil,
    this.nextLevelThreshold,
    this.platinumMinSpend = 0,
    this.redeemMin = 0,
    this.redeemCeiling = 0,
    this.heldNextAt,
    this.heldNextAmount = 0,
    this.expiringAt,
    this.expiringAmount = 0,
    this.levels = const [],
    this.lots = const [],
  });

  /// Блок `v1` из ответа аккаунта. null — сервер на прежней программе
  /// (нет `programV1: true` или нет блока).
  static LoyaltyV1? fromAccount(Map data) {
    if (data['programV1'] != true) return null;
    final v = data['v1'];
    if (v is! Map) return null;
    final level = LoyaltyLevelX.fromKey(v['level']?.toString()) ??
        LoyaltyLevelX.fromKey(data['level']?.toString()) ??
        LoyaltyLevel.basic;
    return LoyaltyV1(
      available: _int(v['available']),
      redeemable: _int(v['redeemable'], _int(data['balance'])),
      held: _int(v['held']),
      statusPoints: _int(v['statusPoints']),
      purchases365: _int(v['purchases365']),
      level: level,
      levelUntil: _date(v['levelUntil']),
      nextLevelThreshold: _intOrNull(v['nextLevelThreshold']),
      platinumMinSpend: _int(v['platinumMinSpend']),
      redeemMin: _int(v['redeemMin']),
      redeemCeiling: _double(v['redeemCeiling']),
      heldNextAt: _date(v['heldNextAt']),
      heldNextAmount: _int(v['heldNextAmount']),
      expiringAt: _date(v['expiringAt']),
      expiringAmount: _int(v['expiringAmount']),
      levels: [
        for (final l in (v['levels'] as List? ?? const []))
          if (LoyaltyLevelInfo.fromJson(l) case final info?) info,
      ],
      lots: [
        for (final l in (v['lots'] as List? ?? const []))
          if (l is Map) LoyaltyLot.fromJson(l),
      ],
    );
  }

  /// Можно потратить сейчас (не меньше нуля).
  int get spendable => redeemable < 0 ? 0 : redeemable;

  LoyaltyLevel? get nextLevel =>
      nextLevelThreshold == null ? null : level.next;

  LoyaltyLevelInfo? infoFor(LoyaltyLevel l) {
    for (final i in levels) {
      if (i.level == l) return i;
    }
    return null;
  }

  // ── Шкала до минимума списания (пока доступно меньше REDEEM_MIN) ─────────
  bool get belowRedeemMin => redeemMin > 0 && spendable < redeemMin;
  double get redeemMinProgress =>
      redeemMin <= 0 ? 1 : (spendable / redeemMin).clamp(0.0, 1.0);
  String get redeemMinText =>
      'Списание от $redeemMin: накоплено $spendable из $redeemMin';

  // ── Шкала уровня (статусные) ──────────────────────────────────────────────
  double get levelProgress {
    final to = nextLevelThreshold;
    if (to == null || to <= 0) return 1;
    return (statusPoints / to).clamp(0.0, 1.0);
  }

  /// «до Серебра: 320 из 500» / у Платины — до какого числа держится уровень.
  String get levelScaleText {
    final nxt = nextLevel;
    final to = nextLevelThreshold;
    if (nxt == null || to == null) {
      final until = levelUntil;
      return until == null
          ? 'Максимальный уровень'
          : 'Максимальный уровень · до ${loyaltyDate(until)}';
    }
    return 'до ${levelGenitive(nxt)}: ${loyaltyGroup(statusPoints)} '
        'из ${loyaltyGroup(to)} статусных';
  }

  // ── Вторая шкала Платины: покупки за 365 дней ─────────────────────────────
  bool get showSpendScale =>
      nextLevel == LoyaltyLevel.platinum && platinumMinSpend > 0;
  double get spendProgress => platinumMinSpend <= 0
      ? 1
      : (purchases365 / platinumMinSpend).clamp(0.0, 1.0);
  String get spendScaleText => 'покупки за год: ${loyaltyGroup(purchases365)} '
      'из ${loyaltyGroup(platinumMinSpend)} ₽';

  // ── Привилегии текущего уровня — только с сервера ─────────────────────────
  String get perkText {
    final info = infoFor(level);
    if (info != null && info.perkText.isNotEmpty) return info.perkText;
    return redeemCeiling > 0
        ? 'оплата бонусами до ${loyaltyPercent(redeemCeiling)}% заказа'
        : '';
  }

  /// «оплата до 20%» — короткая плашка уровня.
  String get ceilingChip => redeemCeiling > 0
      ? 'оплата до ${loyaltyPercent(redeemCeiling)}%'
      : '';

  String get availableText => 'Доступно $spendable ${bonusWord(spendable)}';

  /// Удержание покупочных бонусов (ожидают срока возврата).
  String? get heldLine {
    if (held <= 0) return null;
    final at = heldNextAt;
    if (at == null || heldNextAmount <= 0) {
      return '$held ${bonusWord(held)} ожидают получения заказа';
    }
    final rest = held > heldNextAmount ? ' · всего ожидает $held' : '';
    return 'ещё $heldNextAmount ${bonusWord(heldNextAmount)} станут доступны '
        '${loyaltyDayMonth(at)}$rest';
  }

  /// Ближайшее сгорание.
  String? get expiringLine {
    final at = expiringAt;
    if (at == null || expiringAmount <= 0) return null;
    return '$expiringAmount ${bonusWord(expiringAmount)} сгорят ${loyaltyDate(at)}';
  }

  /// Долг после возврата товара.
  String? get debtLine => available < 0
      ? 'Долг ${-available} ${bonusWord(-available)} — погасится следующими начислениями'
      : null;
}

/// Превью кассы: сколько бонусов можно списать в этой корзине
/// (POST /v1/loyalty/redeem-preview).
class RedeemPreview {
  final bool programV1;
  final int available;
  final int redeemMin;
  final int maxPercent; // прежняя программа
  final double eligibleTotal;
  final double ceiling;
  final int redeemMax;
  final bool canRedeem;
  final String reason;
  final Map<int, String> blockedLines; // индекс позиции → причина

  const RedeemPreview({
    this.programV1 = false,
    this.available = 0,
    this.redeemMin = 0,
    this.maxPercent = 0,
    this.eligibleTotal = 0,
    this.ceiling = 0,
    this.redeemMax = 0,
    this.canRedeem = false,
    this.reason = '',
    this.blockedLines = const {},
  });

  factory RedeemPreview.fromJson(Map j) {
    final blocked = <int, String>{};
    for (final l in (j['lines'] as List? ?? const [])) {
      if (l is Map && l['eligible'] == false) {
        blocked[_int(l['index'], -1)] = l['reason']?.toString() ?? '';
      }
    }
    final rmin = _int(j['redeemMin']);
    final rmax = _int(j['redeemMax']);
    return RedeemPreview(
      programV1: j['programV1'] == true,
      available: _int(j['available']),
      redeemMin: rmin,
      maxPercent: _int(j['maxPercent']),
      eligibleTotal: _double(j['eligibleTotal']),
      ceiling: _double(j['ceiling']),
      redeemMax: rmax,
      canRedeem: j['canRedeem'] is bool ? j['canRedeem'] as bool : rmax >= rmin,
      reason: j['reason']?.toString() ?? '',
      blockedLines: blocked,
    );
  }

  /// Значение ползунка 0..redeemMax с учётом минимума: меньше минимума
  /// списать нельзя — ближе к нулю → 0, иначе → минимум.
  int snap(num value) {
    if (!canRedeem || redeemMax <= 0) return 0;
    var v = value.round();
    if (v <= 0) return 0;
    if (v > redeemMax) v = redeemMax;
    if (v < redeemMin) return v * 2 < redeemMin ? 0 : redeemMin;
    return v;
  }

  /// Пометка позиции, за которую бонусами платить нельзя. null — можно.
  String? lineNote(int index) {
    final r = blockedLines[index];
    if (r == null) return null;
    return switch (r) {
      'markdown' => 'уценка — без оплаты бонусами',
      'excluded_category' => 'не оплачивается бонусами',
      'not_in_catalog' => 'не оплачивается бонусами',
      _ => 'не оплачивается бонусами',
    };
  }

  /// «Списать бонусы можно от 300…» — пояснение, почему ползунок неактивен.
  String get disabledText => reason.isNotEmpty
      ? reason
      : 'Списать бонусы можно от $redeemMin: сейчас доступно $available';
}

/// «5 250 ₽ + 2 250 бонусов» — цена с частичной оплатой бонусами.
String priceWithBonuses(int rub, int bonuses) => bonuses > 0
    ? '${loyaltyGroup(rub)} ₽ + ${loyaltyGroup(bonuses)} ${bonusWord(bonuses)}'
    : '${loyaltyGroup(rub)} ₽';
