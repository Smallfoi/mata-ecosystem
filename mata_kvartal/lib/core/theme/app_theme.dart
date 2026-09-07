import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'app_colors.dart';

/// Тема «Квартал 2.0» (Ф8, утверждено 31.08.2026).
///
/// Ритм прежний: скругления 14/22/30, мягкие тени, кнопка-«таблетка», одна
/// кривая движения. Типографика пакета дизайнов: Manrope — крупное/заголовки,
/// Inter — текст и данные. Тема строится из геттеров AppColors, поэтому одна
/// функция [current] отдаёт и графитовый, и светлый интерьер.
class AppTheme {
  AppTheme._();

  /// Шрифт текста и данных.
  static const fontText = 'Inter';

  /// Шрифт крупных заголовков и чисел.
  static const fontDisplay = 'Manrope';

  // Скругления сайта.
  static const rSm = 14.0;
  static const rMd = 22.0;
  static const rLg = 30.0;
  static const rPill = 999.0;

  /// Фирменное замедление сайта — одна подпись движения на все переходы.
  static const ease = Cubic(0.33, 1, 0.34, 1);
  static const durFast = Duration(milliseconds: 260);
  static const durSlow = Duration(milliseconds: 600);

  /// Мягкая премиальная тень (карточки).
  static List<BoxShadow> get shadowSm => const [
    BoxShadow(color: Color(0x14202529), blurRadius: 34, offset: Offset(0, 12)),
  ];

  /// Тень для плавающих панелей над картой.
  static List<BoxShadow> get shadowMd => const [
    BoxShadow(color: Color(0x1F202529), blurRadius: 60, offset: Offset(0, 22)),
  ];

  /// Крупный дисплейный стиль: заголовки экранов и числа пробежки.
  static TextStyle display(
    double size, {
    FontWeight weight = FontWeight.w700,
    Color? color,
    double? height,
  }) => TextStyle(
    fontFamily: fontDisplay,
    fontSize: size,
    fontWeight: weight,
    color: color ?? AppColors.ink,
    height: height,
    letterSpacing: -0.02 * size,
    // Цифры не должны «прыгать» на бегу.
    fontFeatures: const [FontFeature.tabularFigures()],
  );

  /// Мелкая подпись капсом с разрядкой — «eyebrow» с сайта.
  static TextStyle eyebrow({Color? color}) => TextStyle(
    fontFamily: fontText,
    fontSize: 11,
    fontWeight: FontWeight.w800,
    color: color ?? AppColors.accentInk,
    letterSpacing: 0.18 * 11,
  );

  static TextStyle _t(
    double size,
    FontWeight weight,
    Color color, {
    double? letterSpacing,
    double? height,
  }) => TextStyle(
    fontFamily: fontText,
    fontSize: size,
    fontWeight: weight,
    color: color,
    letterSpacing: letterSpacing,
    height: height,
  );

  /// Текущая тема — по AppColors.isGraphite (выставляет тема-контроллер).
  static ThemeData current() {
    final g = AppColors.isGraphite;
    // Главное действие: на светлом — графитовая кнопка с лаймовым текстом
    // (как в дизайн-проектах), на графите — лаймовая кнопка с тёмным текстом.
    final ctaBg = g ? AppColors.lime : AppColors.block;
    final ctaFg = g ? const Color(0xFF171C19) : AppColors.lime;
    return ThemeData(
      useMaterial3: true,
      brightness: g ? Brightness.dark : Brightness.light,
      fontFamily: fontText,
      colorScheme: ColorScheme(
        brightness: g ? Brightness.dark : Brightness.light,
        primary: ctaBg,
        onPrimary: ctaFg,
        secondary: AppColors.accent,
        onSecondary: AppColors.onDark,
        tertiary: AppColors.lime,
        onTertiary: const Color(0xFF171C19),
        surface: AppColors.paper,
        onSurface: AppColors.ink,
        surfaceContainerHighest: AppColors.soft,
        // Тональные кнопки (IconButton.filledTonal) берут цвет отсюда.
        secondaryContainer: AppColors.soft,
        onSecondaryContainer: AppColors.accentInk,
        outline: AppColors.line,
        error: AppColors.error,
        onError: g ? const Color(0xFF171C19) : AppColors.onDark,
      ),
      scaffoldBackgroundColor: AppColors.bg,
      appBarTheme: AppBarTheme(
        backgroundColor: AppColors.bg,
        foregroundColor: AppColors.ink,
        elevation: 0,
        scrolledUnderElevation: 0,
        systemOverlayStyle: SystemUiOverlayStyle(
          statusBarColor: Colors.transparent,
          statusBarIconBrightness: g ? Brightness.light : Brightness.dark,
          statusBarBrightness: g ? Brightness.dark : Brightness.light,
        ),
        titleTextStyle: display(19, weight: FontWeight.w600),
      ),
      cardTheme: CardThemeData(
        color: AppColors.paper,
        elevation: 0,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(rMd),
          side: BorderSide(color: AppColors.line),
        ),
        margin: EdgeInsets.zero,
      ),
      elevatedButtonTheme: ElevatedButtonThemeData(
        style: ElevatedButton.styleFrom(
          backgroundColor: ctaBg,
          foregroundColor: ctaFg,
          // Только высота: Size.fromHeight — это Size(бесконечность, 54), и в Row
          // такая кнопка требует бесконечную ширину и роняет раскладку экрана.
          minimumSize: const Size(64, 54),
          shape: const StadiumBorder(),
          textStyle: _t(15, FontWeight.w800, ctaFg, letterSpacing: 0.15),
          elevation: 0,
        ),
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          backgroundColor: ctaBg,
          foregroundColor: ctaFg,
          // Только высота: Size.fromHeight — это Size(бесконечность, 54), и в Row
          // такая кнопка требует бесконечную ширину и роняет раскладку экрана.
          minimumSize: const Size(64, 54),
          shape: const StadiumBorder(),
          textStyle: _t(15, FontWeight.w800, ctaFg, letterSpacing: 0.15),
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          foregroundColor: AppColors.ink,
          // Только высота: Size.fromHeight — это Size(бесконечность, 54), и в Row
          // такая кнопка требует бесконечную ширину и роняет раскладку экрана.
          minimumSize: const Size(64, 54),
          side: BorderSide(color: AppColors.line),
          shape: const StadiumBorder(),
          textStyle: _t(15, FontWeight.w800, AppColors.ink, letterSpacing: 0.15),
        ),
      ),
      textButtonTheme: TextButtonThemeData(
        style: TextButton.styleFrom(
          foregroundColor: AppColors.accentInk,
          textStyle: _t(15, FontWeight.w700, AppColors.accentInk),
        ),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: AppColors.paper,
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(rMd),
          borderSide: BorderSide(color: AppColors.line),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(rMd),
          borderSide: BorderSide(color: AppColors.line),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(rMd),
          borderSide: BorderSide(color: AppColors.accent, width: 2),
        ),
        hintStyle: _t(15, FontWeight.w400, AppColors.disabled),
        labelStyle: _t(15, FontWeight.w500, AppColors.muted),
        contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 16),
      ),
      dividerTheme: DividerThemeData(
        color: AppColors.line,
        thickness: 1,
        space: 1,
      ),
      iconTheme: IconThemeData(color: AppColors.muted, size: 24),
      floatingActionButtonTheme: const FloatingActionButtonThemeData(
        backgroundColor: AppColors.lime,
        foregroundColor: Color(0xFF171C19),
        elevation: 0,
        shape: CircleBorder(),
      ),
      chipTheme: ChipThemeData(
        backgroundColor: AppColors.soft,
        labelStyle: _t(12, FontWeight.w800, AppColors.ink),
        side: BorderSide.none,
        shape: const StadiumBorder(),
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
      ),
      bottomSheetTheme: BottomSheetThemeData(
        backgroundColor: AppColors.paper,
        surfaceTintColor: Colors.transparent,
        shape: const RoundedRectangleBorder(
          borderRadius: BorderRadius.vertical(top: Radius.circular(rLg)),
        ),
      ),
      dialogTheme: DialogThemeData(
        backgroundColor: AppColors.paper,
        surfaceTintColor: Colors.transparent,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(rLg)),
      ),
      snackBarTheme: SnackBarThemeData(
        backgroundColor: g ? AppColors.panel : AppColors.block,
        contentTextStyle: _t(14, FontWeight.w600, AppColors.onDark),
        behavior: SnackBarBehavior.floating,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(rSm)),
      ),
      splashFactory: InkSparkle.splashFactory,
      textTheme: TextTheme(
        // Крупное — дисплейным шрифтом, как заголовки сайта.
        displayLarge: display(56),
        displayMedium: display(44),
        displaySmall: display(34),
        headlineLarge: display(30),
        headlineMedium: display(25, weight: FontWeight.w600),
        headlineSmall: display(21, weight: FontWeight.w600),
        titleLarge: display(19, weight: FontWeight.w600),
        titleMedium: _t(16, FontWeight.w800, AppColors.ink),
        titleSmall: _t(14, FontWeight.w700, AppColors.muted),
        bodyLarge: _t(16, FontWeight.w400, AppColors.ink, height: 1.55),
        bodyMedium: _t(14.5, FontWeight.w400, AppColors.ink, height: 1.5),
        bodySmall: _t(13, FontWeight.w400, AppColors.muted, height: 1.45),
        labelLarge: _t(15, FontWeight.w800, AppColors.ink),
        labelMedium: _t(13, FontWeight.w700, AppColors.muted),
        labelSmall: _t(11, FontWeight.w700, AppColors.faint),
      ),
    );
  }

  /// Прежние имена. Оба отдают текущий интерьер — см. [current].
  static ThemeData get light => current();
  static ThemeData get dark => current();
}
