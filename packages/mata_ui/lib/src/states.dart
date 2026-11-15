import 'package:flutter/widgets.dart';
import 'package:flutter/cupertino.dart' show CupertinoActivityIndicator, CupertinoIcons;

/// Единые состояния экрана для Store и Квартала (пункт «states», утверждён
/// владельцем 15.11.2026).
///
/// До этого каждый экран рисовал их по-своему: иконка 40 / 44 / 54 / 56 / 64,
/// отступ под ней 12 / 16 / 20, заголовок 15 / 16 / 18 / 20 пунктов,
/// полужирный то w700, то w800. Здесь — один стандарт размеров и отступов;
/// цвета и шрифты приходят из приложения, потому что темы у них разные.
///
/// Текст можно передать строкой (`title`) или готовым виджетом (`titleWidget`).
/// Виджет нужен МАТА Store: там видимый контент идёт через `RemoteText`, чтобы
/// владелец правил его в Конструкторе.

/// Размеры состояний. Один набор на экосистему — чтобы «пусто» и «ошибка»
/// выглядели одинаково в любом разделе обоих приложений.
abstract final class MataStateMetrics {
  /// Иконка состояния.
  static const double iconSize = 52;

  /// Иконка → заголовок.
  static const double gapIconTitle = 16;

  /// Заголовок → пояснение.
  static const double gapTitleHint = 6;

  /// Пояснение → кнопка действия.
  static const double gapHintAction = 20;

  /// Поля вокруг блока.
  static const EdgeInsets padding =
      EdgeInsets.symmetric(horizontal: 32, vertical: 24);

  /// Запасные стили: применяются, если приложение не задало свои. Цвет не
  /// указан намеренно — его подхватит `DefaultTextStyle` экрана.
  static const TextStyle titleStyle =
      TextStyle(fontSize: 17, fontWeight: FontWeight.w700);
  static const TextStyle hintStyle = TextStyle(fontSize: 14, height: 1.4);
}

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
    this.title,
    this.titleWidget,
    this.titleStyle,
    this.hint,
    this.hintWidget,
    this.hintStyle,
    this.icon,
    this.iconColor,
    this.action,
  }) : assert(
          title != null || titleWidget != null,
          'состояние без заголовка не объясняет пользователю ничего',
        ),
        assert(
          title == null || titleWidget == null,
          'заголовок задаётся либо строкой, либо виджетом',
        ),
        assert(
          hint == null || hintWidget == null,
          'пояснение задаётся либо строкой, либо виджетом',
        );

  /// Заголовок строкой.
  final String? title;

  /// Заголовок готовым виджетом — для `RemoteText` в МАТА Store.
  final Widget? titleWidget;
  final TextStyle? titleStyle;

  final String? hint;

  /// Пояснение готовым виджетом — для `RemoteText` в МАТА Store.
  final Widget? hintWidget;
  final TextStyle? hintStyle;

  final IconData? icon;
  final Color? iconColor;

  /// Кнопка действия. Если действия нет — не выдумываем его.
  final Widget? action;

  @override
  Widget build(BuildContext context) {
    final titleChild = titleWidget ??
        Text(
          title!,
          textAlign: TextAlign.center,
          style: titleStyle ?? MataStateMetrics.titleStyle,
        );
    final hintChild = hintWidget ??
        (hint == null
            ? null
            : Text(
                hint!,
                textAlign: TextAlign.center,
                style: hintStyle ?? MataStateMetrics.hintStyle,
              ));

    return Center(
      child: Padding(
        padding: MataStateMetrics.padding,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (icon != null) ...[
              Icon(icon, size: MataStateMetrics.iconSize, color: iconColor),
              const SizedBox(height: MataStateMetrics.gapIconTitle),
            ],
            titleChild,
            if (hintChild != null) ...[
              const SizedBox(height: MataStateMetrics.gapTitleHint),
              hintChild,
            ],
            if (action != null) ...[
              const SizedBox(height: MataStateMetrics.gapHintAction),
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
    this.title,
    this.titleWidget,
    this.titleStyle,
    required this.retryLabel,
    required this.onRetry,
    required this.retryBuilder,
    this.hint,
    this.hintWidget,
    this.hintStyle,
    this.icon,
    this.iconColor,
  });

  final String? title;
  final Widget? titleWidget;
  final TextStyle? titleStyle;

  final String? hint;
  final Widget? hintWidget;
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
      titleWidget: titleWidget,
      titleStyle: titleStyle,
      hint: hint,
      hintWidget: hintWidget,
      hintStyle: hintStyle,
      icon: icon ?? CupertinoIcons.exclamationmark_triangle,
      iconColor: iconColor,
      action: retryBuilder(context, retryLabel, onRetry),
    );
  }
}
