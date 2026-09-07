import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:geolocator/geolocator.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../../../core/api/api_client.dart';
import '../../../core/api/api_config.dart';
import '../../auth/data/auth_provider.dart';

/// Беговое соревнование (старт) для вкладки «Старты».
/// Данные с общего backend (`GET /v1/races`). JSON — camelCase, парсим защитно.
class RaceEvent {
  final int id;
  final String title;
  final String city;
  final String region;
  final String place;
  final String type;
  final String typeLabel;
  final String regStatus; // open | soon | closed | done
  final String regUrl;
  final String description;
  final String coverUrl;
  final DateTime? date;
  final List<String> distances;
  final int points;

  const RaceEvent({
    required this.id,
    required this.title,
    required this.city,
    required this.region,
    required this.place,
    required this.type,
    required this.typeLabel,
    required this.regStatus,
    required this.regUrl,
    required this.description,
    required this.coverUrl,
    required this.date,
    required this.distances,
    required this.points,
  });

  factory RaceEvent.fromJson(Map<String, dynamic> j) => RaceEvent(
        id: (j['id'] as num?)?.toInt() ?? 0,
        title: j['title']?.toString() ?? '',
        city: j['city']?.toString() ?? '',
        region: j['region']?.toString() ?? '',
        place: j['place']?.toString() ?? '',
        type: j['type']?.toString() ?? 'other',
        typeLabel: j['typeLabel']?.toString() ?? '',
        regStatus: j['regStatus']?.toString() ?? 'soon',
        regUrl: j['regUrl']?.toString() ?? '',
        description: j['description']?.toString() ?? '',
        coverUrl: ApiConfig.resolveMedia(j['coverUrl']?.toString() ?? ''),
        date: DateTime.tryParse(j['date']?.toString() ?? ''),
        distances: ((j['distances'] as List?) ?? const [])
            .map((e) => e.toString())
            .toList(),
        points: (j['points'] as num?)?.toInt() ?? 0,
      );

  /// Для локального сохранения в «Мои старты» (обратно читается через fromJson).
  Map<String, dynamic> toJson() => {
        'id': id,
        'title': title,
        'city': city,
        'region': region,
        'place': place,
        'type': type,
        'typeLabel': typeLabel,
        'regStatus': regStatus,
        'regUrl': regUrl,
        'description': description,
        'coverUrl': coverUrl,
        'date': date?.toIso8601String(),
        'distances': distances,
        'points': points,
      };

  bool get isPast {
    final d = date;
    if (d == null) return false;
    final now = DateTime.now();
    return d.isBefore(DateTime(now.year, now.month, now.day));
  }
}

/// Лента «Стартов»: забеги + подпись выбранного режима/региона (для шапки).
class RacesFeed {
  final List<RaceEvent> items;
  final String region; // подпись: «Республика Саха (Якутия)» / «Вся Россия» / «Крупные марафоны»
  const RacesFeed({required this.items, required this.region});
}

/// Режим показа афиши (переключатель региона в шапке «Стартов»).
/// saved — «Мои старты» (сохранённые локально, показываются вне фильтра региона).
enum RegionMode { myRegion, all, majors, region, saved }

/// Текущий выбор региона. По умолчанию — «мой регион» (из профиля/GPS).
class RegionSelection {
  final RegionMode mode;
  final String slug; // для mode == region
  final String label; // запасная подпись до загрузки ленты
  const RegionSelection({this.mode = RegionMode.myRegion, this.slug = '', this.label = ''});

  static const my = RegionSelection();
  static const russia = RegionSelection(mode: RegionMode.all, label: 'Вся Россия');
  static const majors = RegionSelection(mode: RegionMode.majors, label: 'Крупные марафоны');
  static const saved = RegionSelection(mode: RegionMode.saved, label: 'Мои старты');
  factory RegionSelection.region(String slug, String name) =>
      RegionSelection(mode: RegionMode.region, slug: slug, label: name);
}

/// «Мои старты» — забеги, которые пользователь отметил «Планирую поехать».
/// Хранятся локально (shared_preferences), целиком — чтобы показывать даже старты
/// из других регионов, которые обычный фильтр бы скрыл.
class PlannedRacesNotifier extends StateNotifier<List<RaceEvent>> {
  PlannedRacesNotifier() : super(const []) {
    _load();
  }
  static const _key = 'kvartal.races.planned.v1';

  Future<void> _load() async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getStringList(_key) ?? const [];
    state = raw
        .map((s) {
          try {
            return RaceEvent.fromJson(jsonDecode(s) as Map<String, dynamic>);
          } catch (_) {
            return null;
          }
        })
        .whereType<RaceEvent>()
        .toList();
  }

  Future<void> _save() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setStringList(
        _key, state.map((r) => jsonEncode(r.toJson())).toList());
  }

  bool contains(int id) => state.any((r) => r.id == id);

  /// Добавить/убрать старт. Возвращает true, если после действия он в списке.
  Future<bool> toggle(RaceEvent r) async {
    final has = contains(r.id);
    state = has
        ? state.where((x) => x.id != r.id).toList()
        : [...state, r];
    await _save();
    return !has;
  }
}

final plannedRacesProvider =
    StateNotifierProvider<PlannedRacesNotifier, List<RaceEvent>>(
        (ref) => PlannedRacesNotifier());

/// Выбранный режим/регион. Меняется из пикера — лента перезапрашивается.
final raceSelectionProvider = StateProvider<RegionSelection>((ref) => RegionSelection.my);

/// Регион с забегами (для пикера «показать другой регион»).
class RaceRegion {
  final String slug;
  final String name;
  final int count;
  const RaceRegion({required this.slug, required this.name, required this.count});
  factory RaceRegion.fromJson(Map<String, dynamic> j) => RaceRegion(
        slug: j['slug']?.toString() ?? '',
        name: j['name']?.toString() ?? '',
        count: (j['count'] as num?)?.toInt() ?? 0,
      );
}

final _racesDio = ApiClient.create();

/// Последняя известная позиция (без запроса свежего фикса — мгновенно, не блокирует).
/// Для «моего региона» как fallback, если город в профиле не заполнен.
Future<Position?> _lastKnownPosition() async {
  try {
    return await Geolocator.getLastKnownPosition();
  } catch (_) {
    return null;
  }
}

/// Афиша забегов (публичный эндпоинт — токен не нужен). Режим выбирается пикером:
/// «мой регион» (город из профиля + GPS-fallback), «вся Россия», «крупные марафоны»
/// или конкретный регион (слаг). Меняется выбор — лента перезапрашивается.
/// TODO: авто-парсер источников (Celery).
final racesProvider = FutureProvider.autoDispose<RacesFeed>((ref) async {
  final sel = ref.watch(raceSelectionProvider);

  // «Мои старты» — целиком из локального хранилища, без сети.
  if (sel.mode == RegionMode.saved) {
    final planned = ref.watch(plannedRacesProvider);
    return RacesFeed(items: planned, region: 'Мои старты');
  }

  final city = ref.watch(authProvider.select((s) => s.user?.city))?.trim() ?? '';

  final qp = <String, dynamic>{};
  switch (sel.mode) {
    case RegionMode.all:
      qp['all'] = '1';
      break;
    case RegionMode.majors:
      qp['scope'] = 'federal';
      break;
    case RegionMode.region:
      qp['region'] = sel.slug;
      break;
    case RegionMode.myRegion:
      if (city.isNotEmpty) qp['city'] = city;
      // GPS-fallback: если города нет — регион определит бэкенд по координатам.
      final pos = await _lastKnownPosition();
      if (pos != null) {
        qp['lat'] = pos.latitude;
        qp['lng'] = pos.longitude;
      }
      break;
    case RegionMode.saved:
      break; // обработано выше
  }

  final res = await _racesDio.get<Map<String, dynamic>>('/races', queryParameters: qp);
  final items = (res.data?['races'] as List? ?? const [])
      .whereType<Map<String, dynamic>>()
      .map(RaceEvent.fromJson)
      .toList();
  return RacesFeed(items: items, region: res.data?['region']?.toString() ?? '');
});

/// Список регионов с забегами (для пикера).
final raceRegionsProvider = FutureProvider.autoDispose<List<RaceRegion>>((ref) async {
  final res = await _racesDio.get<Map<String, dynamic>>('/races/regions');
  return (res.data?['regions'] as List? ?? const [])
      .whereType<Map<String, dynamic>>()
      .map(RaceRegion.fromJson)
      .toList();
});
