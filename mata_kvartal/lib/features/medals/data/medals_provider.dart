import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../../../core/api/api_config.dart';
import '../../auth/data/auth_provider.dart';
import 'medal_defs.dart';

/// Состояние наград «Штамп МАТА» с сервера (GET /v1/me/medals).
///
/// Сервер — единственный судья: он присваивает медали лениво и хранит
/// гравировку реверса (значение фиксируется на момент получения). Здесь —
/// только чтение и склейка с каталогом [kMedals].
class MedalState {
  final String id;
  final bool available;
  final int? earnedAtMs;
  final bool isNew;
  final ({String v, String u, String sub})? engraving;
  final ({double cur, num target})? progress;

  const MedalState({
    required this.id,
    required this.available,
    this.earnedAtMs,
    this.isNew = false,
    this.engraving,
    this.progress,
  });

  bool get earned => earnedAtMs != null;

  factory MedalState.fromJson(Map<String, dynamic> j) {
    final e = j['engraving'] as Map<String, dynamic>?;
    final p = j['progress'] as Map<String, dynamic>?;
    return MedalState(
      id: j['id'] as String,
      available: j['available'] as bool? ?? false,
      earnedAtMs: (j['earnedAtMs'] as num?)?.toInt(),
      isNew: j['new'] as bool? ?? false,
      engraving: e == null
          ? null
          : (
              v: e['v'] as String? ?? '',
              u: e['u'] as String? ?? '',
              sub: e['sub'] as String? ?? '',
            ),
      progress: p == null
          ? null
          : (
              cur: (p['cur'] as num?)?.toDouble() ?? 0,
              target: (p['target'] as num?) ?? 1,
            ),
    );
  }
}

/// Медаль целиком: описание из каталога + состояние с сервера.
class MedalFull {
  final MedalDef def;
  final MedalState state;
  const MedalFull(this.def, this.state);

  bool get earned => state.earned;
}

final _medalsDio = Dio(
  BaseOptions(
    baseUrl: ApiConfig.baseUrl,
    connectTimeout: ApiConfig.connectTimeout,
    receiveTimeout: ApiConfig.receiveTimeout,
    headers: {'Content-Type': 'application/json', 'Connection': 'close'},
  ),
);

final medalsProvider = FutureProvider.autoDispose<List<MedalFull>>((ref) async {
  final token = ref.watch(authProvider).token;
  if (token == null || token.isEmpty) {
    return [
      for (final d in kMedals)
        MedalFull(d, MedalState(id: d.id, available: d.waitNote == null)),
    ];
  }
  final res = await _medalsDio.get<Map<String, dynamic>>(
    '/me/medals',
    options: Options(headers: {'Authorization': 'Bearer $token'}),
  );
  final items = (res.data?['items'] as List? ?? const [])
      .cast<Map<String, dynamic>>();
  final byId = {for (final j in items) j['id'] as String: MedalState.fromJson(j)};
  final list = [
    for (final d in kMedals)
      MedalFull(
        d,
        byId[d.id] ?? MedalState(id: d.id, available: d.waitNote == null),
      ),
  ];
  // Первый запуск на устройстве: всё уже заработанное считаем «показанным»,
  // чтобы церемония не выстрелила очередью по старым медалям.
  await MedalCeremonyLedger.seedIfNeeded(list);
  return list;
});

/// Журнал «церемония показана» — чтобы чеканка новой медали игралась один раз.
class MedalCeremonyLedger {
  MedalCeremonyLedger._();

  static const _kShown = 'kvartal.medals.ceremonyShown';
  static const _kSeeded = 'kvartal.medals.seeded';

  static Future<void> seedIfNeeded(List<MedalFull> list) async {
    final p = await SharedPreferences.getInstance();
    if (p.getBool(_kSeeded) ?? false) return;
    await p.setStringList(
      _kShown,
      [for (final m in list.where((m) => m.earned)) m.def.id],
    );
    await p.setBool(_kSeeded, true);
  }

  /// Медали, для которых ещё не игралась церемония.
  static Future<List<MedalFull>> unshown(List<MedalFull> list) async {
    final p = await SharedPreferences.getInstance();
    final shown = (p.getStringList(_kShown) ?? const []).toSet();
    return [for (final m in list) if (m.earned && !shown.contains(m.def.id)) m];
  }

  static Future<void> markShown(String id) async {
    final p = await SharedPreferences.getInstance();
    final shown = (p.getStringList(_kShown) ?? const []).toSet()..add(id);
    await p.setStringList(_kShown, shown.toList());
  }
}
