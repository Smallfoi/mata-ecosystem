import 'package:flutter/material.dart';
import 'package:mata_ui/mata_ui.dart';

import '../../../../core/theme/app_colors.dart';

/// Цвета ввода кода OTP V5 (виджет — общий, `OtpVerifyBoxes` из mata_ui)
/// под ТЕКУЩИЙ интерьер Квартала (графит/светлый). Функция, а не константа:
/// геттеры AppColors зависят от AppColors.isGraphite, поэтому стиль читается
/// заново при каждой сборке экрана. Значения 1:1 с прежней локальной копией
/// виджета (D-126) — дизайн не менялся.
OtpBoxesStyle kvartalOtpBoxesStyle() => OtpBoxesStyle(
  accent: AppColors.electricBlue,
  currentShadow: AppColors.electricBlue.withValues(alpha: 0.25),
  currentShadowBlur: 18,
  filledBorder: AppColors.electricBlue.withValues(alpha: 0.4),
  emptyBorder: AppColors.bgElevated,
  cellBackground: AppColors.paper,
  digit: AppColors.textPrimary,
  error: AppColors.error,
  success: AppColors.success,
  verifiedBackground: AppColors.success.withValues(alpha: 0.12),
  verifiedShadow: AppColors.success.withValues(alpha: 0.4),
  spark: const Color(0xFF4ADE80),
);
