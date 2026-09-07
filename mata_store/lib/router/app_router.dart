import 'package:go_router/go_router.dart';
import 'package:sentry_flutter/sentry_flutter.dart';
import '../screens/main_shell.dart';
import '../screens/home/home_screen.dart';
import '../screens/catalog/catalog_screen.dart';
import '../screens/product/product_detail_screen.dart';
import '../screens/cart/cart_screen.dart';
import '../screens/profile/profile_screen.dart';
import '../screens/search/search_screen.dart';
import '../screens/checkout/checkout_screen.dart';
import '../screens/checkout/order_success_screen.dart';
import '../screens/checkout/payment_screen.dart';
import '../screens/notifications/notifications_screen.dart';
import '../screens/loyalty/loyalty_screen.dart';

final appRouter = GoRouter(
  initialLocation: '/',
  // Крошки переходов между экранами (D-32) — путь пользователя до падения.
  observers: [SentryNavigatorObserver()],
  routes: [
    StatefulShellRoute.indexedStack(
      builder: (context, state, shell) => MainShell(shell: shell),
      branches: [
        StatefulShellBranch(
          routes: [
            GoRoute(
              path: '/',
              builder: (context, state) => const HomeScreen(),
            ),
          ],
        ),
        StatefulShellBranch(
          routes: [
            GoRoute(
              path: '/catalog',
              builder: (context, state) {
                final categoryId = state.uri.queryParameters['category'];
                return CatalogScreen(initialCategory: categoryId);
              },
            ),
          ],
        ),
        StatefulShellBranch(
          routes: [
            GoRoute(
              path: '/cart',
              builder: (context, state) => const CartScreen(),
            ),
          ],
        ),
        StatefulShellBranch(
          routes: [
            GoRoute(
              path: '/profile',
              builder: (context, state) => const ProfileScreen(),
            ),
          ],
        ),
      ],
    ),
    GoRoute(
      path: '/product/:id',
      builder: (context, state) {
        final id = state.pathParameters['id']!;
        final heroTag = state.extra is String ? state.extra as String : null;
        return ProductDetailScreen(productId: id, heroTag: heroTag);
      },
    ),
    GoRoute(
      path: '/search',
      builder: (context, state) => const SearchScreen(),
    ),
    GoRoute(
      path: '/notifications',
      builder: (context, state) => const NotificationsScreen(),
    ),
    GoRoute(
      path: '/loyalty',
      builder: (context, state) => const LoyaltyScreen(),
    ),
    GoRoute(
      path: '/checkout',
      builder: (context, state) => const CheckoutScreen(),
    ),
    GoRoute(
      path: '/order-payment/:id',
      builder: (context, state) => PaymentScreen(
        orderId: state.pathParameters['id']!,
      ),
    ),
    GoRoute(
      path: '/order-success/:id',
      builder: (context, state) => OrderSuccessScreen(
        orderId: state.pathParameters['id']!,
      ),
    ),
  ],
);
