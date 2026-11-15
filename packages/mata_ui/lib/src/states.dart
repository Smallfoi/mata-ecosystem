import 'package:flutter/cupertino.dart';

/// Единые состояния экрана для Store и Квартала (пункт «states», утверждён
/// владельцем 15.11.2026).
///
/// До этого каждый экран рисовал их по-своему: где-то крутилка Android,
/// где-то iOS, где-то просто пустота. Здесь — один стандарт; цвета приходят
/// из приложения, потому что темы у них разные.

/// Ожидание. Одна крутилка на всю экосистему — в стиле iOS, как и иконки.
class MataLoading extends StatelessWidget {
  const MataLoading({super.key, this.color, this.radius = 11, this.padding});

  /// Цвет крутилки. `null` — цвет по теме Cupertino.
  final Color? color;

  /// Радиус в логических пикселях: 8 — внутри кнопки, 11 — на экране.
  final double radius;

  final EdgeInsetsGeometry? padding;

  @override
  Widget build(BuildContext context) {
    final spinner = color == null
        ? CupertinoActivityIndicator(radius: radius)
        : CupertinoActivityIndicator(radius: radius, color: color);
    return Center(
      child: padding == null ? spinner : Padding(padding: padding!, child: spinner),
    );
  }
}

/// Пусто. Не голый экран, а объяснение и — где уместно — действие.
class MataEmpty extends StatelessWidget {
  const MataEmpty({
    super.key,
    required this.title,
    required this.titleStyle,
    this.hint,
    this.hintStyle,
    this.icon,
    this.iconColor,
    this.action,
  });

  final String title;
  final TextStyle titleStyle;
  final String? hint;
  final TextStyle? hintStyle;
  final IconData? icon;
  final Color? iconColor;

  /// Кнопка действия. Если действия нет — не выдумываем его.
  final Widget? action;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 32, vertical: 24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (icon != null) ...[
              Icon(icon, size: 34, color: iconColor),
              const SizedBox(height: 14),
            ],
            Text(title, textAlign: TextAlign.center, style: titleStyle),
            if (hint != null) ...[
              const SizedBox(height: 6),
              Text(hint!, textAlign: TextAlign.center, style: hintStyle),
            ],
            if (action != null) ...[
              const SizedBox(height: 18),
              action!,
            ],
          ],
        ),
      ),
    );
  }
}

/// Ошибка. Всегда объясняет, что не вышло, и всегда даёт «Повторить».
class MataError extends StatelessWidget {
  const MataError({
    super.key,
    required this.title,
    required this.titleStyle,
    required this.retryLabel,
    required this.onRetry,
    required this.retryBuilder,
    this.hint,
    this.hintStyle,
    this.icon,
    this.iconColor,
  });

  final String title;
  final TextStyle titleStyle;
  final String? hint;
  final TextStyle? hintStyle;
  final IconData? icon;
  final Color? iconColor;

  final String retryLabel;
  final VoidCallback onRetry;

  /// Кнопку рисует приложение — у Store и Квартала они разные.
  final Widget Function(BuildContext context, String label, VoidCallback onTap)
      retryBuilder;

  @override
  Widget build(BuildContext context) {
    return MataEmpty(
      title: title,
      titleStyle: titleStyle,
      hint: hint,
      hintStyle: hintStyle,
      icon: icon ?? CupertinoIcons.exclamationmark_triangle,
      iconColor: iconColor,
      action: retryBuilder(context, retryLabel, onRetry),
    );
  }
}
