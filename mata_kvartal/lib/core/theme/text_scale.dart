import 'package:flutter/widgets.dart';

/// Предел увеличения шрифта из настроек телефона.
///
/// Размеры текста в приложении заданы вручную, и при «огромном» системном
/// шрифте (до 3× на iOS/Android) строки вылезают за карточки, карту и экран
/// забега. Шрифт по-прежнему растёт вместе с настройкой, но не больше чем
/// в 1,3 раза; уменьшение не ограничиваем.
const double kMaxTextScale = 1.3;

/// Для `MaterialApp.builder`: ограничивает масштаб текста во всём приложении.
Widget clampTextScale(BuildContext context, Widget? child) {
  return MediaQuery.withClampedTextScaling(
    maxScaleFactor: kMaxTextScale,
    child: child ?? const SizedBox.shrink(),
  );
}
