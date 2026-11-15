import 'package:flutter/material.dart';

import '../widgets/remote_text.dart';
import 'app_theme.dart';

/// Оформление единых состояний экрана (`MataEmpty` / `MataError` из `mata_ui`).
///
/// Размеры и отступы держит пакет — одинаково для Store и Квартала. Цвета и
/// шрифты задаёт приложение. Сами тексты состояний идут через `RemoteText`:
/// это видимый контент, владелец правит его в Конструкторе.
abstract final class AppStates {
  static const TextStyle title = TextStyle(
    fontSize: 17,
    fontWeight: FontWeight.w700,
    color: AppColors.black,
  );

  static const TextStyle hint = TextStyle(
    fontSize: 14,
    height: 1.4,
    color: AppColors.grey600,
  );

  /// Иконка состояния. «Не текст» по D-127: `grey200` давал Lc 0 — иконку
  /// просто не было видно.
  static const Color icon = AppColors.grey500;

  /// Кнопка «Повторить» для `MataError`. Подпись редактируется в Конструкторе.
  static Widget retry(BuildContext context, String label, VoidCallback onTap) =>
      OutlinedButton(
        onPressed: onTap,
        child: RemoteText('app.common.retry', label),
      );
}
