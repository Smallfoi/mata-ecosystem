import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_config.dart';
import '../../auth/data/auth_provider.dart';

/// Зачёты лиги и профиль бегуна (docs/LEAGUE_PLAN.md, Э1).
///
/// Смысл лиги: одна и та же пробежка попадает сразу в несколько зачётов, и в
/// каждом выигрывает другой человек. Быстрый берёт абсолютный, регулярный —
/// постоянство, возрастной — свою лигу. Считает всё сервер (античит S-04),
/// приложение только показывает.

/// Доска зачёта. Ключ совпадает с параметром API — не переводим на клиенте,
/// чтобы список зачётов задавался в одном месте.
enum LeagueBoard { absolute, consistency, mylane, personal, club }

extension LeagueBoardX on LeagueBoard {
  String get key => name;

  String get title => switch (this) {
    LeagueBoard.absolute => 'Километры',
    LeagueBoard.consistency => 'Постоянство',
    LeagueBoard.mylane => 'Своя лига',
    LeagueBoard.personal => 'Мой прогресс',
    LeagueBoard.club => 'Клубы',
  };

  /// Одна строка о том, кого этот зачёт держит в игре, — человеку должно быть
  /// понятно, почему таблиц несколько.
  String get hint => switch (this) {
    LeagueBoard.absolute => 'Кто набрал больше километров',
    LeagueBoard.consistency => 'Кто чаще выходил бежать — скорость не важна',
    LeagueBoard.mylane => 'Только ровесники твоего пола',
    LeagueBoard.personal => 'Ты против себя в прошлом периоде',
    LeagueBoard.club => 'Сумма километров участников клуба',
  };
}

class LeagueRow {
  final String id;
  final String name;
  final String? club;
  final double value;
  final int place;
  final bool isMe;

  const LeagueRow({
    required this.id,
    required this.name,
    required this.value,
    required this.place,
    required this.isMe,
    this.club,
  });

  factory LeagueRow.fromJson(Map<String, dynamic> j) => LeagueRow(
    // В клубной доске приходит clubId вместо userId — строка выглядит одинаково.
    id: (j['userId'] ?? j['clubId'])?.toString() ?? '',
    name: j['name']?.toString() ?? '—',
    club: j['club']?.toString(),
    value: (j['value'] as num?)?.toDouble() ?? 0,
    place: (j['place'] as num?)?.toInt() ?? 0,
    isMe: j['isMe'] == true,
  );
}

/// Моё положение в зачёте. `aheadOf` — сколько человек позади: главное число
/// для того, кто никогда не будет первым.
class LeagueMe {
  final int? place;
  final int of;
  final double value;
  final int aheadOf;
  final double? behindNext;

  // Только для «моего прогресса»: сравнение с прошлым периодом.
  final double? prevValue;
  final int? runs;
  final int? prevRuns;
  final double? delta;
  final bool improved;

  const LeagueMe({
    this.place,
    this.of = 0,
    this.value = 0,
    this.aheadOf = 0,
    this.behindNext,
    this.prevValue,
    this.runs,
    this.prevRuns,
    this.delta,
    this.improved = false,
  });

  factory LeagueMe.fromJson(Map<String, dynamic> j) => LeagueMe(
    place: (j['place'] as num?)?.toInt(),
    of: (j['of'] as num?)?.toInt() ?? 0,
    value: (j['value'] as num?)?.toDouble() ?? 0,
    aheadOf: (j['aheadOf'] as num?)?.toInt() ?? 0,
    behindNext: (j['behindNext'] as num?)?.toDouble(),
    prevValue: (j['prevValue'] as num?)?.toDouble(),
    runs: (j['runs'] as num?)?.toInt(),
    prevRuns: (j['prevRuns'] as num?)?.toInt(),
    delta: (j['delta'] as num?)?.toDouble(),
    improved: j['improved'] == true,
  );
}

class LeagueBoardData {
  final LeagueBoard board;
  final String period;
  final String unit;
  final List<LeagueRow> top;
  final LeagueMe me;

  /// «Своя лига» без года рождения и пола работать не может — сравнивать не с кем.
  final bool needsProfile;

  /// Подпись группы сравнения: «Мужчины 30–39».
  final String? groupLabel;

  const LeagueBoardData({
    required this.board,
    required this.period,
    required this.unit,
    required this.top,
    required this.me,
    this.needsProfile = false,
    this.groupLabel,
  });
}

class RunnerProfile {
  final int? birthYear;
  final String? gender;
  final String? level;
  final double? weeklyGoalKm;
  final String? groupLabel;

  /// Ответ на «зачем ты бегаешь»: health | compete | social | calm.
  /// 'skip' — вопрос показали, человек пропустил: больше не спрашиваем.
  final String? focus;

  const RunnerProfile({
    this.birthYear,
    this.gender,
    this.level,
    this.weeklyGoalKm,
    this.groupLabel,
    this.focus,
  });

  /// Спрашивать ли о цели: только если человек ещё не отвечал и не пропускал.
  bool get needsFocus => (focus ?? '').isEmpty;

  bool get isReadyForOwnLane => birthYear != null && (gender ?? '').isNotEmpty;

  factory RunnerProfile.fromJson(Map<String, dynamic> j) => RunnerProfile(
    birthYear: (j['birthYear'] as num?)?.toInt(),
    gender: j['gender']?.toString(),
    level: j['level']?.toString(),
    weeklyGoalKm: (j['weeklyGoalKm'] as num?)?.toDouble(),
    groupLabel: (j['group'] as Map<String, dynamic>?)?['label']?.toString(),
    focus: j['focus']?.toString(),
  );
}

final _leagueDio = Dio(
  BaseOptions(
    baseUrl: ApiConfig.baseUrl,
    connectTimeout: ApiConfig.connectTimeout,
    receiveTimeout: ApiConfig.receiveTimeout,
    // 'Connection: close' — как и в рейтинге: keep-alive поверх adb reverse
    // даёт «Connection closed before full header» (см. PITFALLS).
    headers: {'Content-Type': 'application/json', 'Connection': 'close'},
  ),
);

/// Выбранный зачёт и период. Держим в состоянии, чтобы переключение вкладок
/// не сбрасывало выбор.
final leagueBoardProvider = StateProvider<LeagueBoard>((_) => LeagueBoard.absolute);
final leaguePeriodProvider = StateProvider<String>((_) => 'week');

final leagueBoardDataProvider = FutureProvider.autoDispose<LeagueBoardData>((ref) async {
  final board = ref.watch(leagueBoardProvider);
  final period = ref.watch(leaguePeriodProvider);
  final token = ref.watch(authProvider).token;
  if (token == null || token.isEmpty) {
    return LeagueBoardData(
      board: board,
      period: period,
      unit: 'км',
      top: const [],
      me: const LeagueMe(),
    );
  }

  final res = await _leagueDio.get<Map<String, dynamic>>(
    '/league/boards',
    queryParameters: {'board': board.key, 'period': period},
    options: Options(headers: {'Authorization': 'Bearer $token'}),
  );
  final data = res.data ?? {};
  return LeagueBoardData(
    board: board,
    period: period,
    unit: data['unit']?.toString() ?? 'км',
    top: (data['top'] as List? ?? [])
        .whereType<Map<String, dynamic>>()
        .map(LeagueRow.fromJson)
        .toList(),
    me: LeagueMe.fromJson((data['me'] as Map<String, dynamic>?) ?? const {}),
    needsProfile: data['needsProfile'] == true,
    groupLabel: (data['group'] as Map<String, dynamic>?)?['label']?.toString(),
  );
});

final runnerProfileProvider = FutureProvider.autoDispose<RunnerProfile>((ref) async {
  final token = ref.watch(authProvider).token;
  if (token == null || token.isEmpty) return const RunnerProfile();
  final res = await _leagueDio.get<Map<String, dynamic>>(
    '/runner/profile',
    options: Options(headers: {'Authorization': 'Bearer $token'}),
  );
  return RunnerProfile.fromJson(res.data ?? {});
});

/// Сохранить профиль. Передаём только изменённые поля: сервер остальные не трогает.
Future<RunnerProfile> saveRunnerProfile(
  WidgetRef ref, {
  int? birthYear,
  String? gender,
  String? level,
  double? weeklyGoalKm,
  String? focus,
}) async {
  final token = ref.read(authProvider).token;
  if (token == null || token.isEmpty) return const RunnerProfile();
  final body = <String, dynamic>{};
  if (birthYear != null) body['birthYear'] = birthYear;
  if (gender != null) body['gender'] = gender;
  if (level != null) body['level'] = level;
  if (weeklyGoalKm != null) body['weeklyGoalKm'] = weeklyGoalKm;
  if (focus != null) body['focus'] = focus;

  final res = await _leagueDio.post<Map<String, dynamic>>(
    '/runner/profile',
    data: body,
    options: Options(headers: {'Authorization': 'Bearer $token'}),
  );
  ref.invalidate(runnerProfileProvider);
  ref.invalidate(leagueBoardDataProvider);
  return RunnerProfile.fromJson(res.data ?? {});
}
