import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../../../core/api/api_config.dart';

enum AuthStatus { unauthenticated, codeSent, authenticated }

class AuthUser {
  final String id;
  final String name;
  final String email;
  final String? phone;
  final String? city;
  final String? avatarPath;

  const AuthUser({
    required this.id,
    required this.name,
    required this.email,
    this.phone,
    this.city,
    this.avatarPath,
  });

  factory AuthUser.fromJson(Map<String, dynamic> json) => AuthUser(
    id: json['id']?.toString() ?? '',
    name: json['name']?.toString() ?? 'Бегун КВАРТАЛ',
    email: json['email']?.toString() ?? '',
    phone: json['phone']?.toString(),
    city: _cleanProfileText(json['city']?.toString(), fallback: null),
    avatarPath: json['avatarPath']?.toString(),
  );

  Map<String, dynamic> toJson() => {
    'id': id,
    'name': name,
    'email': email,
    'phone': phone,
    'city': city,
    'avatarPath': avatarPath,
  };
}

String? _cleanProfileText(String? value, {required String? fallback}) {
  final text = value?.trim();
  if (text == null || text.isEmpty) return fallback;
  if (RegExp(r'^\?+$').hasMatch(text.replaceAll(RegExp(r'\s+'), ''))) {
    return fallback;
  }
  return text;
}

class AuthState {
  final AuthStatus status;
  final String phone;
  final bool isLoading;
  final String? error;
  final String? token;
  final AuthUser? user;

  const AuthState({
    this.status = AuthStatus.unauthenticated,
    this.phone = '',
    this.isLoading = false,
    this.error,
    this.token,
    this.user,
  });

  AuthState copyWith({
    AuthStatus? status,
    String? phone,
    bool? isLoading,
    String? error,
    String? token,
    AuthUser? user,
    bool clearError = false,
    bool clearSession = false,
  }) => AuthState(
    status: status ?? this.status,
    phone: phone ?? this.phone,
    isLoading: isLoading ?? this.isLoading,
    error: clearError ? null : error ?? this.error,
    token: clearSession ? null : token ?? this.token,
    user: clearSession ? null : user ?? this.user,
  );
}

class AuthNotifier extends StateNotifier<AuthState> {
  AuthNotifier() : super(const AuthState()) {
    restoreSession();
  }

  static const _tokenPrefsKey = 'kvartal.auth.token.v1';
  static const _phonePrefsKey = 'kvartal.auth.phone.v1';
  static const _userIdPrefsKey = 'kvartal.auth.user_id.v1';
  static const _userNamePrefsKey = 'kvartal.auth.user_name.v1';
  static const _userEmailPrefsKey = 'kvartal.auth.user_email.v1';
  static const _userCityPrefsKey = 'kvartal.auth.user_city.v1';
  static const _userAvatarPrefsKey = 'kvartal.auth.user_avatar.v1';

  final Dio _dio = Dio(
    BaseOptions(
      baseUrl: ApiConfig.baseUrl,
      connectTimeout: ApiConfig.connectTimeout,
      receiveTimeout: ApiConfig.receiveTimeout,
      headers: {'Content-Type': 'application/json'},
    ),
  );

  // Токен входа — в защищённом хранилище (Android Keystore / iOS Keychain),
  // а не в открытых SharedPreferences (S-08, launch-gate §13).
  final FlutterSecureStorage _secure = const FlutterSecureStorage(
    aOptions: AndroidOptions(encryptedSharedPreferences: true),
  );
  static const _tokenSecureKey = 'kvartal.auth.token.secure.v1';

  Future<String?> _readToken(SharedPreferences prefs) async {
    try {
      final secure = await _secure.read(key: _tokenSecureKey);
      if (secure != null && secure.isNotEmpty) return secure;
    } catch (_) {}
    // Миграция со старого открытого ключа (одноразово после обновления).
    final legacy = prefs.getString(_tokenPrefsKey);
    if (legacy != null && legacy.isNotEmpty) {
      await _writeToken(legacy);
      await prefs.remove(_tokenPrefsKey);
      return legacy;
    }
    return null;
  }

  Future<void> _writeToken(String token) async {
    try {
      await _secure.write(key: _tokenSecureKey, value: token);
    } catch (_) {}
  }

  Future<void> _deleteToken(SharedPreferences prefs) async {
    try {
      await _secure.delete(key: _tokenSecureKey);
    } catch (_) {}
    await prefs.remove(
      _tokenPrefsKey,
    ); // на случай оставшегося старого значения
  }

  Future<void> restoreSession() async {
    final prefs = await SharedPreferences.getInstance();
    final token = await _readToken(prefs);
    if (token == null || token.isEmpty) return;

    final phone = prefs.getString(_phonePrefsKey) ?? '';
    final cachedUser = AuthUser(
      id: prefs.getString(_userIdPrefsKey) ?? '',
      name: prefs.getString(_userNamePrefsKey) ?? 'Бегун КВАРТАЛ',
      email: prefs.getString(_userEmailPrefsKey) ?? '',
      phone: phone.isEmpty ? null : phone,
      city: _cleanProfileText(
        prefs.getString(_userCityPrefsKey),
        fallback: null,
      ),
      avatarPath: prefs.getString(_userAvatarPrefsKey),
    );

    state = state.copyWith(
      status: AuthStatus.authenticated,
      phone: phone,
      token: token,
      user: cachedUser,
      clearError: true,
    );

    try {
      final response = await _dio.get<Map<String, dynamic>>(
        '/auth/me',
        options: Options(headers: {'Authorization': 'Bearer $token'}),
      );
      final freshUser = AuthUser.fromJson(response.data ?? {});
      await _saveSession(
        token,
        freshUser,
        phone.isEmpty ? freshUser.phone ?? '' : phone,
      );
      state = state.copyWith(user: freshUser, phone: freshUser.phone ?? phone);
    } catch (_) {
      // Если сервер временно недоступен, оставляем локальную сессию для dev-теста карты/GPS.
    }
  }

  /// Запросить код входа. Реально зовёт POST /auth/phone/request (в dev-режиме
  /// сервер печатает код 1234; при включённом SMS_PROVIDER — шлёт SMS).
  /// Если сервер недоступен, всё равно переходим к вводу кода — ошибку сети
  /// покажет verifyCode (dev-friendly: бэкенд мог ещё не подняться).
  Future<void> sendCode(String phone) async {
    state = state.copyWith(isLoading: true, error: null, clearError: true);
    try {
      await _dio.post<Map<String, dynamic>>(
        '/auth/phone/request',
        data: {'phone': phone},
      );
    } catch (_) {}
    state = state.copyWith(
      status: AuthStatus.codeSent,
      phone: phone,
      isLoading: false,
      clearError: true,
    );
  }

  /// Проверить код НА СЕРВЕРЕ (раньше сверялся локально с '1234' и на сервер
  /// уходила константа — с реальными SMS это ломало вход).
  Future<bool> verifyCode(String code) async {
    state = state.copyWith(isLoading: true, error: null, clearError: true);
    try {
      final session = await _loginOrRegisterByPhone(state.phone, code);
      await _saveSession(session.token, session.user, state.phone);
      state = state.copyWith(
        status: AuthStatus.authenticated,
        isLoading: false,
        token: session.token,
        user: session.user,
        clearError: true,
      );
      return true;
    } catch (e) {
      state = state.copyWith(isLoading: false, error: _authErrorText(e));
      return false;
    }
  }

  Future<_BackendSession> _loginOrRegisterByPhone(
    String phone,
    String code,
  ) async {
    return _postAuth('/auth/phone/verify', {
      'phone': phone,
      'code': code,
      'name': 'Бегун КВАРТАЛ',
    });
  }

  // Отложенные данные для флоу с SMS (задаются перед sendCode): цель + имя/пароль.
  String _pendingPurpose = 'login'; // login | register | reset
  String _pendingName = '';
  String _pendingPassword = '';

  void setPending({required String purpose, String name = '', String password = ''}) {
    _pendingPurpose = purpose;
    _pendingName = name;
    _pendingPassword = password;
  }

  /// Вход по ТЕЛЕФОНУ + ПАРОЛЮ (основной путь, #8) — без OTP.
  Future<bool> loginByPassword(String phone, String password) async {
    state = state.copyWith(isLoading: true, error: null, clearError: true);
    try {
      final session = await _postAuth('/auth/login', {'phone': phone, 'password': password});
      await _completeSession(session, phone);
      return true;
    } catch (e) {
      state = state.copyWith(isLoading: false, error: _authErrorText(e));
      return false;
    }
  }

  /// Проверка кода с учётом цели: регистрация / сброс пароля / (легаси) OTP-вход.
  Future<bool> completeWithCode(String code) async {
    state = state.copyWith(isLoading: true, error: null, clearError: true);
    try {
      final session = _pendingPurpose == 'register'
          ? await _postAuth('/auth/register', {
              'phone': state.phone, 'code': code,
              'password': _pendingPassword, 'name': _pendingName,
            })
          : _pendingPurpose == 'reset'
              ? await _postAuth('/auth/password/reset', {
                  'phone': state.phone, 'code': code, 'password': _pendingPassword,
                })
              : await _loginOrRegisterByPhone(state.phone, code);
      await _completeSession(session, state.phone);
      return true;
    } catch (e) {
      state = state.copyWith(isLoading: false, error: _authErrorText(e));
      return false;
    }
  }

  Future<void> _completeSession(_BackendSession session, String phone) async {
    await _saveSession(session.token, session.user, phone);
    state = state.copyWith(
      status: AuthStatus.authenticated,
      isLoading: false,
      token: session.token,
      user: session.user,
      clearError: true,
    );
  }

  Future<_BackendSession> _postAuth(
    String path,
    Map<String, dynamic> body,
  ) async {
    final response = await _dio.post<Map<String, dynamic>>(path, data: body);
    final data = response.data ?? {};
    final token = data['token']?.toString();
    final userJson = data['user'];
    if (token == null || token.isEmpty || userJson is! Map<String, dynamic>) {
      throw const FormatException('Backend вернул неполную сессию');
    }
    return _BackendSession(token, AuthUser.fromJson(userJson));
  }

  Future<void> _saveSession(String token, AuthUser user, String phone) async {
    final prefs = await SharedPreferences.getInstance();
    await _writeToken(token);
    await prefs.setString(_phonePrefsKey, phone);
    await prefs.setString(_userIdPrefsKey, user.id);
    await prefs.setString(_userNamePrefsKey, user.name);
    await prefs.setString(_userEmailPrefsKey, user.email);
    if (user.city == null || user.city!.isEmpty) {
      await prefs.remove(_userCityPrefsKey);
    } else {
      await prefs.setString(_userCityPrefsKey, user.city!);
    }
    if (user.avatarPath == null || user.avatarPath!.isEmpty) {
      await prefs.remove(_userAvatarPrefsKey);
    } else {
      await prefs.setString(_userAvatarPrefsKey, user.avatarPath!);
    }
  }

  Future<bool> updateProfile({
    required String name,
    String? phone,
    String? email,
    String? city,
    String? avatarPath,
  }) async {
    final token = state.token;
    if (token == null || token.isEmpty) {
      state = state.copyWith(error: 'Сессия истекла. Войди ещё раз.');
      return false;
    }

    state = state.copyWith(isLoading: true, clearError: true);
    try {
      final response = await _dio.patch<Map<String, dynamic>>(
        '/profile',
        data: {
          'name': name,
          'phone': phone,
          'email': email,
          'city': city,
          'avatarPath': avatarPath,
        },
        options: Options(headers: {'Authorization': 'Bearer $token'}),
      );
      final user = AuthUser.fromJson(response.data ?? {});
      await _saveSession(token, user, user.phone ?? state.phone);
      state = state.copyWith(
        isLoading: false,
        phone: user.phone ?? state.phone,
        user: user,
        clearError: true,
      );
      return true;
    } catch (e) {
      state = state.copyWith(isLoading: false, error: _authErrorText(e));
      return false;
    }
  }

  /// Загрузить фото профиля (единый аватар экосистемы). Multipart на сервер →
  /// avatar_path в media; все приложения берут аватар по /auth/me.
  Future<bool> uploadAvatar(String filePath) async {
    final token = state.token;
    if (token == null || token.isEmpty) return false;
    state = state.copyWith(isLoading: true, clearError: true);
    try {
      final form = FormData.fromMap({
        'image': await MultipartFile.fromFile(filePath),
      });
      final response = await _dio.post<Map<String, dynamic>>(
        '/profile/avatar',
        data: form,
        options: Options(headers: {'Authorization': 'Bearer $token'}),
      );
      final user = AuthUser.fromJson(response.data ?? {});
      await _saveSession(token, user, user.phone ?? state.phone);
      state = state.copyWith(isLoading: false, user: user, clearError: true);
      return true;
    } catch (e) {
      state = state.copyWith(isLoading: false, error: _authErrorText(e));
      return false;
    }
  }

  /// Снять фото профиля (вернуться к инициалам).
  Future<bool> removeAvatar() async {
    final token = state.token;
    if (token == null || token.isEmpty) return false;
    try {
      final response = await _dio.delete<Map<String, dynamic>>(
        '/profile/avatar',
        options: Options(headers: {'Authorization': 'Bearer $token'}),
      );
      final user = AuthUser.fromJson(response.data ?? {});
      await _saveSession(token, user, user.phone ?? state.phone);
      state = state.copyWith(user: user);
      return true;
    } catch (_) {
      return false;
    }
  }

  String _authErrorText(Object error) {
    if (error is DioException) {
      if (error.type == DioExceptionType.connectionTimeout ||
          error.type == DioExceptionType.receiveTimeout ||
          error.type == DioExceptionType.connectionError) {
        return 'Не удалось подключиться к серверу. Проверь backend и USB/Wi-Fi соединение.';
      }
      final message = error.response?.data;
      if (message is Map && message['detail'] != null) {
        return message['detail'].toString();
      }
      if (error.response?.statusCode == 401) {
        return 'Неверный код. Попробуй ещё раз';
      }
    }
    return 'Не удалось войти. Попробуй ещё раз.';
  }

  Future<void> logout() async {
    final prefs = await SharedPreferences.getInstance();
    await _deleteToken(prefs);
    await prefs.remove(_phonePrefsKey);
    await prefs.remove(_userIdPrefsKey);
    await prefs.remove(_userNamePrefsKey);
    await prefs.remove(_userEmailPrefsKey);
    await prefs.remove(_userCityPrefsKey);
    await prefs.remove(_userAvatarPrefsKey);
    state = const AuthState();
  }
}

class _BackendSession {
  final String token;
  final AuthUser user;

  const _BackendSession(this.token, this.user);
}

final authProvider = StateNotifierProvider<AuthNotifier, AuthState>(
  (_) => AuthNotifier(),
);
