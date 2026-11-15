import 'package:flutter/material.dart';

/// Палитра «Квартал 2.0» (Ф8 «Графитовый интерьер», утверждено 31.08.2026).
///
/// Два интерьера на одних именах: графит (по умолчанию) и светлый. Экран
/// написан один раз против `AppColors.*`, а тема выбирается флагом [graphite],
/// который выставляет тема-контроллер ПЕРЕД пересборкой дерева (main.dart
/// пересобирает приложение по ключу темы). Поэтому здесь геттеры, а не const.
///
/// Словарь цвета (утверждён): лайм — только «моё» и главное действие;
/// тёплый — чужое и угрозы; teal — уровень/структура; всё остальное — нейтрали.
class AppColors {
  AppColors._();

  /// Текущий интерьер. Меняет ТОЛЬКО тема-контроллер (core/theme/theme_controller.dart).
  static bool isGraphite = true;

  // ── Поверхности ───────────────────────────────────────────────────────────
  /// Фон экрана: графит #20252B / светлая «бумага» #F0EFE9.
  static Color get bg =>
      isGraphite ? const Color(0xFF20252B) : const Color(0xFFF0EFE9);

  /// Карточки и панели поверх фона.
  static Color get paper =>
      isGraphite ? const Color(0xFF2A302C) : const Color(0xFFFFFFFF);

  /// Приподнятая карточка — максимальный контраст с фоном.
  static Color get panel =>
      isGraphite ? const Color(0xFF2F362F) : const Color(0xFFFFFFFF);

  /// Подложка чипов, аватаров, неактивных состояний.
  static Color get soft =>
      isGraphite ? const Color(0xFF343B35) : const Color(0xFFEFEDE3);

  /// Контраст-блок (главные кнопки, «своя» строка). На графите — глубже фона.
  static Color get block =>
      isGraphite ? const Color(0xFF171C19) : const Color(0xFF20252B);

  /// Историческое имя контраст-блока — им пользуется большинство экранов.
  static Color get graphite => block;

  /// Полупрозрачная панель над картой (навбар, плавающие панели).
  static Color get glassPaper =>
      isGraphite ? const Color(0xF2222824) : const Color(0xF2FFFFFF);

  // ── Текст ─────────────────────────────────────────────────────────────────
  static Color get ink =>
      isGraphite ? const Color(0xFFEFF1EA) : const Color(0xFF20252B);
  static Color get muted =>
      isGraphite ? const Color(0xFFB9C1BB) : const Color(0xFF505650);
  static Color get faint =>
      isGraphite ? const Color(0xFF9FA6A0) : const Color(0xFF666D65);
  static Color get disabled =>
      isGraphite ? const Color(0xFF7E8981) : const Color(0xFFA9ACA4);

  /// Текст на тёмных заливках (контраст-блок, teal-шапка).
  static Color get onDark => const Color(0xFFEFF1EA);

  /// Тонкие границы.
  static Color get line =>
      isGraphite ? const Color(0xFF3A423C) : const Color(0xFFE0DED2);

  // ── Акценты ───────────────────────────────────────────────────────────────
  /// Лайм — ТОЛЬКО «моё» и главное действие.
  static const lime = Color(0xFFDFF45F);

  /// Затемнённый лайм — обводки/текст лаймовой семантики на светлом.
  static const limeDeep = Color(0xFFB9CC3A);

  /// Teal — уровень, структура, крупные заливки (текст на нём — светлый).
  static const teal = Color(0xFF2E6E64);

  /// Тёплый — чужое и угрозы.
  static const warm = Color(0xFFC96A3B);

  /// Крупная акцентная заливка (перекочевало имя от голубого).
  static Color get accent => teal;

  /// Мелкий акцентный текст/иконки/ссылки: на графите teal высветлен.
  static Color get accentInk =>
      isGraphite ? const Color(0xFF9CC9BF) : const Color(0xFF275D55);

  // ── Статусы ───────────────────────────────────────────────────────────────
  static Color get success =>
      isGraphite ? const Color(0xFF9CD89A) : const Color(0xFF186036);
  static Color get warning =>
      isGraphite ? const Color(0xFFDDBA6D) : const Color(0xFF714D07);
  static Color get error =>
      isGraphite ? const Color(0xFFEBB2A3) : const Color(0xFF982B22);
  static Color get info => accentInk;

  // ── Зоны на карте (словарь цвета Ф2) ─────────────────────────────────────
  /// Моё — единственное лаймовое пятно на карте.
  static Color get zoneMine => lime;

  /// Чужое — тёплый.
  static Color get zoneEnemy => warm;

  /// Спорное/решается — teal.
  static Color get zoneContested => teal;

  static Color get zoneNeutral =>
      isGraphite ? const Color(0xFF454D46) : const Color(0xFFD6D3C6);
  static Color get zoneFading =>
      isGraphite ? const Color(0xFF39413A) : const Color(0xFFC9C6B8);

  // ── Ночная поверхность (историческое имя; теперь это и есть графит Ф8) ───
  static Color get nightBg => const Color(0xFF20252B);
  static Color get nightPaper => const Color(0xFF2A302C);
  static Color get nightInk => const Color(0xFFEFF1EA);
  static Color get nightMuted => const Color(0xFFB9C1BB);
  static Color get nightLine => const Color(0xFF3A423C);

  // ── Переходные псевдонимы ─────────────────────────────────────────────────
  // Имена прежних тем; на них завязано ~700 мест в экранах. Все указывают на
  // новые токены, чтобы оба интерьера включались без правки каждого экрана.
  static Color get electricBlue => accentInk;
  static Color get accentBlue => accentInk;
  static Color get iceWhite => soft;
  static Color get bgDark => bg;
  static Color get bgSurface => paper;
  static Color get bgCard => paper;
  static Color get bgElevated => panel;
  static Color get separator => line;
  static Color get glass => glassPaper;
  static Color get textPrimary => ink;
  static Color get textSecondary => muted;
  static Color get textTertiary => faint;
  static Color get textDisabled => disabled;
  static Color get hexNeutral => zoneNeutral;
  static Color get hexOwned => zoneMine;
  static Color get hexEnemy => zoneEnemy;
  static Color get hexContested => zoneContested;
  static Color get hexFading => zoneFading;
  static Color get gradientStart => teal;
  static Color get gradientEnd => const Color(0xFF1F4B44);
}
