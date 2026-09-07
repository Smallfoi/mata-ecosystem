import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import '../../features/auth/data/auth_provider.dart';
import '../../features/auth/presentation/screens/phone_screen.dart';
import '../../features/auth/presentation/screens/welcome_screen.dart';
import '../../features/auth/presentation/screens/otp_screen.dart';
import '../../features/map/presentation/screens/map_screen.dart';
import '../../features/run/data/completed_runs_provider.dart';
import '../../features/run/presentation/screens/run_screen.dart';
import '../../features/run/presentation/screens/run_result_screen.dart';
import '../../features/run/presentation/screens/run_passport_screen.dart';
import '../../features/run/presentation/screens/runs_journal_screen.dart';
import '../../features/permissions/presentation/location_setup_sheet.dart';
import '../../features/league/presentation/screens/focus_screen.dart';
import '../../features/league/presentation/screens/league_screen.dart';
import '../../features/trails/data/trails_provider.dart';
import '../../features/trails/presentation/screens/trails_screen.dart';
import '../../features/workouts/presentation/screens/watch_sync_screen.dart';
import '../../features/league/presentation/screens/division_hub_screen.dart';
import '../../features/races/data/races_provider.dart';
import '../../features/races/presentation/screens/races_screen.dart';
import '../../features/races/presentation/screens/race_detail_screen.dart';
import '../../features/club/presentation/screens/club_screen.dart';
import '../../features/club/presentation/screens/club_scan_screen.dart';
import '../../features/profile/presentation/screens/profile_screen.dart';
import '../../features/profile/presentation/screens/theme_screen.dart';
import '../../features/medals/presentation/hall_screen.dart';
import '../../features/profile/presentation/screens/trophy_screen.dart';
import '../../features/notifications/presentation/screens/notifications_screen.dart';
import '../../features/profile/presentation/screens/legal_documents_screen.dart';
import '../../features/profile/presentation/screens/privacy_screen.dart';
import '../../features/profile/presentation/screens/stats_screen.dart';
import '../../features/shoes/presentation/screens/shoes_screen.dart';
import '../../features/tools/presentation/screens/tools_screen.dart';
import '../../features/tools/presentation/screens/pace_converter_screen.dart';
import '../../features/tools/presentation/screens/hr_zones_screen.dart';
import '../../features/tools/presentation/screens/shoe_size_screen.dart';
import '../../features/tools/presentation/screens/cadence_metronome_screen.dart';
import '../../features/tools/presentation/screens/interval_timer_screen.dart';
import '../../features/profile/presentation/screens/about_app_screen.dart';
import '../../features/splash/presentation/splash_screen.dart';
import '../../shared/widgets/main_scaffold.dart';

class _RouterNotifier extends ChangeNotifier {
  _RouterNotifier(this._ref) {
    // redirect зависит только от auth.status (вход/выход). Рефрешим GoRouter
    // лишь при смене статуса — иначе сохранение профиля/аватара/isLoading
    // дёргает весь стек роутера, и экран редактирования мелькает («перекрытие»
    // редактора, проблеск предыдущего экрана при «Сохранить»).
    _ref.listen<AuthState>(authProvider, (prev, next) {
      if (prev?.status != next.status) notifyListeners();
    });
  }

  final Ref _ref;

  String? redirect(BuildContext context, GoRouterState state) {
    final auth = _ref.read(authProvider);
    final isAuth = auth.status == AuthStatus.authenticated;
    final loc = state.matchedLocation;

    if (loc == '/splash') return null; // сплэш сам управляет навигацией
    if (!isAuth && !loc.startsWith('/auth')) return '/auth/phone';
    if (isAuth && loc.startsWith('/auth')) return null;
    if (loc == '/auth/otp' && auth.status != AuthStatus.codeSent) {
      return '/auth/phone';
    }
    return null;
  }
}

// У каждой вкладки — свой навигатор (ветка). Ключи нужны, чтобы при уходе с
// вкладки закрыть открытый на ней модальный лист (погода, выбор кроссовок) —
// иначе он висит поверх новой вкладки (см. [[feedback-no-repeat-fixed-bugs]]).
final tabNavigatorKeys = <GlobalKey<NavigatorState>>[
  GlobalKey<NavigatorState>(debugLabel: 'tab-map'),
  GlobalKey<NavigatorState>(debugLabel: 'tab-run'),
  GlobalKey<NavigatorState>(debugLabel: 'tab-leaderboard'),
  GlobalKey<NavigatorState>(debugLabel: 'tab-club'),
  GlobalKey<NavigatorState>(debugLabel: 'tab-profile'),
];

final routerProvider = Provider<GoRouter>((ref) {
  final notifier = _RouterNotifier(ref);
  return GoRouter(
    initialLocation: '/splash',
    refreshListenable: notifier,
    redirect: notifier.redirect,
    routes: [
      GoRoute(
        path: '/splash',
        pageBuilder: (_, __) => const NoTransitionPage(child: SplashScreen()),
      ),
      GoRoute(
        path: '/auth/welcome',
        pageBuilder: (_, __) => const NoTransitionPage(child: WelcomeScreen()),
      ),
      GoRoute(
        path: '/auth/phone',
        pageBuilder: (_, __) => const NoTransitionPage(child: PhoneScreen()),
      ),
      GoRoute(
        path: '/auth/otp',
        pageBuilder: (_, __) => const NoTransitionPage(child: OtpScreen()),
      ),
      // Гейт согласия после входа (вне шелла): показывается, если есть
      // непринятые обязательные документы. redirect не трогает /auth/*.
      GoRoute(
        path: '/auth/consent',
        pageBuilder: (_, __) =>
            const NoTransitionPage(child: ConsentGateScreen()),
      ),
      // Скан QR приглашения — полноэкранный (вне шелла), как камера в Тинькофф.
      // «Зачем ты бегаешь» — поверх вкладок: это разговор, а не раздел приложения.
      GoRoute(
        path: '/focus',
        builder: (_, __) => const FocusScreen(),
      ),
      // Церемония итогов пробежки (Ф1) — на весь экран, без таб-бара.
      GoRoute(
        path: '/run/result',
        builder: (_, state) =>
            RunResultScreen(result: state.extra as RunResult),
      ),
      // «Паспорт пробежки» + журнал (дизайн 05.09.2026): детальный экран
      // с маршрутом-героем и шарингом в любой момент.
      GoRoute(
        path: '/runs',
        builder: (_, __) => const RunsJournalScreen(),
      ),
      GoRoute(
        path: '/runs/passport',
        builder: (_, state) =>
            RunPassportScreen(run: state.extra as CompletedRun),
      ),
      GoRoute(
        path: '/club/scan',
        builder: (_, __) => const ClubScanScreen(),
      ),
      // Вкладки — ветки с собственными навигаторами: экран вкладки НЕ
      // пересоздаётся при переключении, а сохраняется (индексированный стек).
      // Из-за пересоздания и возникал баг «после карты соседний экран пустой»:
      // тяжёлая карта сносилась, а новый экран строился в том же кадре.
      // Побочно чинится и «вкладка забывает, куда ты в ней зашёл».
      StatefulShellRoute.indexedStack(
        pageBuilder: (context, state, navigationShell) {
          final scaffold = MainScaffold(navigationShell: navigationShell);
          final reduceMotion =
              MediaQuery.maybeOf(context)?.disableAnimations ?? false;
          // Вход со сплэша (?from=splash) — приложение поднимается снизу поверх
          // графита, пока знак сплэша улетает в чип шапки (финал дизайн-проекта
          // 24d1c230). Любой другой вход/переключение вкладок — без анимации.
          if (state.uri.queryParameters['from'] == 'splash' && !reduceMotion) {
            return CustomTransitionPage<void>(
              key: state.pageKey,
              transitionDuration: const Duration(milliseconds: 520),
              child: scaffold,
              transitionsBuilder: (_, animation, __, page) => SlideTransition(
                position: animation.drive(
                  Tween(begin: const Offset(0, 1), end: Offset.zero)
                      .chain(CurveTween(curve: const Cubic(0.32, 0.01, 0.18, 1))),
                ),
                child: page,
              ),
            );
          }
          return NoTransitionPage<void>(key: state.pageKey, child: scaffold);
        },
        branches: [
          // 0 — Карта
          StatefulShellBranch(
            navigatorKey: tabNavigatorKeys[0],
            routes: [
              GoRoute(path: '/map', builder: (_, __) => const MapScreen()),
            ],
          ),
          // 1 — Бег
          StatefulShellBranch(
            navigatorKey: tabNavigatorKeys[1],
            routes: [
              GoRoute(path: '/run', builder: (_, __) => const RunScreen()),
              // Настройка доступа к геолокации — внутри вкладки, чтобы таб-бар
              // продолжал переключать экраны (а не модальный лист, он залипал).
              GoRoute(
                path: '/run/location-access',
                builder: (_, __) => const LocationSetupScreen(),
              ),
            ],
          ),
          // 2 — Рейтинг (внутри него живёт «Лига»: то же место в голове —
          //     «как я выгляжу на фоне других», но зачётов несколько)
          StatefulShellBranch(
            navigatorKey: tabNavigatorKeys[2],
            routes: [
              GoRoute(
                path: '/leaderboard',
                builder: (_, __) => const DivisionHubScreen(),
              ),
              GoRoute(
                path: '/league',
                builder: (_, __) => const LeagueScreen(),
              ),
              GoRoute(
                path: '/trails',
                builder: (_, __) => const TrailsScreen(),
              ),
              // Тропу передаём объектом: список уже загружен, второй запрос
              // ради названия и длины не нужен.
              GoRoute(
                path: '/trails/detail',
                builder: (_, state) =>
                    TrailDetailScreen(trail: state.extra as Trail),
              ),
            ],
          ),
          // 3 — Клуб (внутри него живут «Старты»)
          StatefulShellBranch(
            navigatorKey: tabNavigatorKeys[3],
            routes: [
              GoRoute(path: '/club', builder: (_, __) => const ClubScreen()),
              GoRoute(path: '/races', builder: (_, __) => const RacesScreen()),
              // Детали забега — данные передаём через extra.
              GoRoute(
                path: '/races/detail',
                builder: (_, state) =>
                    RaceDetailScreen(race: state.extra as RaceEvent),
              ),
            ],
          ),
          // 4 — Профиль (внутри него живёт «Сервис»)
          StatefulShellBranch(
            navigatorKey: tabNavigatorKeys[4],
            routes: [
              GoRoute(
                path: '/profile',
                builder: (_, __) => const ProfileScreen(),
              ),
              GoRoute(
                path: '/profile/points',
                builder: (_, __) => const PointsHistoryScreen(),
              ),
              GoRoute(
                path: '/profile/stats',
                builder: (_, __) => const StatsScreen(),
              ),
              GoRoute(
                path: '/profile/shoes',
                builder: (_, __) => const ShoesScreen(),
              ),
              GoRoute(
                path: '/profile/edit',
                builder: (_, __) => const EditProfileScreen(),
              ),
              GoRoute(
                path: '/profile/settings',
                builder: (_, __) => const SettingsScreen(),
              ),
              GoRoute(
                path: '/profile/about',
                builder: (_, __) => const AboutAppScreen(),
              ),
              GoRoute(
                path: '/profile/notifications',
                builder: (_, __) => const NotificationsScreen(),
              ),
              GoRoute(
                path: '/profile/privacy',
                builder: (_, __) => const PrivacyScreen(),
              ),
              // Зал славы (пьедестал, утверждён 02.09.2026); полный каталог
              // 44 штампов — вложенным маршрутом за кнопкой «Все медали».
              GoRoute(
                path: '/profile/trophies',
                builder: (_, __) => const TrophyHallScreen(),
              ),
              GoRoute(
                path: '/profile/trophies/all',
                builder: (_, __) => const MedalCatalogScreen(),
              ),
              GoRoute(
                path: '/profile/theme',
                builder: (_, __) => const ThemeScreen(),
              ),
              GoRoute(
                path: '/profile/watch',
                builder: (_, __) => const WatchSyncScreen(),
              ),
              GoRoute(
                path: '/profile/legal',
                builder: (_, __) => const LegalDocumentsScreen(),
              ),
              // Инструменты бегуна — хаб + под-экраны /tools/*.
              GoRoute(path: '/tools', builder: (_, __) => const ToolsScreen()),
              GoRoute(
                path: '/tools/pace',
                builder: (_, __) => const PaceConverterScreen(),
              ),
              GoRoute(
                path: '/tools/hr-zones',
                builder: (_, __) => const HrZonesScreen(),
              ),
              GoRoute(
                path: '/tools/shoe-size',
                builder: (_, __) => const ShoeSizeScreen(),
              ),
              GoRoute(
                path: '/tools/metronome',
                builder: (_, __) => const CadenceMetronomeScreen(),
              ),
              GoRoute(
                path: '/tools/interval',
                builder: (_, __) => const IntervalTimerScreen(),
              ),
            ],
          ),
        ],
      ),
    ],
  );
});
