import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_config.dart';
import '../../auth/data/auth_provider.dart';

/// Относительный media-URL логотипа клуба → абсолютный для Image.network
/// (origin из baseUrl без '/v1'). Буква/эмодзи возвращаем как есть.
String resolveClubMediaUrl(String url) {
  if (url.isEmpty || url.startsWith('http')) return url;
  final origin = ApiConfig.baseUrl.replaceFirst(RegExp(r'/v1/?$'), '');
  return url.startsWith('/') ? '$origin$url' : '$origin/$url';
}

bool clubLogoIsPhoto(String logo) =>
    logo.startsWith('http') || logo.startsWith('/media');

class ClubMember {
  final String userId, name, role;

  /// Вклад участника в км (растёт с забегами). Личные баллы в клубе не показываем.
  final double km;
  const ClubMember({
    required this.userId,
    required this.name,
    required this.role,
    required this.km,
  });
  factory ClubMember.fromJson(Map<String, dynamic> json) => ClubMember(
    userId: json['userId']?.toString() ?? '',
    name: json['name']?.toString() ?? 'Участник',
    role: json['role']?.toString() ?? 'member',
    km: (json['km'] as num?)?.toDouble() ?? 0,
  );
}

/// Вклад участника в клубный челлендж (км за период).
class ClubContribution {
  final String name;
  final double km;
  const ClubContribution({required this.name, required this.km});
  factory ClubContribution.fromJson(Map<String, dynamic> json) =>
      ClubContribution(
        name: json['name']?.toString() ?? 'Участник',
        km: (json['km'] as num?)?.toDouble() ?? 0,
      );
}

/// Клубный челлендж: общая цель по км на период + прогресс и вклад участников.
class ClubChallenge {
  final String id, title;
  final double targetKm, currentKm;
  final int daysLeft, hoursLeft;
  final List<ClubContribution> contributions;
  const ClubChallenge({
    required this.id,
    required this.title,
    required this.targetKm,
    required this.currentKm,
    required this.daysLeft,
    required this.hoursLeft,
    this.contributions = const [],
  });
  factory ClubChallenge.fromJson(Map<String, dynamic> json) => ClubChallenge(
    id: json['id']?.toString() ?? '',
    title: json['title']?.toString() ?? '',
    targetKm: (json['targetKm'] as num?)?.toDouble() ?? 0,
    currentKm: (json['currentKm'] as num?)?.toDouble() ?? 0,
    daysLeft: (json['daysLeft'] as num?)?.toInt() ?? 0,
    hoursLeft: (json['hoursLeft'] as num?)?.toInt() ?? 0,
    contributions: (json['contributions'] as List? ?? const [])
        .whereType<Map<String, dynamic>>()
        .map(ClubContribution.fromJson)
        .toList(),
  );
  double get progress =>
      targetKm <= 0 ? 0 : (currentKm / targetKm).clamp(0.0, 1.0);
  bool get isDone => currentKm >= targetKm && targetKm > 0;
}

class ClubJoinRequest {
  final String id, userId, name;
  const ClubJoinRequest({
    required this.id,
    required this.userId,
    required this.name,
  });
  factory ClubJoinRequest.fromJson(Map<String, dynamic> json) =>
      ClubJoinRequest(
        id: json['id']?.toString() ?? '',
        userId: json['userId']?.toString() ?? '',
        name: json['name']?.toString() ?? 'Участник',
      );
}

class Club {
  final String id, name, logo, ownerId, joinPolicy;
  final String? city, description, myRole;
  final int memberCount;

  /// Пресет оформления клуба (minimal/north/fire/neon/festive).
  final String style;

  /// Обложка-баннер шапки (URL загруженного фото) или null.
  final String? cover;

  /// Активный клубный челлендж (цель по км на период) или null.
  final ClubChallenge? challenge;

  /// Удерживаемая клубом площадь территорий (м²) и число зон.
  final double territoryAreaM2;
  final int territoryPieces;

  /// Активность клуба — суммарный пробег (км), а не баллы.
  final double totalKm;
  final List<ClubMember> members;
  const Club({
    required this.id,
    required this.name,
    required this.logo,
    required this.ownerId,
    required this.joinPolicy,
    required this.memberCount,
    required this.totalKm,
    this.style = 'minimal',
    this.cover,
    this.challenge,
    this.territoryAreaM2 = 0,
    this.territoryPieces = 0,
    this.city,
    this.description,
    this.myRole,
    this.members = const [],
  });
  factory Club.fromJson(Map<String, dynamic> json) => Club(
    id: json['id']?.toString() ?? '',
    name: json['name']?.toString() ?? 'Клуб',
    logo: json['logo']?.toString().trim().isNotEmpty == true
        ? json['logo'].toString()
        : 'K',
    ownerId: json['ownerId']?.toString() ?? '',
    joinPolicy: json['joinPolicy']?.toString() ?? 'open',
    memberCount: (json['memberCount'] as num?)?.toInt() ?? 0,
    totalKm: (json['totalKm'] as num?)?.toDouble() ?? 0,
    style: json['style']?.toString().trim().isNotEmpty == true
        ? json['style'].toString()
        : 'minimal',
    cover: _text(json['cover']?.toString()),
    challenge: json['challenge'] is Map<String, dynamic>
        ? ClubChallenge.fromJson(json['challenge'] as Map<String, dynamic>)
        : null,
    territoryAreaM2: json['territory'] is Map
        ? ((json['territory']['areaM2'] as num?)?.toDouble() ?? 0)
        : 0,
    territoryPieces: json['territory'] is Map
        ? ((json['territory']['pieces'] as num?)?.toInt() ?? 0)
        : 0,
    city: _text(json['city']?.toString()),
    description: _text(json['description']?.toString()),
    myRole: _text(json['myRole']?.toString()),
    members: (json['members'] as List? ?? [])
        .whereType<Map<String, dynamic>>()
        .map(ClubMember.fromJson)
        .toList(),
  );
  bool get isOwner => myRole == 'owner';
  bool get isRequestOnly => joinPolicy == 'request';
}

String? _text(String? value) {
  final text = value?.trim();
  return text == null || text.isEmpty ? null : text;
}

class ClubState {
  final Club? myClub;
  final List<Club> clubs;
  final List<ClubJoinRequest> requests;
  final bool isLoading, isMutating, loaded;
  final String search;
  final String? error, message;
  const ClubState({
    this.myClub,
    this.clubs = const [],
    this.requests = const [],
    this.isLoading = false,
    this.isMutating = false,
    this.loaded = false,
    this.search = '',
    this.error,
    this.message,
  });
  ClubState copyWith({
    Club? myClub,
    List<Club>? clubs,
    List<ClubJoinRequest>? requests,
    bool? isLoading,
    bool? isMutating,
    bool? loaded,
    String? search,
    String? error,
    String? message,
    bool clearClub = false,
    bool clearError = false,
    bool clearMessage = false,
  }) => ClubState(
    myClub: clearClub ? null : myClub ?? this.myClub,
    clubs: clubs ?? this.clubs,
    requests: requests ?? this.requests,
    isLoading: isLoading ?? this.isLoading,
    isMutating: isMutating ?? this.isMutating,
    loaded: loaded ?? this.loaded,
    search: search ?? this.search,
    error: clearError ? null : error ?? this.error,
    message: clearMessage ? null : message ?? this.message,
  );
}

class ClubNotifier extends StateNotifier<ClubState> {
  final Ref ref;
  ClubNotifier(this.ref) : super(const ClubState());

  final Dio _dio = Dio(
    BaseOptions(
      baseUrl: ApiConfig.baseUrl,
      connectTimeout: ApiConfig.connectTimeout,
      receiveTimeout: ApiConfig.receiveTimeout,
      headers: {'Content-Type': 'application/json', 'Connection': 'close'},
    ),
  );

  Future<void> refresh({String? search}) async {
    final token = ref.read(authProvider).token;
    if (token == null || token.isEmpty) {
      state = const ClubState();
      return;
    }
    final nextSearch = search ?? state.search;
    state = state.copyWith(
      isLoading: true,
      search: nextSearch,
      clearError: true,
      clearMessage: true,
    );
    try {
      final options = Options(headers: {'Authorization': 'Bearer $token'});
      final my = await _dio.get<Map<String, dynamic>>(
        '/clubs/me',
        options: options,
      );
      final rawClub = my.data?['club'];
      final myClub = rawClub is Map<String, dynamic>
          ? Club.fromJson(rawClub)
          : null;
      final list = await _dio.get<List<dynamic>>(
        '/clubs',
        queryParameters: nextSearch.trim().isEmpty
            ? null
            : {'search': nextSearch.trim()},
        options: options,
      );
      final clubs = (list.data ?? [])
          .whereType<Map<String, dynamic>>()
          .map(Club.fromJson)
          .toList();
      state = state.copyWith(
        myClub: myClub,
        clubs: clubs,
        isLoading: false,
        loaded: true,
        clearClub: myClub == null,
        clearError: true,
      );
      if (myClub?.isOwner == true) await loadRequests();
    } catch (e) {
      state = state.copyWith(isLoading: false, error: _errorText(e));
    }
  }

  Future<void> createClub({
    required String name,
    required String city,
    required String description,
    required String logo,
    required String joinPolicy,
    String style = 'minimal',
  }) async {
    await _mutate(() async {
      await _dio.post<Map<String, dynamic>>(
        '/clubs',
        data: {
          'name': name,
          'city': city,
          'description': description,
          'logo': logo,
          'joinPolicy': joinPolicy,
          'style': style,
        },
        options: _authOptions(),
      );
      state = state.copyWith(message: 'Клуб создан');
      await refresh();
    });
  }

  Future<void> updateClub({
    required String name,
    required String city,
    required String description,
    required String logo,
    required String joinPolicy,
    String? style,
  }) async {
    final club = state.myClub;
    if (club == null) return;
    await _mutate(() async {
      await _dio.patch<Map<String, dynamic>>(
        '/clubs/${club.id}',
        data: {
          'name': name,
          'city': city,
          'description': description,
          'logo': logo,
          'joinPolicy': joinPolicy,
          if (style != null) 'style': style,
        },
        options: _authOptions(),
      );
      state = state.copyWith(
        message:
            '\u041a\u043b\u0443\u0431 \u043e\u0431\u043d\u043e\u0432\u043b\u0451\u043d',
      );
      await refresh();
    });
  }

  /// Загрузка фото-логотипа клуба (multipart, поле image). Только владелец.
  Future<void> uploadLogo(String filePath) async {
    final club = state.myClub;
    if (club == null) return;
    await _mutate(() async {
      final form = FormData.fromMap({
        'image': await MultipartFile.fromFile(filePath),
      });
      await _dio.post<Map<String, dynamic>>(
        '/clubs/${club.id}/logo',
        data: form,
        options: _authOptions(),
      );
      state = state.copyWith(message: 'Фото клуба обновлено');
      await refresh();
    });
  }

  /// Загрузка обложки-баннера шапки (multipart, поле image). Только владелец.
  Future<void> uploadCover(String filePath) async {
    final club = state.myClub;
    if (club == null) return;
    await _mutate(() async {
      final form = FormData.fromMap({
        'image': await MultipartFile.fromFile(filePath),
      });
      await _dio.post<Map<String, dynamic>>(
        '/clubs/${club.id}/cover',
        data: form,
        options: _authOptions(),
      );
      state = state.copyWith(message: 'Обложка обновлена');
      await refresh();
    });
  }

  /// Снять обложку-баннер (вернуться к стилю-градиенту). Только владелец.
  Future<void> removeCover() async {
    final club = state.myClub;
    if (club == null) return;
    await _mutate(() async {
      await _dio.delete<Map<String, dynamic>>(
        '/clubs/${club.id}/cover',
        options: _authOptions(),
      );
      state = state.copyWith(message: 'Обложка убрана');
      await refresh();
    });
  }

  /// Создать клубный челлендж (цель по км на период). Только владелец.
  Future<void> createChallenge({
    required String title,
    required double targetKm,
    required int days,
  }) async {
    final club = state.myClub;
    if (club == null) return;
    await _mutate(() async {
      await _dio.post<Map<String, dynamic>>(
        '/clubs/${club.id}/challenge',
        data: {'title': title, 'targetKm': targetKm, 'days': days},
        options: _authOptions(),
      );
      state = state.copyWith(message: 'Челлендж создан');
      await refresh();
    });
  }

  /// Завершить активный челлендж. Только владелец.
  Future<void> cancelChallenge() async {
    final club = state.myClub;
    if (club == null) return;
    await _mutate(() async {
      await _dio.delete<Map<String, dynamic>>(
        '/clubs/${club.id}/challenge',
        options: _authOptions(),
      );
      state = state.copyWith(message: 'Челлендж завершён');
      await refresh();
    });
  }

  Future<void> joinClub(Club club) async {
    await _mutate(() async {
      final response = await _dio.post<Map<String, dynamic>>(
        '/clubs/${club.id}/join',
        options: _authOptions(),
      );
      final status = response.data?['status']?.toString();
      state = state.copyWith(
        message: status == 'joined'
            ? 'Ты вступил в клуб'
            : 'Заявка отправлена владельцу',
      );
      if (status == 'joined') await refresh();
    });
  }

  Future<void> joinByInvite(String invite) async {
    final clubId = _clubIdFromInvite(invite);
    if (clubId.isEmpty) {
      state = state.copyWith(
        error:
            '\u0412\u0432\u0435\u0434\u0438 \u043a\u043e\u0434 \u0438\u043b\u0438 \u0441\u0441\u044b\u043b\u043a\u0443 \u043f\u0440\u0438\u0433\u043b\u0430\u0448\u0435\u043d\u0438\u044f',
      );
      return;
    }
    await _mutate(() async {
      final detail = await _dio.get<Map<String, dynamic>>(
        '/clubs/$clubId',
        options: _authOptions(),
      );
      final club = Club.fromJson(detail.data ?? const <String, dynamic>{});
      final response = await _dio.post<Map<String, dynamic>>(
        '/clubs/${club.id}/join',
        options: _authOptions(),
      );
      final status = response.data?['status']?.toString();
      state = state.copyWith(
        message: status == 'joined'
            ? '\u0422\u044b \u0432\u0441\u0442\u0443\u043f\u0438\u043b \u0432 \u043a\u043b\u0443\u0431'
            : '\u0417\u0430\u044f\u0432\u043a\u0430 \u043e\u0442\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u0430 \u0432\u043b\u0430\u0434\u0435\u043b\u044c\u0446\u0443',
      );
      if (status == 'joined') await refresh();
    });
  }

  Future<void> leaveClub() async {
    final club = state.myClub;
    if (club == null) return;
    await _mutate(() async {
      await _dio.post<Map<String, dynamic>>(
        '/clubs/${club.id}/leave',
        options: _authOptions(),
      );
      state = state.copyWith(
        clearClub: true,
        requests: const [],
        message: 'Ты вышел из клуба',
      );
      await refresh();
    });
  }

  Future<void> loadRequests() async {
    final club = state.myClub;
    if (club == null || !club.isOwner) return;
    try {
      final response = await _dio.get<List<dynamic>>(
        '/clubs/${club.id}/requests',
        options: _authOptions(),
      );
      state = state.copyWith(
        requests: (response.data ?? [])
            .whereType<Map<String, dynamic>>()
            .map(ClubJoinRequest.fromJson)
            .toList(),
      );
    } catch (_) {}
  }

  Future<void> approveRequest(String requestId) async {
    await _mutate(() async {
      await _dio.post<Map<String, dynamic>>(
        '/clubs/requests/$requestId/approve',
        options: _authOptions(),
      );
      state = state.copyWith(message: 'Заявка одобрена');
      await refresh();
    });
  }

  Future<void> rejectRequest(String requestId) async {
    await _mutate(() async {
      await _dio.post<Map<String, dynamic>>(
        '/clubs/requests/$requestId/reject',
        options: _authOptions(),
      );
      state = state.copyWith(message: 'Заявка отклонена');
      await loadRequests();
    });
  }

  Future<void> _mutate(Future<void> Function() action) async {
    if (state.isMutating) return;
    state = state.copyWith(
      isMutating: true,
      clearError: true,
      clearMessage: true,
    );
    try {
      await action();
      state = state.copyWith(isMutating: false, clearError: true);
    } catch (e) {
      state = state.copyWith(isMutating: false, error: _errorText(e));
    }
  }

  Options _authOptions() => Options(
    headers: {'Authorization': 'Bearer ${ref.read(authProvider).token}'},
  );

  String _errorText(Object error) {
    if (error is DioException) {
      final data = error.response?.data;
      if (data is Map && data['detail'] != null) {
        return data['detail'].toString();
      }
      if (error.type == DioExceptionType.connectionTimeout ||
          error.type == DioExceptionType.receiveTimeout ||
          error.type == DioExceptionType.connectionError) {
        return 'Не удалось подключиться к серверу. Проверь backend и USB/Wi-Fi.';
      }
    }
    return 'Не удалось выполнить действие. Попробуй ещё раз.';
  }
}

String _clubIdFromInvite(String raw) {
  var value = raw.trim();
  if (value.isEmpty) return '';
  value = value.replaceAll('quartal://club/', '');
  value = value.replaceAll('kvartal://club/', '');
  final uri = Uri.tryParse(value);
  if (uri != null && uri.pathSegments.isNotEmpty) {
    final index = uri.pathSegments.indexOf('club');
    if (index >= 0 && uri.pathSegments.length > index + 1) {
      return uri.pathSegments[index + 1].trim();
    }
    if (uri.host.isNotEmpty) return uri.pathSegments.last.trim();
  }
  return value.split('/').where((part) => part.trim().isNotEmpty).last.trim();
}

final clubProvider = StateNotifierProvider<ClubNotifier, ClubState>((ref) {
  final notifier = ClubNotifier(ref);
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


// ── «Война района» (Квартал 2.0, Ф6, бэкенд 09.2026) ─────────────────────────

class WarStanding {
  final String clubId;
  final String name;
  final double areaM2;
  final int pieces;
  final int place;
  final bool isMine;

  const WarStanding({
    required this.clubId,
    required this.name,
    required this.areaM2,
    required this.pieces,
    required this.place,
    required this.isMine,
  });
}

class WarThreat {
  final String attackerName;
  final String victimName;
  final bool mine;
  final double areaM2;
  final int atMs;

  const WarThreat({
    required this.attackerName,
    required this.victimName,
    required this.mine,
    required this.areaM2,
    required this.atMs,
  });
}

class WarData {
  final List<WarStanding> standings;
  final List<WarThreat> threats;

  const WarData({this.standings = const [], this.threats = const []});
}

final _warDio = Dio(
  BaseOptions(
    baseUrl: ApiConfig.baseUrl,
    connectTimeout: ApiConfig.connectTimeout,
    receiveTimeout: ApiConfig.receiveTimeout,
    headers: {'Content-Type': 'application/json', 'Connection': 'close'},
  ),
);

/// Позиции клубов по земле + лента угроз моего клуба за 7 дней.
final clubWarProvider = FutureProvider.autoDispose<WarData>((ref) async {
  final token = ref.watch(authProvider).token;
  if (token == null || token.isEmpty) return const WarData();
  final res = await _warDio.get<Map<String, dynamic>>(
    '/clubs/war',
    options: Options(headers: {'Authorization': 'Bearer $token'}),
  );
  final data = res.data ?? {};
  return WarData(
    standings: (data['standings'] as List? ?? [])
        .whereType<Map<String, dynamic>>()
        .map(
          (j) => WarStanding(
            clubId: j['clubId']?.toString() ?? '',
            name: j['name']?.toString() ?? 'Клуб',
            areaM2: (j['areaM2'] as num?)?.toDouble() ?? 0,
            pieces: (j['pieces'] as num?)?.toInt() ?? 0,
            place: (j['place'] as num?)?.toInt() ?? 0,
            isMine: j['isMine'] == true,
          ),
        )
        .toList(),
    threats: (data['threats'] as List? ?? [])
        .whereType<Map<String, dynamic>>()
        .map(
          (j) => WarThreat(
            attackerName: j['attackerName']?.toString() ?? 'Бегун',
            victimName: j['victimName']?.toString() ?? 'Бегун',
            mine: j['mine'] == true,
            areaM2: (j['areaM2'] as num?)?.toDouble() ?? 0,
            atMs: (j['atMs'] as num?)?.toInt() ?? 0,
          ),
        )
        .toList(),
  );
});
