import 'package:dio/dio.dart';
import 'package:flutter/material.dart' show Color;
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_config.dart';
import '../../auth/data/auth_provider.dart';
import '../../profile/data/me_stats_provider.dart';
import '../../run/data/completed_runs_provider.dart';

/// Уровни бегуна по пожизненным километрам (Ф4, утверждено 31.08.2026).
///
/// Уровень никогда не отбирается: километры только копятся. Номер дивизиона —
/// сверху вниз, как в FIFA Rivals: «Лайм» = I, новичок в «Асфальте» = VII.
enum RunnerLevel {
  asphalt('Асфальт', 0),
  dvory('Дворы', 50),
  ulitsa('Улица', 250),
  prospekt('Проспект', 1000),
  rayon('Район', 2500),
  gorod('Город', 5000),
  lime('Лайм', 15000);

  final String title;

  /// Нижняя граница уровня, пожизненные км.
  final int minKm;

  const RunnerLevel(this.title, this.minKm);

  static RunnerLevel fromKm(double km) {
    var level = RunnerLevel.asphalt;
    for (final l in RunnerLevel.values) {
      if (km >= l.minKm) level = l;
    }
    return level;
  }

  /// Номер дивизиона (I — высший «Лайм», VII — стартовый «Асфальт»).
  String get roman =>
      const ['VII', 'VI', 'V', 'IV', 'III', 'II', 'I'][index];

  /// Следующий уровень (null на «Лайме» — статус вечный, потолка нет).
  RunnerLevel? get next =>
      this == RunnerLevel.lime ? null : RunnerLevel.values[index + 1];

  /// Цвет уровня (Ф4): красит шапку статуса. Лайм остаётся цветом «моего»
  /// и действия на всех уровнях — семантика не меняется.
  Color get color => const [
    Color(0xFF8B8F86), // Асфальт
    Color(0xFF7A8F5A), // Дворы
    Color(0xFF4E7D46), // Улица
    Color(0xFF2E6E64), // Проспект — глубокая бирюза
    Color(0xFF3A5A8C), // Район — синий
    Color(0xFF15181B), // Город — чёрный
    Color(0xFFB9CC3A), // Лайм
  ][index];

  /// Прогресс внутри уровня 0..1 по пожизненным км (на «Лайме» всегда 1).
  double progress(double km) {
    final n = next;
    if (n == null) return 1;
    final span = n.minKm - minKm;
    if (span <= 0) return 1;
    return ((km - minKm) / span).clamp(0.0, 1.0);
  }
}

/// Недельный стрик: сколько недель подряд (включая текущую или прошлую)
/// была хотя бы одна пробежка. По локальной истории.
final weekStreakProvider = Provider.autoDispose<int>((ref) {
  final runs = ref.watch(completedRunsProvider);
  if (runs.isEmpty) return 0;
  final weeks = <int>{};
  for (final r in runs) {
    final d = DateTime(r.finishedAt.year, r.finishedAt.month, r.finishedAt.day);
    final monday = d.subtract(Duration(days: d.weekday - 1));
    weeks.add(monday.millisecondsSinceEpoch ~/ 86400000);
  }
  final now = DateTime.now();
  final today = DateTime(now.year, now.month, now.day);
  var monday = today.subtract(Duration(days: today.weekday - 1));
  var streak = 0;
  // Текущая неделя может быть ещё «в работе»: если в ней нет пробежки,
  // стрик считаем с прошлой недели и не обнуляем.
  if (!weeks.contains(monday.millisecondsSinceEpoch ~/ 86400000)) {
    monday = monday.subtract(const Duration(days: 7));
  }
  while (weeks.contains(monday.millisecondsSinceEpoch ~/ 86400000)) {
    streak++;
    monday = monday.subtract(const Duration(days: 7));
  }
  return streak;
});

/// Уровень текущего бегуна — из пожизненных км общего бэка (/me/stats).
final runnerLevelProvider = FutureProvider.autoDispose<RunnerLevel>((ref) async {
  final stats = await ref.watch(meStatsProvider.future);
  return RunnerLevel.fromKm(stats.totalKm);
});

/// Форма недели: пн–вс, был ли в этот день бег (по локальной истории пробежек).
final weekFormProvider = Provider.autoDispose<List<bool>>((ref) {
  final runs = ref.watch(completedRunsProvider);
  final now = DateTime.now();
  final today = DateTime(now.year, now.month, now.day);
  final monday = today.subtract(Duration(days: today.weekday - 1));
  final form = List<bool>.filled(7, false);
  for (final run in runs) {
    final d = DateTime(
      run.finishedAt.year,
      run.finishedAt.month,
      run.finishedAt.day,
    );
    final diff = d.difference(monday).inDays;
    if (diff >= 0 && diff < 7) form[diff] = true;
  }
  return form;
});


// ── Серверный дивизион недели (Квартал 2.0, бэкенд 09.2026) ─────────────────

final _divDio = Dio(
  BaseOptions(
    baseUrl: ApiConfig.baseUrl,
    connectTimeout: ApiConfig.connectTimeout,
    receiveTimeout: ApiConfig.receiveTimeout,
    headers: {'Content-Type': 'application/json', 'Connection': 'close'},
  ),
);

class DivisionMemberRow {
  final String userId;
  final String name;
  final String? club;
  final double km;
  final int place;
  final int? movement;
  final bool isMe;

  const DivisionMemberRow({
    required this.userId,
    required this.name,
    this.club,
    required this.km,
    required this.place,
    this.movement,
    required this.isMe,
  });

  factory DivisionMemberRow.fromJson(Map<String, dynamic> j) =>
      DivisionMemberRow(
        userId: j['userId']?.toString() ?? '',
        name: j['name']?.toString() ?? 'Бегун',
        club: j['club']?.toString(),
        km: (j['km'] as num?)?.toDouble() ?? 0,
        place: (j['place'] as num?)?.toInt() ?? 0,
        movement: (j['movement'] as num?)?.toInt(),
        isMe: j['isMe'] == true,
      );
}

class DivisionData {
  final String name;
  final String tierLabel;
  final String roman;
  final int size;
  final int? myPlace;
  final int? myMovement;
  final List<DivisionMemberRow> members;

  const DivisionData({
    required this.name,
    required this.tierLabel,
    required this.roman,
    required this.size,
    this.myPlace,
    this.myMovement,
    this.members = const [],
  });
}

/// Дивизион недели с бэка: группа до 30 бегунов твоего уровня.
final divisionProvider = FutureProvider.autoDispose<DivisionData?>((ref) async {
  final token = ref.watch(authProvider).token;
  if (token == null || token.isEmpty) return null;
  final res = await _divDio.get<Map<String, dynamic>>(
    '/league/division',
    options: Options(headers: {'Authorization': 'Bearer $token'}),
  );
  final data = res.data ?? {};
  final div = (data['division'] as Map<String, dynamic>?) ?? const {};
  final me = (data['me'] as Map<String, dynamic>?) ?? const {};
  return DivisionData(
    name: div['name']?.toString() ?? 'Дивизион',
    tierLabel: div['tierLabel']?.toString() ?? '',
    roman: div['roman']?.toString() ?? '–',
    size: (div['size'] as num?)?.toInt() ?? 0,
    myPlace: (me['place'] as num?)?.toInt(),
    myMovement: (me['movement'] as num?)?.toInt(),
    members: (data['members'] as List? ?? [])
        .whereType<Map<String, dynamic>>()
        .map(DivisionMemberRow.fromJson)
        .toList(),
  );
});

// ── Итог прошлого сезона (для церемонии) ────────────────────────────────────

class SeasonResultData {
  final String month;
  final int place;
  final int of;
  final double km;
  final int runs;

  const SeasonResultData({
    required this.month,
    required this.place,
    required this.of,
    required this.km,
    required this.runs,
  });
}

final seasonLatestProvider =
    FutureProvider.autoDispose<SeasonResultData?>((ref) async {
  final token = ref.watch(authProvider).token;
  if (token == null || token.isEmpty) return null;
  final res = await _divDio.get<Map<String, dynamic>>(
    '/league/season/latest',
    options: Options(headers: {'Authorization': 'Bearer $token'}),
  );
  final data = res.data ?? {};
  final me = data['me'];
  if (me is! Map<String, dynamic>) return null;
  return SeasonResultData(
    month: data['month']?.toString() ?? '',
    place: (me['place'] as num?)?.toInt() ?? 0,
    of: (me['of'] as num?)?.toInt() ?? 0,
    km: (me['km'] as num?)?.toDouble() ?? 0,
    runs: (me['runs'] as num?)?.toInt() ?? 0,
  );
});
