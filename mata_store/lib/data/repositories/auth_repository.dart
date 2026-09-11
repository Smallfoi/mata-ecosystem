import '../../models/auth_user.dart';
import '../../models/me_stats.dart';
import '../api/api_client.dart';

/// Контракт аутентификации. Валидация форм остаётся в `AuthProvider`,
/// здесь — обращение к backend (или его имитация).
abstract class AuthRepository {
  Future<AuthUser> login(String email, String password);
  Future<AuthUser> loginByPhone(String phone, String code, {String? name});
  Future<AuthUser> register(String name, String email, String password);
  // Вход/регистрация по ТЕЛЕФОНУ+ПАРОЛЮ (основной путь экосистемы, #8).
  Future<AuthUser> loginByPassword(String phone, String password);
  Future<SmsCodeInfo> requestSmsCode(String phone);
  Future<AuthUser> registerByPhone(String phone, String code, String password, String name);
  Future<AuthUser> resetPasswordByPhone(String phone, String code, String password);
  Future<void> sendPasswordReset(String email);
  Future<void> resetPassword(String newPassword);
  Future<void> changePassword(String oldPassword, String newPassword);

  /// Обновление профиля на backend (источник правды). Возвращает актуального юзера.
  Future<AuthUser> updateProfile(
    AuthUser current, {
    String? name,
    String? phone,
    String? city,
    String? avatarPath,
    String? email,
    List<SavedAddress>? addresses,
  });

  /// Профиль текущего пользователя по JWT (GET /auth/me).
  Future<AuthUser> fetchMe();

  /// Личная статистика (GET /me/stats): забеги/км, баллы, заказы.
  Future<MeStats> fetchStats();

  /// Загрузить серверный аватар (единый для экосистемы) → актуальный юзер.
  Future<AuthUser> uploadAvatar(String filePath);

  /// Снять серверный аватар.
  Future<AuthUser> removeAvatar();

  /// Видимость профиля (часть общих настроек приватности аккаунта).
  Future<bool> getProfilePublic();
  Future<bool> setProfilePublic(bool value);

  /// Необратимое удаление аккаунта и всех персональных данных (152-ФЗ, §13).
  Future<void> deleteAccount();
}

class MockAuthRepository implements AuthRepository {
  @override
  Future<AuthUser> login(String email, String password) async {
    await Future.delayed(const Duration(milliseconds: 1400));
    return AuthUser(name: email.split('@').first, email: email.trim());
  }

  @override
  Future<AuthUser> loginByPhone(
    String phone,
    String code, {
    String? name,
  }) async {
    await Future.delayed(const Duration(milliseconds: 800));
    return AuthUser(
      id: 'local-phone-${phone.replaceAll(RegExp(r'\D'), '')}',
      name: (name == null || name.trim().isEmpty) ? 'Бегун' : name.trim(),
      email: 'runner_${phone.replaceAll(RegExp(r'\D'), '')}@kvartal.local',
      phone: phone.trim(),
      provider: LoginProvider.phone,
    );
  }

  @override
  Future<AuthUser> register(String name, String email, String password) async {
    await Future.delayed(const Duration(milliseconds: 1400));
    return AuthUser(name: name.trim(), email: email.trim());
  }

  @override
  Future<AuthUser> loginByPassword(String phone, String password) async {
    await Future.delayed(const Duration(milliseconds: 900));
    return AuthUser(name: 'Гость', email: 'u_$phone@mata.local', phone: phone, provider: LoginProvider.phone);
  }

  @override
  Future<SmsCodeInfo> requestSmsCode(String phone) async {
    await Future.delayed(const Duration(milliseconds: 600));
    return const SmsCodeInfo(); // без backend — режим разработки, код 1234
  }

  @override
  Future<AuthUser> registerByPhone(String phone, String code, String password, String name) async {
    await Future.delayed(const Duration(milliseconds: 1200));
    return AuthUser(name: name.trim(), email: 'u_$phone@mata.local', phone: phone, provider: LoginProvider.phone);
  }

  @override
  Future<AuthUser> resetPasswordByPhone(String phone, String code, String password) async {
    await Future.delayed(const Duration(milliseconds: 1000));
    return AuthUser(name: 'Гость', email: 'u_$phone@mata.local', phone: phone, provider: LoginProvider.phone);
  }

  @override
  Future<void> sendPasswordReset(String email) async {
    await Future.delayed(const Duration(milliseconds: 1200));
  }

  @override
  Future<void> resetPassword(String newPassword) async {
    await Future.delayed(const Duration(milliseconds: 1000));
  }

  @override
  Future<void> changePassword(String oldPassword, String newPassword) async {
    await Future.delayed(const Duration(milliseconds: 800));
  }

  @override
  Future<AuthUser> updateProfile(
    AuthUser current, {
    String? name,
    String? phone,
    String? city,
    String? avatarPath,
    String? email,
    List<SavedAddress>? addresses,
  }) async {
    await Future.delayed(const Duration(milliseconds: 300));
    return AuthUser(
      id: current.id,
      name: (name?.trim().isNotEmpty == true) ? name!.trim() : current.name,
      email: (email?.trim().isNotEmpty == true) ? email!.trim() : current.email,
      phone: phone != null
          ? (phone.trim().isNotEmpty ? phone.trim() : null)
          : current.phone,
      city: city != null
          ? (city.trim().isNotEmpty ? city.trim() : null)
          : current.city,
      provider: current.provider,
      addresses: addresses ?? current.addresses,
      avatarPath: avatarPath ?? current.avatarPath,
    );
  }

  @override
  Future<AuthUser> fetchMe() async =>
      throw UnimplementedError('Mock не имеет /auth/me');

  @override
  Future<MeStats> fetchStats() async => const MeStats();

  @override
  Future<AuthUser> uploadAvatar(String filePath) async =>
      throw UnimplementedError('Mock не грузит аватар');

  @override
  Future<AuthUser> removeAvatar() async =>
      throw UnimplementedError('Mock не грузит аватар');

  @override
  Future<bool> getProfilePublic() async => false;

  @override
  Future<bool> setProfilePublic(bool value) async => value;

  @override
  Future<void> deleteAccount() async {}
}

class ApiAuthRepository implements AuthRepository {
  final ApiClient _client;
  ApiAuthRepository(this._client);

  @override
  Future<AuthUser> login(String email, String password) async {
    final data = await _client.post(
      '/auth/login',
      body: {'email': email, 'password': password},
    );
    final map = data as Map<String, dynamic>;
    _client.authToken = map['token'] as String?;
    return AuthUser.fromJson(map['user'] as Map<String, dynamic>);
  }

  @override
  Future<AuthUser> loginByPhone(
    String phone,
    String code, {
    String? name,
  }) async {
    final data = await _client.post(
      '/auth/phone/verify',
      body: {
        'phone': phone,
        'code': code,
        'name': (name == null || name.trim().isEmpty) ? 'Бегун' : name.trim(),
      },
    );
    final map = data as Map<String, dynamic>;
    _client.authToken = map['token'] as String?;
    return AuthUser.fromJson(map['user'] as Map<String, dynamic>);
  }

  @override
  Future<AuthUser> register(String name, String email, String password) async {
    final data = await _client.post(
      '/auth/register',
      body: {'name': name, 'email': email, 'password': password},
    );
    final map = data as Map<String, dynamic>;
    _client.authToken = map['token'] as String?;
    return AuthUser.fromJson(map['user'] as Map<String, dynamic>);
  }

  @override
  Future<AuthUser> loginByPassword(String phone, String password) async {
    final data = await _client.post(
      '/auth/login',
      body: {'phone': phone, 'password': password},
    );
    final map = data as Map<String, dynamic>;
    _client.authToken = map['token'] as String?;
    return AuthUser.fromJson(map['user'] as Map<String, dynamic>);
  }

  @override
  Future<SmsCodeInfo> requestSmsCode(String phone) async {
    final data = await _client.post('/auth/phone/request', body: {'phone': phone});
    return data is Map ? SmsCodeInfo.fromJson(data) : const SmsCodeInfo();
  }

  @override
  Future<AuthUser> registerByPhone(String phone, String code, String password, String name) async {
    final data = await _client.post(
      '/auth/register',
      body: {'phone': phone, 'code': code, 'password': password, 'name': name},
    );
    final map = data as Map<String, dynamic>;
    _client.authToken = map['token'] as String?;
    return AuthUser.fromJson(map['user'] as Map<String, dynamic>);
  }

  @override
  Future<AuthUser> resetPasswordByPhone(String phone, String code, String password) async {
    final data = await _client.post(
      '/auth/password/reset',
      body: {'phone': phone, 'code': code, 'password': password},
    );
    final map = data as Map<String, dynamic>;
    _client.authToken = map['token'] as String?;
    return AuthUser.fromJson(map['user'] as Map<String, dynamic>);
  }

  @override
  Future<void> sendPasswordReset(String email) async {
    await _client.post('/auth/password/forgot', body: {'email': email});
  }

  @override
  Future<void> resetPassword(String newPassword) async {
    await _client.post('/auth/password/reset', body: {'password': newPassword});
  }

  @override
  Future<void> changePassword(String oldPassword, String newPassword) async {
    await _client.put(
      '/auth/password',
      body: {'old': oldPassword, 'new': newPassword},
    );
  }

  @override
  Future<AuthUser> updateProfile(
    AuthUser current, {
    String? name,
    String? phone,
    String? city,
    String? avatarPath,
    String? email,
    List<SavedAddress>? addresses,
  }) async {
    final body = <String, dynamic>{};
    if (name != null) body['name'] = name;
    if (phone != null) body['phone'] = phone;
    if (city != null) body['city'] = city;
    if (avatarPath != null) body['avatarPath'] = avatarPath;
    if (email != null && email.trim().isNotEmpty) body['email'] = email.trim();
    // Адреса доставки — единые в экосистеме (структурные объекты на бэк).
    if (addresses != null) {
      body['addresses'] = addresses.map((a) => a.toJson()).toList();
    }
    final data = await _client.patch('/profile', body: body);
    return AuthUser.fromJson(data as Map<String, dynamic>);
  }

  @override
  Future<AuthUser> fetchMe() async {
    final data = await _client.get('/auth/me');
    return AuthUser.fromJson(data as Map<String, dynamic>);
  }

  @override
  Future<MeStats> fetchStats() async {
    final data = await _client.get('/me/stats');
    return MeStats.fromJson(data as Map<String, dynamic>);
  }

  @override
  Future<AuthUser> uploadAvatar(String filePath) async {
    final data = await _client.uploadImage('/profile/avatar', filePath);
    return AuthUser.fromJson(data as Map<String, dynamic>);
  }

  @override
  Future<AuthUser> removeAvatar() async {
    final data = await _client.delete('/profile/avatar');
    return AuthUser.fromJson(data as Map<String, dynamic>);
  }

  @override
  Future<bool> getProfilePublic() async {
    final data = await _client.get('/account/privacy');
    return (data as Map<String, dynamic>)['profilePublic'] == true;
  }

  @override
  Future<bool> setProfilePublic(bool value) async {
    final data = await _client.patch(
      '/account/privacy',
      body: {'profilePublic': value},
    );
    return (data as Map<String, dynamic>)['profilePublic'] == true;
  }

  @override
  Future<void> deleteAccount() async {
    await _client.post('/account/delete', body: {'confirm': true});
  }
}

/// Что сервер сказал об отправке кода (POST /auth/phone/request).
class SmsCodeInfo {
  /// Боевой вход: код реально отправлен. Иначе режим разработки — код 1234.
  final bool smsEnabled;

  /// Канал доставки: звонок (flashcall), SMS…
  final String channelType;

  const SmsCodeInfo({this.smsEnabled = false, this.channelType = ''});

  /// Код придёт звонком: это последние 4 цифры номера.
  bool get isCall => channelType.toLowerCase().contains('call');

  factory SmsCodeInfo.fromJson(Map data) {
    final channel = data['channel'];
    return SmsCodeInfo(
      smsEnabled: data['smsEnabled'] == true,
      channelType: channel is Map ? (channel['type'] ?? '').toString() : '',
    );
  }
}
