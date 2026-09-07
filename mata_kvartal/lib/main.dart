import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:sentry_flutter/sentry_flutter.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'core/constants/app_strings.dart';
import 'core/router/app_router.dart';
import 'core/theme/app_colors.dart';
import 'core/theme/app_theme.dart';
import 'core/theme/theme_controller.dart';
import 'features/races/data/race_reminders.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await _clearMapAndRunDataOnStartup();
  await RaceReminders.init(); // локальные напоминания о «Моих стартах»
  await _runWithSentry(const ProviderScope(child: KvartalApp()));
}

/// Видимость ошибок (D-32): при заданном SENTRY_DSN (--dart-define) крэши и
/// необработанные ошибки летят в GlitchTip. Без DSN — обычный запуск (no-op).
/// PII не шлём (152-ФЗ). DSN приложения — из своего проекта GlitchTip.
Future<void> _runWithSentry(Widget app) async {
  const dsn = String.fromEnvironment('SENTRY_DSN');
  if (dsn.isEmpty) {
    runApp(app);
    return;
  }
  await SentryFlutter.init(
    (o) {
      o.dsn = dsn;
      o.environment = const String.fromEnvironment(
        'SENTRY_ENVIRONMENT',
        defaultValue: 'production',
      );
      const rel = String.fromEnvironment('SENTRY_RELEASE');
      if (rel.isNotEmpty) o.release = rel;
      o.tracesSampleRate = 0.0;
      o.sendDefaultPii = false;
    },
    appRunner: () => runApp(app),
  );
}

Future<void> _clearMapAndRunDataOnStartup() async {
  final prefs = await SharedPreferences.getInstance();
  const cleanupKey = 'kvartal.map_cleanup_2026_06_13_v3';
  if (prefs.getBool(cleanupKey) == true) return;

  const keys = [
    'kvartal.captured_zone_ids.v1',
    'kvartal.captured_areas.v1',
    'kvartal.active_run.v1',
    'kvartal.completed_runs.v1',
    'kvartal.map_cleanup_2026_06_11.v1',
  ];

  for (final key in keys) {
    await prefs.remove(key);
  }
  await prefs.setBool(cleanupKey, true);
}


class KvartalApp extends ConsumerStatefulWidget {
  const KvartalApp({super.key});

  @override
  ConsumerState<KvartalApp> createState() => _KvartalAppState();
}

class _KvartalAppState extends ConsumerState<KvartalApp>
    with WidgetsBindingObserver {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangePlatformBrightness() {
    // Режим «Как в системе»: тема телефона поменялась — перерисоваться
    // полностью (const-виджеты не перечитают геттеры палитры сами).
    setState(() {});
    WidgetsBinding.instance.reassembleApplication();
  }

  @override
  Widget build(BuildContext context) {
    final mode = ref.watch(interiorProvider);
    final platform =
        WidgetsBinding.instance.platformDispatcher.platformBrightness;
    final graphite = resolveGraphite(mode, platform);
    // Флаг читают геттеры AppColors во всех build-методах, поэтому выставляем
    // его ДО сборки и пересобираем всё дерево по ключу. GoRouter один и тот же —
    // текущий экран и история навигации сохраняются.
    AppColors.isGraphite = graphite;
    return MaterialApp.router(
      key: ValueKey('interior-$graphite'),
      title: AppStrings.appName,
      debugShowCheckedModeBanner: false,
      theme: AppTheme.current(),
      routerConfig: ref.watch(routerProvider),
    );
  }
}
