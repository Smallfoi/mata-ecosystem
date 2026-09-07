import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_config.dart';
import '../../auth/data/auth_provider.dart';

/// Тропы: участки маршрута, по которым бегают регулярно (D-60).
///
/// Territория даёт повод бежать куда-то, тропа — повод бежать снова. Прохождения
/// находит сервер: телефон отправляет трек забега, сервер сверяет его с тропами
/// района и удаляет трек через 14 дней. Приложение только показывает результат.

class Trail {
  final String id;
  final String name;
  final String? city;
  final int lengthM;
  final bool createdByMe;
  final bool attemptedByMe;

  /// Двойная мотивация прямо в списке (Ф0): моё лучшее и «чаще всех».
  final int? myBestS;
  final int myAttempts;
  final String? frequentLeaderName;
  final bool frequentLeaderIsMe;

  const Trail({
    required this.id,
    required this.name,
    required this.lengthM,
    this.city,
    this.createdByMe = false,
    this.attemptedByMe = false,
    this.myBestS,
    this.myAttempts = 0,
    this.frequentLeaderName,
    this.frequentLeaderIsMe = false,
  });

  String get lengthLabel => lengthM >= 1000
      ? '${(lengthM / 1000).toStringAsFixed(lengthM % 1000 == 0 ? 0 : 1)} км'
      : '$lengthM м';

  factory Trail.fromJson(Map<String, dynamic> j) => Trail(
    id: j['id']?.toString() ?? '',
    name: j['name']?.toString() ?? 'Тропа',
    city: j['city']?.toString(),
    lengthM: (j['lengthM'] as num?)?.toInt() ?? 0,
    createdByMe: j['createdByMe'] == true,
    attemptedByMe: j['attemptedByMe'] == true,
    myBestS: (j['myBestS'] as num?)?.toInt(),
    myAttempts: (j['myAttempts'] as num?)?.toInt() ?? 0,
    frequentLeaderName: (j['frequentLeader'] as Map?)?['name']?.toString(),
    frequentLeaderIsMe: (j['frequentLeader'] as Map?)?['isMe'] == true,
  );
}

/// Доски тропы. Ключи совпадают с параметром API.
enum TrailBoard { fastest, mine, frequent, mylane }

extension TrailBoardX on TrailBoard {
  String get key => name;

  String get title => switch (this) {
    TrailBoard.fastest => 'Быстрейшие',
    TrailBoard.mine => 'Мои попытки',
    TrailBoard.frequent => 'Чаще всех',
    TrailBoard.mylane => 'Своя лига',
  };

  String get hint => switch (this) {
    TrailBoard.fastest => 'Лучшее время каждого',
    TrailBoard.mine => 'Твои прохождения и личный рекорд',
    TrailBoard.frequent => 'Кто прошёл тропу чаще за 90 дней',
    TrailBoard.mylane => 'Только ровесники твоего пола',
  };
}

class TrailRow {
  final String name;
  final String? club;
  final int value;
  final int place;
  final bool isMe;

  const TrailRow({
    required this.name,
    required this.value,
    required this.place,
    required this.isMe,
    this.club,
  });

  factory TrailRow.fromJson(Map<String, dynamic> j) => TrailRow(
    name: j['name']?.toString() ?? '—',
    club: j['club']?.toString(),
    value: (j['value'] as num?)?.toInt() ?? 0,
    place: (j['place'] as num?)?.toInt() ?? 0,
    isMe: j['isMe'] == true,
  );
}

class TrailAttemptRow {
  final int startedAtMs;
  final int durationS;
  const TrailAttemptRow({required this.startedAtMs, required this.durationS});

  factory TrailAttemptRow.fromJson(Map<String, dynamic> j) => TrailAttemptRow(
    startedAtMs: (j['startedAtMs'] as num?)?.toInt() ?? 0,
    durationS: (j['durationS'] as num?)?.toInt() ?? 0,
  );
}

class TrailBoardData {
  final TrailBoard board;
  final String unit;
  final List<TrailRow> top;
  final List<TrailAttemptRow> attempts;
  final int? place;
  final int of;
  final int? value;
  final int aheadOf;
  final int? myBest;
  final int myAttempts;
  final bool needsProfile;

  const TrailBoardData({
    required this.board,
    required this.unit,
    this.top = const [],
    this.attempts = const [],
    this.place,
    this.of = 0,
    this.value,
    this.aheadOf = 0,
    this.myBest,
    this.myAttempts = 0,
    this.needsProfile = false,
  });
}

final _trailsDio = Dio(
  BaseOptions(
    baseUrl: ApiConfig.baseUrl,
    connectTimeout: ApiConfig.connectTimeout,
    receiveTimeout: ApiConfig.receiveTimeout,
    headers: {'Content-Type': 'application/json', 'Connection': 'close'},
  ),
);

final trailsProvider = FutureProvider.autoDispose<List<Trail>>((ref) async {
  final token = ref.watch(authProvider).token;
  if (token == null || token.isEmpty) return const [];
  final res = await _trailsDio.get<Map<String, dynamic>>(
    '/trails/',
    options: Options(headers: {'Authorization': 'Bearer $token'}),
  );
  return ((res.data ?? {})['items'] as List? ?? [])
      .whereType<Map<String, dynamic>>()
      .map(Trail.fromJson)
      .toList();
});

/// Выбранная доска на открытой тропе.
final trailBoardProvider = StateProvider<TrailBoard>((_) => TrailBoard.fastest);

final trailBoardDataProvider = FutureProvider.autoDispose
    .family<TrailBoardData, String>((ref, trailId) async {
  final board = ref.watch(trailBoardProvider);
  final token = ref.watch(authProvider).token;
  if (token == null || token.isEmpty) {
    return TrailBoardData(board: board, unit: 'с');
  }
  final res = await _trailsDio.get<Map<String, dynamic>>(
    '/trails/$trailId/boards',
    queryParameters: {'board': board.key},
    options: Options(headers: {'Authorization': 'Bearer $token'}),
  );
  final data = res.data ?? {};
  final me = (data['me'] as Map<String, dynamic>?) ?? const {};
  return TrailBoardData(
    board: board,
    unit: data['unit']?.toString() ?? 'с',
    top: board == TrailBoard.mine
        ? const []
        : (data['top'] as List? ?? [])
            .whereType<Map<String, dynamic>>()
            .map(TrailRow.fromJson)
            .toList(),
    attempts: board == TrailBoard.mine
        ? (data['top'] as List? ?? [])
            .whereType<Map<String, dynamic>>()
            .map(TrailAttemptRow.fromJson)
            .toList()
        : const [],
    place: (me['place'] as num?)?.toInt(),
    of: (me['of'] as num?)?.toInt() ?? 0,
    value: (me['value'] as num?)?.toInt(),
    aheadOf: (me['aheadOf'] as num?)?.toInt() ?? 0,
    myBest: (me['best'] as num?)?.toInt(),
    myAttempts: (me['attempts'] as num?)?.toInt() ?? 0,
    needsProfile: data['needsProfile'] == true,
  );
});

/// Время прохождения человеческим языком: 7:42, а не 462 секунды.
String formatDuration(int seconds) {
  final m = seconds ~/ 60;
  final s = seconds % 60;
  if (m >= 60) {
    final h = m ~/ 60;
    return '$h:${(m % 60).toString().padLeft(2, '0')}:${s.toString().padLeft(2, '0')}';
  }
  return '$m:${s.toString().padLeft(2, '0')}';
}
