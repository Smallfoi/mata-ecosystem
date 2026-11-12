import 'package:flutter/material.dart';
import 'package:mata_ui/mata_ui.dart';

import 'app_theme.dart';

/// Цвета ввода кода OTP V5 (виджет — общий, `OtpVerifyBoxes` из mata_ui)
/// под светлую тему Store: чёрный акцент. Значения 1:1 с прежней локальной
/// копией виджета (D-126) — дизайн не менялся.
final storeOtpBoxesStyle = OtpBoxesStyle(
  accent: AppColors.black,
  currentShadow: AppColors.black.withValues(alpha: 0.12),
  currentShadowBlur: 14,
  filledBorder: AppColors.grey800,
  emptyBorder: AppColors.grey200,
  cellBackground: AppColors.white,
  digit: AppColors.black,
  error: AppColors.red,
  success: AppColors.success,
  verifiedBackground: const Color(0xFFEAF4EC),
  verifiedShadow: AppColors.success.withValues(alpha: 0.3),
  spark: const Color(0xFF66BB6A),
  cursorRequiresFocus: true,
);
