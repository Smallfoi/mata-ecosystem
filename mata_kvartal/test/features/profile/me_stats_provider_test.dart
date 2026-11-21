import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:kvartal_app/features/auth/data/auth_provider.dart';
import 'package:kvartal_app/features/profile/data/me_stats_provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Холодный запуск (телефон владельца, 21.11.2026): карта строится раньше, чем
/// восстановлена сессия. Статистика без токена падает «Не авторизован» — и
/// обязана перезапроситься, когда токен появится. Раньше она читала токен один
/// раз и оставалась в ошибке: чип «Дивизион» висел в «загрузка…» до перезапуска.
class _FakeAuth extends AuthNotifier {
  void signIn() => state = AuthState(
    status: AuthStatus.authenticated,
    token: 't',
    user: const AuthUser(id: 'u1', name: 'Бегун', email: ''),
  );
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUp(() => SharedPreferences.setMockInitialValues({}));

  test('без токена — ошибка, с появлением токена — новый запрос', () async {
    final auth = _FakeAuth();
    final container = ProviderContainer(
      overrides: [authProvider.overrideWith((ref) => auth)],
    );
    addTearDown(container.dispose);

    final states = <AsyncValue<MeStats>>[];
    container.listen(meStatsProvider, (_, next) => states.add(next),
        fireImmediately: true);
    await pumpEventQueue();
    expect(container.read(meStatsProvider).hasError, isTrue);

    states.clear();
    auth.signIn();
    await pumpEventQueue(times: 1);
    expect(states.any((s) => s.isLoading), isTrue,
        reason: 'после входа статистика должна перезапроситься');
  });
}
