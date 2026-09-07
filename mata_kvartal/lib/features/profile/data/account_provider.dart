import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_client.dart';
import '../../auth/data/auth_provider.dart';

/// Настройки приватности (LAUNCH_READINESS §2) и удаление аккаунта (§13).
/// Бэкенд: GET/PATCH /v1/account/privacy, POST /v1/account/delete.
class PrivacySettings {
  final bool profilePublic;
  final bool routePublic;
  final bool realtimePublic;

  const PrivacySettings({
    this.profilePublic = false,
    this.routePublic = false,
    this.realtimePublic = false,
  });

  factory PrivacySettings.fromJson(Map<String, dynamic> j) => PrivacySettings(
        profilePublic: j['profilePublic'] == true,
        routePublic: j['routePublic'] == true,
        realtimePublic: j['realtimePublic'] == true,
      );

  PrivacySettings copyWith({
    bool? profilePublic,
    bool? routePublic,
    bool? realtimePublic,
  }) =>
      PrivacySettings(
        profilePublic: profilePublic ?? this.profilePublic,
        routePublic: routePublic ?? this.routePublic,
        realtimePublic: realtimePublic ?? this.realtimePublic,
      );
}

class AccountState {
  final PrivacySettings privacy;
  final bool loading;
  const AccountState({this.privacy = const PrivacySettings(), this.loading = false});

  AccountState copyWith({PrivacySettings? privacy, bool? loading}) =>
      AccountState(privacy: privacy ?? this.privacy, loading: loading ?? this.loading);
}

class AccountNotifier extends StateNotifier<AccountState> {
  final Ref ref;
  AccountNotifier(this.ref) : super(const AccountState());

  final Dio _dio = ApiClient.create(headers: {'Content-Type': 'application/json', 'Connection': 'close'});

  Options? _auth() {
    final t = ref.read(authProvider).token;
    if (t == null || t.isEmpty) return null;
    return Options(headers: {'Authorization': 'Bearer $t'});
  }

  Future<void> loadPrivacy() async {
    if (_auth() == null) return;
    state = state.copyWith(loading: true);
    try {
      final r = await _dio.get<Map<String, dynamic>>(
        '/account/privacy',
        options: _auth(),
      );
      state = AccountState(
        privacy: r.data != null
            ? PrivacySettings.fromJson(r.data!)
            : state.privacy,
        loading: false,
      );
    } catch (_) {
      state = state.copyWith(loading: false);
    }
  }

  Future<void> setPrivacy({
    bool? profilePublic,
    bool? routePublic,
    bool? realtimePublic,
  }) async {
    // Оптимистично обновляем UI.
    state = state.copyWith(
      privacy: state.privacy.copyWith(
        profilePublic: profilePublic,
        routePublic: routePublic,
        realtimePublic: realtimePublic,
      ),
    );
    final body = <String, dynamic>{};
    if (profilePublic != null) body['profilePublic'] = profilePublic;
    if (routePublic != null) body['routePublic'] = routePublic;
    if (realtimePublic != null) body['realtimePublic'] = realtimePublic;
    try {
      final r = await _dio.patch<Map<String, dynamic>>(
        '/account/privacy',
        data: body,
        options: _auth(),
      );
      if (r.data != null) {
        state = state.copyWith(privacy: PrivacySettings.fromJson(r.data!));
      }
    } catch (_) {
      // офлайн — синхронизируется при следующей загрузке
    }
  }

  /// Необратимо удалить аккаунт и все персональные данные. true — успех.
  Future<bool> deleteAccount() async {
    if (_auth() == null) return false;
    try {
      await _dio.post<dynamic>(
        '/account/delete',
        data: const {'confirm': true},
        options: _auth(),
      );
      return true;
    } catch (_) {
      return false;
    }
  }
}

final accountProvider =
    StateNotifierProvider<AccountNotifier, AccountState>((ref) => AccountNotifier(ref));
