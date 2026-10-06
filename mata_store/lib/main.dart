import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:provider/provider.dart';
import 'package:sentry_flutter/sentry_flutter.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'app.dart';
import 'data/api/api_client.dart';
import 'data/api/api_config.dart';
import 'data/repositories/auth_repository.dart';
import 'data/repositories/loyalty_repository.dart';
import 'data/repositories/order_repository.dart';
import 'data/shipping_rates.dart';
import 'data/repositories/product_repository.dart';
import 'providers/auth_provider.dart';
import 'providers/cart_provider.dart';
import 'providers/catalog_provider.dart';
import 'providers/loyalty_provider.dart';
import 'providers/notifications_provider.dart';
import 'providers/order_provider.dart';
import 'providers/remote_content_provider.dart';
import 'providers/tab_notifier.dart';
import 'providers/wishlist_provider.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  // Шрифты (Inter/Oswald) встроены в assets/fonts — берём их локально, без обращения
  // к fonts.gstatic.com (офлайн + приватность §2: не шлём IP в Google). Файлы байт-в-байт
  // те же, что google_fonts скачал бы по сети, поэтому вид не меняется (D-01).
  GoogleFonts.config.allowRuntimeFetching = false;
  final prefs = await SharedPreferences.getInstance();

  // Per-service источник данных (walking skeleton): часть сервисов на реальном
  // backend, часть на mock — см. ApiConfig. Общий ApiClient хранит JWT.
  final ApiClient? api = ApiConfig.anyApi ? ApiClient() : null;
  if (api != null) {
    // JWT — в защищённом хранилище (Android Keystore / iOS Keychain), не в
    // открытых SharedPreferences (S-08). Сохраняем при смене токена, восстанавливаем
    // при старте; одноразовая миграция со старого открытого ключа prefs['jwt'].
    const secure = FlutterSecureStorage(
      aOptions: AndroidOptions(encryptedSharedPreferences: true),
    );
    api.onTokenChanged = (t) {
      if (t == null) {
        secure.delete(key: 'jwt');
      } else {
        secure.write(key: 'jwt', value: t);
      }
    };
    var token = await secure.read(key: 'jwt');
    if (token == null) {
      final legacy = prefs.getString('jwt');
      if (legacy != null && legacy.isNotEmpty) {
        await secure.write(key: 'jwt', value: legacy);
        await prefs.remove('jwt');
        token = legacy;
      }
    }
    api.authToken = token;
  }

  final ProductRepository productRepo = ApiConfig.useApiCatalog
      ? ApiProductRepository(api!)
      : MockProductRepository();
  final AuthRepository authRepo =
      ApiConfig.useApiAuth ? ApiAuthRepository(api!) : MockAuthRepository();
  final OrderRepository orderRepo =
      ApiConfig.useApiOrder ? ApiOrderRepository(api!) : MockOrderRepository();
  // Цены доставки с сервера (D-110) — фоном, оформление их дождётся само.
  if (ApiConfig.useApiOrder) ShippingRates.load(api!);
  final LoyaltyRepository loyaltyRepo = ApiConfig.useApiLoyalty
      ? ApiLoyaltyRepository(api!)
      : MockLoyaltyRepository();

  await _runWithSentry(
    MultiProvider(
      providers: [
        // Общий HTTP-клиент экосистемы (хранит JWT) — чтобы экраны могли
        // читать backend напрямую (напр. правовые документы /legal/documents).
        Provider<ApiClient?>.value(value: api),
        ChangeNotifierProvider(
          create: (_) {
            final ap = AuthProvider(prefs, authRepo,
                onSessionEnd: () => api?.authToken = null);
            // Сервер отверг токен (401) → авто-выход + «Сессия истекла».
            // Лечит «залипший» протухший токен (см. ApiClient.onUnauthorized).
            api?.onUnauthorized = ap.handleUnauthorized;
            return ap;
          },
        ),
        ChangeNotifierProvider(create: (_) => CartProvider(prefs)),
        ChangeNotifierProvider(create: (_) => WishlistProvider(prefs)),
        // Редактируемые тексты приложения (мини-CMS, ключи app.*): фолбэк — текущий
        // текст; правятся в «Конструкторе», подтягиваются в проде.
        ChangeNotifierProvider(create: (_) => RemoteContentProvider(api)),
        ChangeNotifierProxyProvider<AuthProvider, NotificationsProvider>(
          create: (_) => NotificationsProvider(prefs,
              api: api, serverBacked: ApiConfig.useApiNotifications && api != null),
          update: (_, auth, notif) =>
              notif!..syncAuth(auth.isLoggedIn, userId: auth.user?.id),
        ),
        ChangeNotifierProxyProvider<AuthProvider, LoyaltyProvider>(
          create: (_) => LoyaltyProvider(prefs, loyaltyRepo,
              serverBacked: ApiConfig.useApiLoyalty),
          update: (_, auth, loyalty) {
            loyalty!.syncAuth(auth.isLoggedIn, userId: auth.user?.id);
            return loyalty;
          },
        ),
        ChangeNotifierProvider(create: (_) => CatalogProvider(productRepo)),
        ChangeNotifierProxyProvider2<AuthProvider, NotificationsProvider,
            OrderProvider>(
          create: (_) => OrderProvider(prefs, orderRepo,
              serverBacked: ApiConfig.useApiOrder),
          update: (_, auth, notifier, order) {
            order!.attachNotifier(notifier);
            // Своя история у каждого аккаунта (аудит C03).
            order.syncAuth(auth.isLoggedIn, userId: auth.user?.id);
            return order;
          },
        ),
        ChangeNotifierProvider(create: (_) => TabNotifier(4)),
      ],
      child: SportStoreApp(prefs: prefs),
    ),
  );
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
