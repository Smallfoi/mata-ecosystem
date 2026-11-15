import 'package:flutter/material.dart';

import 'app_colors.dart';

/// Оформление единых состояний экрана (`MataEmpty` / `MataError` из `mata_ui`).
///
/// Размеры и отступы держит пакет — одинаково для Store и Квартала. Цвета и
/// шрифты задаёт приложение: темы у них разные. Одно место на всё приложение,
/// чтобы экраны снова не разъехались по кеглям и оттенкам серого.
abstract final class AppStates {
  static TextStyle get title => TextStyle(
        fontSize: 17,
        fontWeight: FontWeight.w700,
        color: AppColors.textPrimary,
      );

  static TextStyle get hint => TextStyle(
        fontSize: 14,
        height: 1.4,
        color: AppColors.textSecondary,
      );

  /// Иконка состояния. «Не текст» по D-127, поэтому не бледнее третьего
  /// уровня: раньше её рисовали цветом `disabled` и на светлой теме она была
  /// почти не видна.
  static Color get icon => AppColors.textTertiary;

  /// Кнопка «Повторить» для `MataError`.
  static Widget retry(BuildContext context, String label, VoidCallback onTap) =>
      OutlinedButton(onPressed: onTap, child: Text(label));
}
