import 'dart:ui' show Color;

/// Каталог наград «Штамп МАТА» (утверждено 01.09.2026, docs/design/medals/).
///
/// 44 медали: один шестигранный штамп, кант держит категорию, металл — ранг,
/// эмблема — награду. Ассеты выгружены из эталона попиксельно
/// (`assets/medals/id.webp` + `reverse_металл.webp`), сервер хранит только
/// состояние (GET /v1/me/medals) — имена и правила живут здесь.
enum MedalCat { rhythm, territory, distance, season, limited }

enum MedalTier { steel, bronze, silver, gold, iridium }

extension MedalCatX on MedalCat {
  String get title => switch (this) {
    MedalCat.rhythm => 'Ритм',
    MedalCat.territory => 'Территория',
    MedalCat.distance => 'Дистанция',
    MedalCat.season => 'Сезон и лига',
    MedalCat.limited => 'Лимитированные',
  };

  String get note => switch (this) {
    MedalCat.rhythm => 'Постоянные награды за режим. Приходят сами, если просто не бросать.',
    MedalCat.territory => 'То, чего нет ни у кого: захват и удержание кварталов на карте.',
    MedalCat.distance => 'Классика бега плюс награды, которые выдаёт только наш климат.',
    MedalCat.season => 'Итог сезона. Дивизион чеканится в металле — ранг виден без подписи.',
    MedalCat.limited => 'Один день в году, повторно не выдаётся. Каждый год — новый чекан.',
  };
}

extension MedalTierX on MedalTier {
  String get title => switch (this) {
    MedalTier.steel => 'Сталь',
    MedalTier.bronze => 'Бронза',
    MedalTier.silver => 'Серебро',
    MedalTier.gold => 'Золото',
    MedalTier.iridium => 'Иридий',
  };

  /// Металл (hi/mid/lo) — для гравировки реверса и акцентов. Цвета — из
  /// эталона METALS, не из темы: металл не зависит от свет/графит.
  (Color, Color, Color) get metal => switch (this) {
    MedalTier.steel => (const Color(0xFFE2E9ED), const Color(0xFF93A0AA), const Color(0xFF5F6C77)),
    MedalTier.bronze => (const Color(0xFFFFDFB2), const Color(0xFFD8894A), const Color(0xFF9C5A1E)),
    MedalTier.silver => (const Color(0xFFFFFFFF), const Color(0xFFCBD8E2), const Color(0xFF93A3B1)),
    MedalTier.gold => (const Color(0xFFFFF6CF), const Color(0xFFF0BE3C), const Color(0xFFB37C14)),
    MedalTier.iridium => (const Color(0xFFA8B7C4), const Color(0xFF39454F), const Color(0xFF171D23)),
  };
}

class MedalDef {
  final String id;
  final String name;

  /// Требование выдачи — строка из эталона, показывается под медалью.
  final String rq;
  final MedalCat cat;
  final MedalTier tier;

  /// Почему медаль пока «спит» (сервер не умеет её судить). null = живая.
  final String? waitNote;

  const MedalDef(this.id, this.name, this.rq, this.cat, this.tier, {this.waitNote});

  String get asset => 'assets/medals/$id.webp';

  String get reverseAsset => 'assets/medals/reverse_${tier.name}.webp';
}

/// Порядок = порядок в эталоне (docs/design/medals/shtamp-mata.html, SERIES).
const kMedals = <MedalDef>[
  // ── Ритм ──────────────────────────────────────────────────────────────────
  MedalDef('r_goal_first', 'Первая цель', 'Дневная цель закрыта впервые',
      MedalCat.rhythm, MedalTier.steel,
      waitNote: 'Появится вместе с дневной целью на сервере'),
  MedalDef('r_week_perfect', 'Идеальная неделя', 'Семь дней подряд без пропуска',
      MedalCat.rhythm, MedalTier.bronze),
  MedalDef('r_month_perfect', 'Идеальный месяц', 'Все дни календарного месяца',
      MedalCat.rhythm, MedalTier.silver),
  MedalDef('r_year_perfect', 'Идеальный год', '365 дней без единого пропуска',
      MedalCat.rhythm, MedalTier.gold),
  MedalDef('r_goal_x2', 'Цель ×2', 'Двойная норма за день',
      MedalCat.rhythm, MedalTier.bronze,
      waitNote: 'Появится вместе с дневной целью на сервере'),
  MedalDef('r_goal_x3', 'Цель ×3', 'Тройная норма за день',
      MedalCat.rhythm, MedalTier.silver,
      waitNote: 'Появится вместе с дневной целью на сервере'),
  MedalDef('r_goal_x5', 'Цель ×5', 'Пятикратная норма за день',
      MedalCat.rhythm, MedalTier.gold,
      waitNote: 'Появится вместе с дневной целью на сервере'),
  MedalDef('r_streak_7', 'Серия 7', 'Рекорд серии — неделя',
      MedalCat.rhythm, MedalTier.steel),
  MedalDef('r_streak_30', 'Серия 30', 'Рекорд серии — месяц',
      MedalCat.rhythm, MedalTier.silver),
  MedalDef('r_streak_100', 'Серия 100', 'Рекорд серии — сто дней',
      MedalCat.rhythm, MedalTier.gold),
  MedalDef('r_streak_365', 'Серия 365', 'Рекорд серии — год',
      MedalCat.rhythm, MedalTier.iridium),

  // ── Территория ────────────────────────────────────────────────────────────
  MedalDef('t_first_zone', 'Первый квартал', 'Первая захваченная зона',
      MedalCat.territory, MedalTier.steel),
  MedalDef('t_zones_10', '10 кварталов', 'Десять зон за всё время',
      MedalCat.territory, MedalTier.bronze),
  MedalDef('t_zones_50', '50 кварталов', 'Пятьдесят зон',
      MedalCat.territory, MedalTier.silver),
  MedalDef('t_zones_100', '100 кварталов', 'Сотня зон',
      MedalCat.territory, MedalTier.gold),
  MedalDef('t_district', 'Весь район', 'Все зоны района одновременно',
      MedalCat.territory, MedalTier.iridium,
      waitNote: 'Появится, когда разметим районы города'),
  MedalDef('t_defense_7', 'Оборона', 'Зона удержана семь дней',
      MedalCat.territory, MedalTier.bronze),
  MedalDef('t_intercept', 'Перехват', 'Спорная зона отбита у соперника',
      MedalCat.territory, MedalTier.silver),
  MedalDef('t_night_capture', 'Ночной захват', 'Зона взята между 00:00 и 05:00',
      MedalCat.territory, MedalTier.steel),
  MedalDef('t_pioneer', 'Первопроходец', 'Зона, которую не брал никто',
      MedalCat.territory, MedalTier.gold,
      waitNote: 'Появится вместе с журналом истории зон'),

  // ── Дистанция ─────────────────────────────────────────────────────────────
  MedalDef('d_first_run', 'Первый бег', 'Первая пробежка в приложении',
      MedalCat.distance, MedalTier.steel),
  MedalDef('d_run_5k', '5 км', 'Пять километров без остановки',
      MedalCat.distance, MedalTier.bronze),
  MedalDef('d_run_10k', '10 км', 'Десять километров',
      MedalCat.distance, MedalTier.bronze),
  MedalDef('d_half_marathon', 'Полумарафон', '21,1 км за одну пробежку',
      MedalCat.distance, MedalTier.silver),
  MedalDef('d_marathon', 'Марафон', '42,2 км за одну пробежку',
      MedalCat.distance, MedalTier.gold),
  MedalDef('d_month_100', '100 за месяц', 'Сто километров за календарный месяц',
      MedalCat.distance, MedalTier.silver),
  MedalDef('d_total_1000', '1000 км', 'Тысяча километров за всё время',
      MedalCat.distance, MedalTier.iridium),
  MedalDef('d_dawn', 'Рассвет', 'Пробежка начата до 07:00',
      MedalCat.distance, MedalTier.bronze),
  MedalDef('d_midnight', 'Полночь', 'Пробежка начата после 23:00',
      MedalCat.distance, MedalTier.silver),
  MedalDef('d_frost_40', 'Мороз −40', 'Пробежка при −40 °C и ниже',
      MedalCat.distance, MedalTier.iridium,
      waitNote: 'Появится, когда начнём записывать погоду пробежки'),
  MedalDef('d_workouts_100', '100 тренировок', 'Сто тренировок любого типа',
      MedalCat.distance, MedalTier.gold),

  // ── Сезон и лига ──────────────────────────────────────────────────────────
  MedalDef('s_season_closed', 'Сезон закрыт', 'Сезон пройден до конца',
      MedalCat.season, MedalTier.steel),
  MedalDef('s_div_bronze', 'Дивизион «Бронза»', 'Финиш сезона в бронзе',
      MedalCat.season, MedalTier.bronze,
      waitNote: 'Ждёт решения: как 7 уровней Лиги лягут в 4 ранга'),
  MedalDef('s_div_silver', 'Дивизион «Серебро»', 'Финиш сезона в серебре',
      MedalCat.season, MedalTier.silver,
      waitNote: 'Ждёт решения: как 7 уровней Лиги лягут в 4 ранга'),
  MedalDef('s_div_gold', 'Дивизион «Золото»', 'Финиш сезона в золоте',
      MedalCat.season, MedalTier.gold,
      waitNote: 'Ждёт решения: как 7 уровней Лиги лягут в 4 ранга'),
  MedalDef('s_div_elite', 'Дивизион «Элита»', 'Высший дивизион сезона',
      MedalCat.season, MedalTier.iridium,
      waitNote: 'Ждёт решения: как 7 уровней Лиги лягут в 4 ранга'),
  MedalDef('s_champion', 'Чемпион сезона', 'Первое место в дивизионе',
      MedalCat.season, MedalTier.iridium),
  MedalDef('s_club_cup', 'Клубный кубок', 'Клуб взял сезон',
      MedalCat.season, MedalTier.gold,
      waitNote: 'Появится вместе с клубным сезоном'),

  // ── Лимитированные ────────────────────────────────────────────────────────
  MedalDef('l_ny_2026', 'Новый год', '31 декабря или 1 января — любая пробежка',
      MedalCat.limited, MedalTier.silver),
  MedalDef('l_pobeda_2026', 'День Победы', '9 мая, от 9 километров',
      MedalCat.limited, MedalTier.gold),
  MedalDef('l_ysyakh_2026', 'Ысыах', 'Пробежка в дни Ысыаха',
      MedalCat.limited, MedalTier.bronze),
  MedalDef('l_city_2026', 'День города', 'Пробежка в день города — чекан твоего города',
      MedalCat.limited, MedalTier.silver,
      waitNote: 'Появится, когда начнём определять город пробежки'),
  MedalDef('l_eco_2026', 'Экодень', '22 апреля, тренировка на улице',
      MedalCat.limited, MedalTier.iridium),
  MedalDef('l_race_2026', 'Забег МАТА', 'Финиш официального забега МАТА',
      MedalCat.limited, MedalTier.gold,
      waitNote: 'Появится с первым официальным забегом МАТА'),
];

MedalDef medalById(String id) => kMedals.firstWhere((m) => m.id == id);
