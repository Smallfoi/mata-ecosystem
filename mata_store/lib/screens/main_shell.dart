import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';
import 'package:badges/badges.dart' as badges;
import '../providers/cart_provider.dart';
import '../providers/tab_notifier.dart';
import '../services/update_checker.dart';
import '../theme/app_theme.dart';
import '../widgets/remote_labels.dart';

class MainShell extends StatefulWidget {
  final StatefulNavigationShell shell;

  const MainShell({super.key, required this.shell});

  @override
  State<MainShell> createState() => _MainShellState();
}

class _MainShellState extends State<MainShell> {
  /// Ключ экрана для добавленных подписей конструктора (по активной вкладке).
  static const _tabKeys = ['home', 'catalog', 'cart', 'profile'];

  @override
  void initState() {
    super.initState();
    // Проверка обновления тест-сборки (Android): баннер, если в S3 версия новее.
    WidgetsBinding.instance
        .addPostFrameCallback((_) => UpdateChecker.check(context));
  }

  @override
  Widget build(BuildContext context) {
    final shell = widget.shell;
    final screenKey = _tabKeys[shell.currentIndex.clamp(0, _tabKeys.length - 1)];
    return Scaffold(
      body: Stack(
        children: [
          shell,
          // Слой «➕ добавить текст» поверх активной вкладки (правится в конструкторе).
          Positioned.fill(child: RemoteLabelsLayer(screenKey)),
        ],
      ),
      bottomNavigationBar: Container(
        decoration: const BoxDecoration(
          border: Border(top: BorderSide(color: AppColors.grey200, width: 1)),
        ),
        child: Consumer<CartProvider>(
          builder: (context, cart, _) {
            return BottomNavigationBar(
              currentIndex: shell.currentIndex,
              onTap: (index) {
                context.read<TabNotifier>().switchTo(index);
                shell.goBranch(
                  index,
                  initialLocation: index == shell.currentIndex,
                );
              },
              items: [
                const BottomNavigationBarItem(
                  icon: Icon(Icons.home_outlined),
                  activeIcon: Icon(Icons.home),
                  label: 'Главная',
                ),
                const BottomNavigationBarItem(
                  icon: Icon(Icons.grid_view_outlined),
                  activeIcon: Icon(Icons.grid_view),
                  label: 'Каталог',
                ),
                BottomNavigationBarItem(
                  icon: badges.Badge(
                    showBadge: cart.itemCount > 0,
                    badgeContent: Text(
                      '${cart.itemCount}',
                      style: const TextStyle(
                        color: AppColors.white,
                        fontSize: 11,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    badgeStyle: const badges.BadgeStyle(
                      badgeColor: AppColors.black,
                      padding: EdgeInsets.all(4),
                    ),
                    child: const Icon(Icons.shopping_bag_outlined),
                  ),
                  activeIcon: badges.Badge(
                    showBadge: cart.itemCount > 0,
                    badgeContent: Text(
                      '${cart.itemCount}',
                      style: const TextStyle(
                        color: AppColors.white,
                        fontSize: 11,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    badgeStyle: const badges.BadgeStyle(
                      badgeColor: AppColors.black,
                      padding: EdgeInsets.all(4),
                    ),
                    child: const Icon(Icons.shopping_bag),
                  ),
                  label: 'Корзина',
                ),
                const BottomNavigationBarItem(
                  icon: Icon(Icons.person_outline),
                  activeIcon: Icon(Icons.person),
                  label: 'Профиль',
                ),
              ],
            );
          },
        ),
      ),
    );
  }
}
