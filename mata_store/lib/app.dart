import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'providers/auth_provider.dart';
import 'router/app_router.dart';
import 'screens/onboarding/onboarding_screen.dart';
import 'screens/splash/splash_screen.dart';
import 'theme/app_theme.dart';
import 'theme/text_scale.dart';

class SportStoreApp extends StatefulWidget {
  final SharedPreferences prefs;
  const SportStoreApp({super.key, required this.prefs});

  @override
  State<SportStoreApp> createState() => _SportStoreAppState();
}

class _SportStoreAppState extends State<SportStoreApp> {
  static const _onboardingKey = 'onboarding_seen';

  /// Для глобального SnackBar «Сессия истекла» из любого экрана.
  final _messengerKey = GlobalKey<ScaffoldMessengerState>();

  bool _splashDone = false;
  late bool _onboardingDone;

  @override
  void initState() {
    super.initState();
    _onboardingDone = widget.prefs.getBool(_onboardingKey) ?? false;
  }

  void _finishOnboarding() {
    widget.prefs.setBool(_onboardingKey, true);
    setState(() => _onboardingDone = true);
  }

  @override
  Widget build(BuildContext context) {
    if (!_splashDone) {
      return MaterialApp(
        debugShowCheckedModeBanner: false,
        builder: clampTextScale,
        home: SplashScreen(
          onComplete: () => setState(() => _splashDone = true),
        ),
      );
    }

    if (!_onboardingDone) {
      return MaterialApp(
        debugShowCheckedModeBanner: false,
        builder: clampTextScale,
        theme: AppTheme.light,
        home: OnboardingScreen(onComplete: _finishOnboarding),
      );
    }

    // Сессия истекла (сервер отверг токен 401) — авто-выход уже произошёл,
    // здесь только показываем понятное сообщение поверх любого экрана.
    final auth = context.watch<AuthProvider>();
    if (auth.sessionExpired) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (!mounted) return;
        auth.ackSessionExpired();
        _messengerKey.currentState
          ?..hideCurrentSnackBar()
          ..showSnackBar(
            const SnackBar(
              content: Text('Сессия истекла — войдите снова'),
              behavior: SnackBarBehavior.floating,
            ),
          );
      });
    }

    return MaterialApp.router(
      title: 'МАТА Store',
      theme: AppTheme.light,
      scaffoldMessengerKey: _messengerKey,
      routerConfig: appRouter,
      debugShowCheckedModeBanner: false,
        builder: clampTextScale,
    );
  }
}
