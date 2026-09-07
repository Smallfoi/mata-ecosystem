import 'dart:ui' show ImageFilter;
import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import '../../core/constants/app_strings.dart';
import '../../core/router/app_router.dart';
import '../../core/services/update_checker.dart';
import '../../core/theme/app_colors.dart';
import '../../features/league/data/league_provider.dart';
import '../../features/shoes/data/shoes_provider.dart';
import '../../features/shoes/presentation/shoe_prompt.dart';
import 'kvartal_logo.dart';

class MainScaffold extends ConsumerStatefulWidget {
  /// Ветки вкладок: экраны сохраняются между переключениями (см. app_router).
  final StatefulNavigationShell navigationShell;
  const MainScaffold({super.key, required this.navigationShell});

  @override
  ConsumerState<MainScaffold> createState() => _MainScaffoldState();
}

class _MainScaffoldState extends ConsumerState<MainScaffold> {
  // Спрашиваем про новые покупки один раз за запуск приложения.
  bool _askedPending = false;
  bool _asking = false;
  bool _askedFocus = false;

  void _onTap(int index) {
    // Закрываем модальный лист/диалог, открытый на покидаемой вкладке (погода,
    // выбор кроссовок): страничные маршруты вкладки не трогаем — их ведёт роутер.
    final nav = tabNavigatorKeys[widget.navigationShell.currentIndex].currentState;
    nav?.popUntil((route) => route is! PopupRoute);
    // Повторное нажатие активной вкладки — возврат в её начало.
    widget.navigationShell.goBranch(
      index,
      initialLocation: index == widget.navigationShell.currentIndex,
    );
  }

  /// При открытии приложения, как только подгрузились купленные кроссовки,
  /// всплывает окно «Добавить кроссовки в приложение?» — глобально, на любом табе.
  Future<void> _maybeAskPending() async {
    if (_askedPending || _asking) return;
    final st = ref.read(shoesProvider);
    if (!st.loaded || st.pending.isEmpty) return;
    _asking = true;
    _askedPending = true;
    await promptPendingShoes(context, ref);
    _asking = false;
  }

  /// Первый вход — спрашиваем, зачем человек бегает, и отправляем его на
  /// подходящий экран. Гибкость без этого вопроса превращается в кашу: пять
  /// зачётов, территории, тропы и клубы разом новичок не осилит.
  ///
  /// Спрашиваем один раз: ответ (в том числе «пропустить») хранится в профиле
  /// на сервере, а не локально — иначе вопрос всплывёт на втором устройстве.
  Future<void> _maybeAskFocus() async {
    if (_askedFocus) return;
    _askedFocus = true;
    try {
      final profile = await ref.read(runnerProfileProvider.future);
      if (!mounted || !profile.needsFocus) return;
      context.push('/focus');
    } catch (_) {
      // Нет сети — спросим в следующий раз, это не повод задерживать человека.
      _askedFocus = false;
    }
  }

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _maybeAskFocus());
    WidgetsBinding.instance.addPostFrameCallback((_) => _maybeAskPending());
    // Проверка обновления тест-сборки (Android): баннер, если в S3 версия новее.
    WidgetsBinding.instance
        .addPostFrameCallback((_) => UpdateChecker.check(context));
  }

  @override
  Widget build(BuildContext context) {
    // Новые покупки могли подгрузиться позже первого кадра — реагируем на это.
    ref.listen<ShoesState>(shoesProvider, (_, __) => _maybeAskPending());

    return Scaffold(
      extendBody: true,
      body: widget.navigationShell,
      // Центральная кнопка «Бег» — приподнятая плита знака (мотив эмблемы
      // дивизиона и медалей): док по центру, наполовину над баром.
      floatingActionButton: _RunPlate(
        isActive: widget.navigationShell.currentIndex == 1,
        onTap: () => _onTap(1),
      ),
      floatingActionButtonLocation: FloatingActionButtonLocation.centerDocked,
      bottomNavigationBar: _KvartalNavBar(
        currentIndex: widget.navigationShell.currentIndex,
        onTap: _onTap,
      ),
    );
  }
}

// ── Плита «Бег» над баром ────────────────────────────────────────────────────

class _RunPlate extends StatelessWidget {
  final bool isActive;
  final VoidCallback onTap;
  const _RunPlate({required this.isActive, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      behavior: HitTestBehavior.opaque,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 220),
        curve: Curves.easeOutCubic,
        // Плита всегда графитовая (замечание владельца: тёмный знак на лайме
        // смотрится плохо). Активность — яркий знак, полная лаймовая рамка,
        // сильное свечение по контуру и лёгкий рост плиты.
        width: isActive ? 62 : 58,
        height: isActive ? 62 : 58,
        decoration: BoxDecoration(
          color: AppColors.block,
          borderRadius: BorderRadius.circular(isActive ? 20 : 19),
          border: Border.all(
            color: AppColors.lime.withValues(alpha: isActive ? 1 : .45),
            width: isActive ? 1.8 : 1.3,
          ),
          boxShadow: [
            // Свечение строго по контуру плиты — без кругов и пульсов.
            BoxShadow(
              color: AppColors.lime.withValues(alpha: isActive ? .5 : .15),
              blurRadius: isActive ? 26 : 10,
              spreadRadius: isActive ? 2 : 1,
            ),
            BoxShadow(
              color: const Color(0x66101312),
              blurRadius: 18,
              offset: const Offset(0, 8),
            ),
          ],
        ),
        child: Center(
          child: KvartalLogoMark(
            size: isActive ? 33 : 30,
            animated: isActive,
            glow: false,
            outline: const Color(0xFFEDEFE8),
            fill: AppColors.lime,
          ),
        ),
      ),
    );
  }
}

class _KvartalNavBar extends StatelessWidget {
  final int currentIndex;
  final ValueChanged<int> onTap;
  const _KvartalNavBar({required this.currentIndex, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return ClipRect(
      child: BackdropFilter(
        filter: ImageFilter.blur(sigmaX: 20, sigmaY: 20),
        child: Container(
          decoration: BoxDecoration(
            color: AppColors.glass,
            border: Border(
              top: BorderSide(
                color: AppColors.line,
                width: 1,
              ),
            ),
          ),
          child: SafeArea(
            top: false,
            child: SizedBox(
              height: 62,
              // Порядок слева→направо: Карта · Рейтинг · [БЕГ центр] · Клуб · Профиль.
              // Пять пунктов — рекомендованный максимум; «Бег» остаётся акцентной
              // центральной кнопкой (2+центр+2).
              child: Row(
                children: [
                  _NavItem(
                    icon: CupertinoIcons.map,
                    activeIcon: CupertinoIcons.map_fill,
                    label: AppStrings.tabMap,
                    isActive: currentIndex == 0,
                    onTap: () => onTap(0),
                  ),
                  _NavItem(
                    icon: CupertinoIcons.chart_bar_alt_fill,
                    activeIcon: CupertinoIcons.chart_bar_alt_fill,
                    label: AppStrings.tabLeaderboard,
                    isActive: currentIndex == 2,
                    onTap: () => onTap(2),
                  ),
                  _RunNavItem(
                    isActive: currentIndex == 1,
                    onTap: () => onTap(1),
                  ),
                  _NavItem(
                    icon: CupertinoIcons.person_2,
                    activeIcon: CupertinoIcons.person_2_fill,
                    label: AppStrings.tabClub,
                    isActive: currentIndex == 3,
                    onTap: () => onTap(3),
                  ),
                  _NavItem(
                    icon: CupertinoIcons.person,
                    activeIcon: CupertinoIcons.person_fill,
                    label: AppStrings.tabProfile,
                    isActive: currentIndex == 4,
                    onTap: () => onTap(4),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

// ── Центральная кнопка «Бег» ──────────────────────────────────────────────────

class _RunNavItem extends StatelessWidget {
  final bool isActive;
  final VoidCallback onTap;
  const _RunNavItem({required this.isActive, required this.onTap});

  @override
  Widget build(BuildContext context) {
    // Сама плита знака — приподнятый FAB над баром (_RunPlate); в баре
    // остаётся только подпись, выровненная по остальным вкладкам.
    return Expanded(
      child: GestureDetector(
        onTap: onTap,
        behavior: HitTestBehavior.opaque,
        child: Column(
          mainAxisAlignment: MainAxisAlignment.end,
          children: [
            Text(
              AppStrings.tabRun,
              style: TextStyle(
                fontSize: 10,
                height: 1.0,
                letterSpacing: -0.2,
                fontWeight: FontWeight.w700, // центр — акцент
                color: isActive ? AppColors.ink : AppColors.muted,
              ),
            ),
            const SizedBox(height: 8),
          ],
        ),
      ),
    );
  }
}

// ── Обычный таб ───────────────────────────────────────────────────────────────

class _NavItem extends StatelessWidget {
  final IconData icon;
  final IconData activeIcon;
  final String label;
  final bool isActive;
  final VoidCallback onTap;

  const _NavItem({
    required this.icon,
    required this.activeIcon,
    required this.label,
    required this.isActive,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final color = isActive ? AppColors.ink : AppColors.muted;

    return Expanded(
      child: GestureDetector(
        onTap: onTap,
        behavior: HitTestBehavior.opaque,
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            AnimatedSwitcher(
              duration: const Duration(milliseconds: 180),
              child: Icon(
                isActive ? activeIcon : icon,
                key: ValueKey(isActive),
                color: color,
                size: 23,
              ),
            ),
            const SizedBox(height: 3),
            // Единый фиксированный размер у ВСЕХ подписей (без FittedBox/scaleDown,
            // который раньше ужимал длинные слова в разный кегль). Короткие подписи
            // + мелкий ровный шрифт → ничего не «скачет» и не обрезается.
            Text(
              label,
              maxLines: 1,
              softWrap: false,
              textAlign: TextAlign.center,
              overflow: TextOverflow.visible,
              style: TextStyle(
                fontSize: 10,
                height: 1.0,
                letterSpacing: -0.2,
                fontWeight: isActive ? FontWeight.w600 : FontWeight.w500,
                color: color,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
