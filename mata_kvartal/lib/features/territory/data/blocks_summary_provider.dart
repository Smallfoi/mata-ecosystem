import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:geolocator/geolocator.dart';

import '../../../core/api/api_client.dart';
import '../../auth/data/auth_provider.dart';

/// «Мои кварталы» (D-74, Ф3б + Ф4): счёт сезона, домашний квартал, районы,
/// войны клубов. Вся арифметика — на сервере (`GET /v1/blocks/summary`);
/// приложение только показывает.

class DistrictLeader {
  final String name;
  final int blocks;
  final bool isMe;
  const DistrictLeader({required this.name, required this.blocks, this.isMe = false});
}

class DistrictScore {
  final String district;
  final int total;
  final int mine;
  final int taken;
  final DistrictLeader? leader;

  const DistrictScore({
    required this.district,
    required this.total,
    required this.mine,
    required this.taken,
    this.leader,
  });

  factory DistrictScore.fromJson(Map<String, dynamic> j) {
    final l = j['leader'];
    return DistrictScore(
      district: j['district']?.toString() ?? '—',
      total: (j['total'] as num?)?.toInt() ?? 0,
      mine: (j['mine'] as num?)?.toInt() ?? 0,
      taken: (j['taken'] as num?)?.toInt() ?? 0,
      leader: l is Map
          ? DistrictLeader(
              name: l['name']?.toString() ?? 'Бегун',
              blocks: (l['blocks'] as num?)?.toInt() ?? 0,
              isMe: l['isMe'] == true,
            )
          : null,
    );
  }
}

class ClubScore {
  final String clubId;
  final String name;
  final int blocks;
  final int place;
  final bool isMine;

  const ClubScore({
    required this.clubId,
    required this.name,
    required this.blocks,
    required this.place,
    this.isMine = false,
  });

  factory ClubScore.fromJson(Map<String, dynamic> j) => ClubScore(
    clubId: j['clubId']?.toString() ?? '',
    name: j['name']?.toString() ?? 'Клуб',
    blocks: (j['blocks'] as num?)?.toInt() ?? 0,
    place: (j['place'] as num?)?.toInt() ?? 0,
    isMine: j['isMine'] == true,
  );
}

class HomeBlock {
  final String blockId;
  final String? district;
  const HomeBlock({required this.blockId, this.district});
}

class BlocksSummary {
  final DateTime seasonEnd;
  final int mine;
  final int total;
  final double cityPercent;
  final HomeBlock? home;
  final List<DistrictScore> districts;
  final List<ClubScore> clubs;
  final bool inClub;

  const BlocksSummary({
    required this.seasonEnd,
    required this.mine,
    required this.total,
    required this.cityPercent,
    this.home,
    this.districts = const [],
    this.clubs = const [],
    this.inClub = false,
  });

  /// Полных дней до конца сезона; последний день — «последний день».
  int daysLeft(DateTime now) {
    final d = seasonEnd.difference(now);
    return d.isNegative ? 0 : (d.inHours / 24).ceil();
  }

  factory BlocksSummary.fromJson(Map<String, dynamic> j) {
    final season = (j['season'] as Map?) ?? const {};
    final home = j['home'];
    return BlocksSummary(
      seasonEnd: DateTime.fromMillisecondsSinceEpoch(
        (season['endMs'] as num?)?.toInt() ?? 0,
      ),
      mine: (j['mine'] as num?)?.toInt() ?? 0,
      total: (j['total'] as num?)?.toInt() ?? 0,
      cityPercent: (j['cityPercent'] as num?)?.toDouble() ?? 0,
      home: home is Map
          ? HomeBlock(
              blockId: home['blockId']?.toString() ?? '',
              district: home['district']?.toString(),
            )
          : null,
      districts: ((j['districts'] as List?) ?? const [])
          .whereType<Map<String, dynamic>>()
          .map(DistrictScore.fromJson)
          .toList(),
      clubs: ((j['clubs'] as List?) ?? const [])
          .whereType<Map<String, dynamic>>()
          .map(ClubScore.fromJson)
          .toList(),
      inClub: j['myClubId'] != null,
    );
  }
}

/// Квартал под ногами — кандидат в дом.
class BlockHere {
  final String blockId;
  final String? district;
  final bool canBeHome;
  final bool isHome;
  const BlockHere({
    required this.blockId,
    this.district,
    this.canBeHome = false,
    this.isHome = false,
  });
}

final _dio = ApiClient.create(
  headers: const {'Content-Type': 'application/json'},
);

Options _auth(String token) =>
    Options(headers: {'Authorization': 'Bearer $token'});

final blocksSummaryProvider =
    FutureProvider.autoDispose<BlocksSummary?>((ref) async {
  final token = ref.watch(authProvider.select((s) => s.token));
  if (token == null || token.isEmpty) return null;
  final res = await _dio.get<Map<String, dynamic>>(
    '/blocks/summary',
    options: _auth(token),
  );
  return BlocksSummary.fromJson(res.data ?? const {});
});

/// Почему не получилось выбрать дом — человеку, а не код ошибки.
class HomeError implements Exception {
  final String message;
  const HomeError(this.message);
  @override
  String toString() => message;
}

/// Действия с домашним кварталом. Вынесены в класс, чтобы тест подменял сеть и GPS.
class HomeActions {
  HomeActions(this.ref);
  final Ref ref;

  String get _token => ref.read(authProvider).token ?? '';

  /// Текущая точка. Нужна ровно один раз — найти квартал; на сервере не хранится.
  Future<Position> _position() async {
    if (!await Geolocator.isLocationServiceEnabled()) {
      throw const HomeError('Включите геолокацию, чтобы найти ваш квартал.');
    }
    var perm = await Geolocator.checkPermission();
    if (perm == LocationPermission.denied) {
      perm = await Geolocator.requestPermission();
    }
    if (perm == LocationPermission.denied ||
        perm == LocationPermission.deniedForever) {
      throw const HomeError('Нет доступа к геолокации.');
    }
    return Geolocator.getCurrentPosition(
      locationSettings: const LocationSettings(accuracy: LocationAccuracy.high),
    );
  }

  /// Квартал, где человек сейчас стоит, или null — рядом кварталов нет.
  Future<BlockHere?> blockHere() async {
    final pos = await _position();
    try {
      final res = await _dio.get<Map<String, dynamic>>(
        '/blocks/here',
        queryParameters: {'lat': pos.latitude, 'lon': pos.longitude},
        options: _auth(_token),
      );
      final b = (res.data ?? const {})['block'];
      if (b is! Map) return null;
      return BlockHere(
        blockId: b['blockId']?.toString() ?? '',
        district: b['district']?.toString(),
        canBeHome: b['canBeHome'] == true,
        isHome: b['home'] == true,
      );
    } on DioException {
      throw const HomeError('Нет связи с сервером. Попробуйте ещё раз.');
    }
  }

  Future<void> setHome(String blockId) async {
    try {
      await _dio.post<Map<String, dynamic>>(
        '/blocks/home',
        data: {'blockId': blockId},
        options: _auth(_token),
      );
    } on DioException catch (e) {
      final detail = (e.response?.data is Map)
          ? (e.response!.data as Map)['detail']?.toString()
          : null;
      throw HomeError(detail ?? 'Нет связи с сервером. Попробуйте ещё раз.');
    }
    ref.invalidate(blocksSummaryProvider);
  }
}

final homeActionsProvider = Provider<HomeActions>(HomeActions.new);
