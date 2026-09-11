import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../data/repositories/auth_repository.dart';
import '../models/auth_user.dart';
import '../models/me_stats.dart';

// Re-export, чтобы существующие `import '.../auth_provider.dart'` по-прежнему
// видели AuthUser/SavedAddress/LoginProvider.
export '../models/auth_user.dart';
export '../models/me_stats.dart';

class AuthProvider extends ChangeNotifier {
  final SharedPreferences _prefs;
  final AuthRepository _repo;
  final VoidCallback? onSessionEnd; // очистка JWT при выходе (для API)
  static const _key = 'auth_user';

  AuthUser? _user;
  bool _isLoading = false;
  bool _sessionExpired = false;

  /// true один раз после того, как сервер отверг токен (401). UI показывает
  /// «Сессия истекла — войдите снова» и вызывает [ackSessionExpired].
  bool get sessionExpired => _sessionExpired;
  void ackSessionExpired() => _sessionExpired = false;

  AuthProvider(this._prefs, this._repo, {this.onSessionEnd}) {
    _load();
    // Если есть кэш юзера (и валидный JWT) — обновить профиль с backend.
    if (_user != null) refreshFromServer();
  }

  /// Синк с backend. Аватар — единый серверный (источник правды, в т.ч. null при
  /// удалении в другом приложении); локальные адреса сохраняем, если бек не отдал.
  AuthUser _mergeKeepingLocal(AuthUser fresh) => AuthUser(
    id: fresh.id,
    name: fresh.name,
    email: fresh.email,
    phone: fresh.phone,
    city: fresh.city,
    provider: fresh.provider,
    addresses: fresh.addresses.isNotEmpty ? fresh.addresses : _user!.addresses,
    avatarPath: fresh.avatarPath,
  );

  /// Обновить профиль из backend (GET /auth/me). Тихо игнорирует офлайн/mock.
  Future<void> refreshFromServer() async {
    if (_user == null) return;
    try {
      _user = _mergeKeepingLocal(await _repo.fetchMe());
      _save();
      notifyListeners();
    } catch (_) {
      // backend недоступен или mock — оставляем локальный кэш
    }
  }

  /// Личная статистика с общего бэка (GET /me/stats).
  Future<MeStats> fetchStats() => _repo.fetchStats();

  AuthUser? get user => _user;
  bool get isLoggedIn => _user != null;
  bool get isLoading => _isLoading;

  void _load() {
    final raw = _prefs.getString(_key);
    if (raw == null) return;
    try {
      _user = AuthUser.fromJson(jsonDecode(raw) as Map<String, dynamic>);
    } catch (_) {}
  }

  void _save() {
    if (_user == null) {
      _prefs.remove(_key);
    } else {
      _prefs.setString(_key, jsonEncode(_user!.toJson()));
    }
  }

  Future<String?> login(String email, String password) async {
    if (email.trim().isEmpty || password.isEmpty) return 'Заполните все поля';
    if (!email.contains('@')) return 'Некорректный email';
    if (password.length < 6) return 'Минимум 6 символов';
    _setLoading(true);
    _user = await _repo.login(email, password);
    _save();
    _setLoading(false);
    return null;
  }

  /// Вход/регистрация по телефону (единственный способ входа). [name] —
  /// имя при регистрации: verify создаёт аккаунт при первом входе.
  Future<String?> loginByPhone(
    String phone,
    String code, {
    String? name,
  }) async {
    final digits = phone.replaceAll(RegExp(r'\D'), '');
    if (digits.length < 10) return 'Введите корректный номер';
    if (code.trim().length != 4) return 'Введите код из 4 цифр';
    _setLoading(true);
    try {
      _user = await _repo.loginByPhone(phone, code, name: name);
      _save();
      return null;
    } catch (e) {
      return 'Не удалось войти по телефону';
    } finally {
      _setLoading(false);
    }
  }

  /// Вход по ТЕЛЕФОНУ + ПАРОЛЮ (основной путь, #8).
  Future<String?> loginByPassword(String phone, String password) async {
    final digits = phone.replaceAll(RegExp(r'\D'), '');
    if (digits.length < 10) return 'Введите корректный номер';
    if (password.isEmpty) return 'Введите пароль';
    _setLoading(true);
    try {
      _user = await _repo.loginByPassword(phone, password);
      _save();
      return null;
    } catch (e) {
      return 'Неверный телефон или пароль';
    } finally {
      _setLoading(false);
    }
  }

  /// Отправить SMS-код на телефон (для регистрации/сброса пароля).
  /// Что сервер сказал о последней отправке кода — от этого зависит подсказка
  /// под полем: звонок, SMS или режим разработки с кодом 1234.
  SmsCodeInfo _codeInfo = const SmsCodeInfo();
  SmsCodeInfo get codeInfo => _codeInfo;

  Future<String?> requestSmsCode(String phone) async {
    final digits = phone.replaceAll(RegExp(r'\D'), '');
    if (digits.length < 10) return 'Введите корректный номер';
    try {
      _codeInfo = await _repo.requestSmsCode(phone);
      notifyListeners();
      return null;
    } catch (e) {
      return 'Не удалось отправить код';
    }
  }

  /// Регистрация по телефону: код подтверждает телефон, аккаунт с паролем.
  Future<String?> registerByPhone(String phone, String code, String password, String name) async {
    if (name.trim().isEmpty) return 'Введите имя';
    if (code.trim().length != 4) return 'Введите код из 4 цифр';
    if (password.length < 4) return 'Пароль — минимум 4 символа';
    _setLoading(true);
    try {
      _user = await _repo.registerByPhone(phone, code, password, name.trim());
      _save();
      return null;
    } catch (e) {
      return 'Не удалось зарегистрироваться (проверьте код)';
    } finally {
      _setLoading(false);
    }
  }

  /// Сброс пароля по SMS-коду.
  Future<String?> resetPasswordByPhone(String phone, String code, String password) async {
    if (code.trim().length != 4) return 'Введите код из 4 цифр';
    if (password.length < 4) return 'Пароль — минимум 4 символа';
    _setLoading(true);
    try {
      _user = await _repo.resetPasswordByPhone(phone, code, password);
      _save();
      return null;
    } catch (e) {
      return 'Не удалось сбросить пароль (проверьте код)';
    } finally {
      _setLoading(false);
    }
  }

  Future<String?> register(
    String name,
    String email,
    String password,
    String confirm,
  ) async {
    if (name.trim().isEmpty || email.trim().isEmpty || password.isEmpty) {
      return 'Заполните все поля';
    }
    if (!email.contains('@')) return 'Некорректный email';
    if (password.length < 6) return 'Минимум 6 символов';
    if (password != confirm) return 'Пароли не совпадают';
    _setLoading(true);
    _user = await _repo.register(name, email, password);
    _save();
    _setLoading(false);
    return null;
  }

  Future<String?> sendPasswordReset(String email) async {
    if (email.trim().isEmpty) return 'Введите email';
    if (!email.contains('@')) return 'Некорректный email';
    _setLoading(true);
    await _repo.sendPasswordReset(email);
    _setLoading(false);
    return null;
  }

  Future<String?> resetPassword(String newPass, String confirm) async {
    if (newPass.isEmpty || confirm.isEmpty) return 'Заполните все поля';
    if (newPass.length < 6) return 'Минимум 6 символов';
    if (newPass != confirm) return 'Пароли не совпадают';
    _setLoading(true);
    await _repo.resetPassword(newPass);
    _setLoading(false);
    return null;
  }

  Future<String?> updateProfile({
    required String name,
    String? phone,
    String? city,
    String? email,
  }) async {
    if (_user == null) return 'Не авторизован';
    if (name.trim().isEmpty) return 'Введите имя';
    if (email != null && email.trim().isNotEmpty && !email.contains('@')) {
      return 'Введите корректный email';
    }
    _setLoading(true);
    try {
      _user = _mergeKeepingLocal(
        await _repo.updateProfile(
          _user!,
          name: name,
          phone: phone,
          city: city,
          email: email,
        ),
      );
      _save();
      return null;
    } catch (_) {
      return 'Не удалось сохранить профиль';
    } finally {
      _setLoading(false);
    }
  }

  /// Загрузить серверный аватар (единый для экосистемы). null — успех.
  Future<String?> uploadAvatar(String filePath) async {
    if (_user == null) return 'Не авторизован';
    _setLoading(true);
    try {
      _user = _withServerAvatar(await _repo.uploadAvatar(filePath));
      _save();
      return null;
    } catch (_) {
      return 'Не удалось загрузить фото';
    } finally {
      _setLoading(false);
    }
  }

  /// Снять серверный аватар (вернуться к инициалам).
  Future<String?> removeAvatar() async {
    if (_user == null) return 'Не авторизован';
    _setLoading(true);
    try {
      _user = _withServerAvatar(await _repo.removeAvatar());
      _save();
      return null;
    } catch (_) {
      return 'Не удалось убрать фото';
    } finally {
      _setLoading(false);
    }
  }

  /// Свежий юзер с сервера, но локальные адреса сохраняем; аватар — серверный
  /// (включая null при удалении — в отличие от _mergeKeepingLocal).
  AuthUser _withServerAvatar(AuthUser fresh) => AuthUser(
    id: fresh.id,
    name: fresh.name,
    email: fresh.email,
    phone: fresh.phone,
    city: fresh.city,
    provider: fresh.provider,
    addresses: fresh.addresses.isNotEmpty ? fresh.addresses : _user!.addresses,
    avatarPath: fresh.avatarPath,
  );

  AuthUser _withAddresses(List<SavedAddress> list) => AuthUser(
    id: _user!.id,
    name: _user!.name,
    email: _user!.email,
    phone: _user!.phone,
    provider: _user!.provider,
    city: _user!.city,
    addresses: list,
    avatarPath: _user!.avatarPath,
  );

  /// Сохранить адреса на общий бэкенд (единые в экосистеме). Локально уже
  /// применены — здесь только синк; при офлайне молча остаёмся на кэше.
  Future<void> _persistAddresses(List<SavedAddress> list) async {
    if (_user == null) return;
    try {
      final fresh = await _repo.updateProfile(_user!, addresses: list);
      // Берём адреса с сервера, аватар оставляем серверным (единый).
      _user = AuthUser(
        id: fresh.id,
        name: fresh.name,
        email: fresh.email,
        phone: fresh.phone,
        provider: fresh.provider,
        city: fresh.city,
        addresses: fresh.addresses,
        avatarPath: fresh.avatarPath,
      );
      _save();
      notifyListeners();
    } catch (_) {
      // офлайн/ошибка — адрес уже в локальном кэше, долетит позже
    }
  }

  Future<void> addAddress(SavedAddress address) async {
    if (_user == null) return;
    final list = List<SavedAddress>.from(_user!.addresses);
    final exists = list.any((a) => a.displayLine == address.displayLine);
    if (!exists) list.insert(0, address);
    _user = _withAddresses(list);
    _save();
    notifyListeners();
    await _persistAddresses(list);
  }

  Future<void> removeAddress(int index) async {
    if (_user == null) return;
    final list = List<SavedAddress>.from(_user!.addresses)..removeAt(index);
    _user = _withAddresses(list);
    _save();
    notifyListeners();
    await _persistAddresses(list);
  }

  Future<String?> changePassword(
    String oldPass,
    String newPass,
    String confirm,
  ) async {
    if (oldPass.isEmpty || newPass.isEmpty || confirm.isEmpty) {
      return 'Заполните все поля';
    }
    if (oldPass.length < 6) return 'Неверный текущий пароль';
    if (newPass.length < 6) return 'Минимум 6 символов';
    if (newPass != confirm) return 'Пароли не совпадают';
    _setLoading(true);
    await _repo.changePassword(oldPass, newPass);
    _setLoading(false);
    return null;
  }

  void logout() {
    _user = null;
    _save();
    onSessionEnd?.call();
    notifyListeners();
  }

  /// Сервер отверг токен (401) — сессия недействительна/истекла. Чистим её и
  /// поднимаем флаг, чтобы UI попросил войти заново. Идемпотентно: параллельные
  /// 401 (несколько запросов сразу) не зациклят выход. Это и есть «самолечение»:
  /// протухший токен больше не залипает — при первом 401 мы выходим из аккаунта.
  void handleUnauthorized() {
    if (_user == null) return; // уже вышли
    _sessionExpired = true;
    logout();
  }

  /// Видимость профиля (общая настройка приватности аккаунта).
  Future<bool> getProfilePublic() async {
    try {
      return await _repo.getProfilePublic();
    } catch (_) {
      return false;
    }
  }

  Future<bool> setProfilePublic(bool value) async {
    try {
      return await _repo.setProfilePublic(value);
    } catch (_) {
      return value;
    }
  }

  /// Необратимо удалить аккаунт; при успехе разлогинивает. true — успех.
  Future<bool> deleteAccount() async {
    if (_user == null) return false;
    try {
      await _repo.deleteAccount();
      logout();
      return true;
    } catch (_) {
      return false;
    }
  }

  void _setLoading(bool value) {
    _isLoading = value;
    notifyListeners();
  }
}
