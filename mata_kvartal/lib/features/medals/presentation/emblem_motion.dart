import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../data/medals_provider.dart';
import 'medal_widgets.dart';

/// Помедальные анимации эмблем (правило эталона D-64: у КАЖДОЙ медали своя
/// анимация самой эмблемы, общий крутящийся фон запрещён как «ленивый»).
///
/// Механика — послойный экспорт: конвейер выгружает из эталона базу медали
/// (без анимируемых частей) и каждую живую часть отдельным прозрачным WebP
/// на полном холсте 768 (слои совпадают по позиции сами). Таймлайны сняты
/// с SMIL/CSS эталона и переведены в ключи ниже; координаты — в системе
/// viewBox эталона (116 единиц, начало в центре медали), масштаб эмблемы
/// (esc/ey из renderMedal) уже вмножен в значения.
///
/// Медаль без спецификации рисуется статичным ассетом — конвейер идёт
/// партиями, деградация всегда мягкая. Пульсаций и ударных волн нет (D-46).

/// Ключ таймлайна: момент [t] (0..1 периода) и поза слоя в этот момент.
class EmblemKey {
  final double t;
  final double dx, dy; // сдвиг, единицы viewBox (116 на всю медаль)
  final double rot; // градусы, по часовой (экранные координаты SVG)
  final double opacity;
  final double scale; // вокруг pivot (глинты, галочка цели, сноп фейерверка)
  final double skewY; // градусы (ткань финишного флага)

  const EmblemKey(
    this.t, {
    this.dx = 0,
    this.dy = 0,
    this.rot = 0,
    this.opacity = 1,
    this.scale = 1,
    this.skewY = 0,
  });
}

/// Живой слой эмблемы: ассет + цикл ключей.
class EmblemLayer {
  final String part; // суффикс файла: assets/medals/anim/<id>__<part>.webp
  final int periodMs;
  final int delayMs; // фазовый сдвиг цикла (лесенки полос, искры)
  final bool alternate; // туда-обратно (CSS animation-direction: alternate)
  final Curve curve; // кривая МЕЖДУ соседними ключами
  final List<EmblemKey> keys;
  final Offset pivot; // центр вращения, единицы viewBox от центра медали
  final Rect? clip; // окно слоя (восход за горизонтом), те же единицы

  const EmblemLayer(
    this.part, {
    required this.periodMs,
    this.delayMs = 0,
    this.alternate = false,
    this.curve = Curves.linear,
    required this.keys,
    this.pivot = Offset.zero,
    this.clip,
  });
}

/// Порядок частей медали снизу вверх — ровно документный порядок эталона:
/// статические сегменты (seg*) режутся конвейером вокруг живых слоёв, чтобы
/// z-порядок совпал (лучи ордена лежат ПОД звездой, плашка — ПОВЕРХ щита).
const Map<String, List<String>> emblemParts = {
  's_champion': ['seg0', 'rays', 'seg1'],
  'd_dawn': ['seg0', 'sun', 'seg1', 'refl', 'seg2'],
  't_defense_7': ['seg0', 'body', 'arr1', 'arr2', 'arr3', 'seg4'],
  'd_first_run': ['seg0', 'st1', 'st2', 'st3', 'runner', 'sparks', 'seg5'],
  // Партия 2 — Ритм + Территория (порядок из конвейера, документный).
  'r_goal_first': ['seg0', 'check', 'seg1'],
  'r_week_perfect': [
    'seg0', 'day0', 'seg1', 'day1', 'seg2', 'day2', 'seg3', 'day3', 'seg4',
    'day4', 'seg5', 'day5', 'seg6', 'day6', 'seg7', 'seven', 'seg8',
  ],
  'r_month_perfect': [
    'seg0', 'row0', 'seg1', 'row1', 'seg2', 'row2', 'seg3', 'row3', 'seg4',
  ],
  'r_year_perfect': ['seg0', 'glint', 'seg1'],
  'r_goal_x2': ['seg0', 'chev', 'fl1', 'fl2', 'fl3', 'seg4'],
  'r_goal_x3': ['seg0', 'chev', 'fl1', 'fl2', 'fl3', 'seg4'],
  'r_goal_x5': ['seg0', 'chev', 'fl1', 'fl2', 'fl3', 'seg4'],
  'r_streak_7': ['seg0', 'comet', 'seg1'],
  'r_streak_30': ['seg0', 'comet', 'seg1'],
  'r_streak_100': ['seg0', 'comet', 'seg1'],
  'r_streak_365': ['seg0', 'comet', 'seg1'],
  't_first_zone': [
    'seg0', 'link1', 'seg1', 'hexfl1', 'link2', 'seg3', 'hexfl2', 'link3',
    'seg5', 'hexfl3', 'seg6', 'pennA', 'pennB', 'seg7',
  ],
  't_zones_10': [
    'seg0', 'link1', 'seg1', 'hexfl1', 'link2', 'seg3', 'hexfl2', 'link3',
    'seg5', 'hexfl3', 'seg6', 'pennA', 'pennB', 'seg7',
  ],
  't_zones_50': [
    'seg0', 'link1', 'seg1', 'hexfl1', 'link2', 'seg3', 'hexfl2', 'link3',
    'seg5', 'hexfl3', 'seg6', 'pennA', 'pennB', 'seg7',
  ],
  't_zones_100': [
    'seg0', 'link1', 'seg1', 'hexfl1', 'link2', 'seg3', 'hexfl2', 'link3',
    'seg5', 'hexfl3', 'seg6', 'pennA', 'pennB', 'seg7',
  ],
  't_district': ['seg0', 'mlines', 'seg1'],
  't_intercept': ['seg0', 'turn', 'seg1'],
  't_night_capture': [
    'seg0', 'wrap', 'tw1', 'tw2', 'tw3', 'meteor', 'seg5', 'window', 'seg6',
  ],
  't_pioneer': [
    'seg0', 'pennA', 'pennB', 'seg1', 'step1', 'step2', 'step3', 'step4',
    'step5', 'gl1', 'gl2', 'seg8',
  ],
  // Партия 3 — Дистанция + Сезон.
  'd_run_5k': ['seg0', 'flow', 'seg1', 'hflag', 'seg2'],
  'd_run_10k': ['seg0', 'flow', 'seg1', 'hflag', 'seg2'],
  'd_half_marathon': ['seg0', 'flow', 'seg1', 'hflag', 'seg2'],
  'd_marathon': ['seg0', 'flow', 'seg1', 'hflag', 'seg2'],
  'd_month_100': ['seg0', 'flow', 'seg1', 'hflag', 'seg2'],
  'd_total_1000': ['seg0', 'flow', 'seg1', 'hflag', 'seg2'],
  'd_midnight': [
    'seg0', 'wrap', 'tw1', 'tw2', 'tw3', 'meteor', 'seg5', 'window', 'seg6',
  ],
  'd_frost_40': ['seg0', 'spin', 'seg1'],
  'd_workouts_100': [
    'seg0', 'st1', 'st2', 'st3', 'runner', 'sparks', 'seg5',
  ],
  's_season_closed': ['seg0', 'cloth', 'seg1'],
  's_div_bronze': ['seg0', 'wing1', 'wing2', 'gem', 'seg3', 'gl1', 'seg4'],
  's_div_silver': ['seg0', 'wing1', 'wing2', 'gem', 'seg3', 'gl1', 'seg4'],
  's_div_gold': ['seg0', 'wing1', 'wing2', 'gem', 'seg3', 'gl1', 'seg4'],
  's_div_elite': ['seg0', 'wing1', 'wing2', 'gem', 'seg3', 'gl1', 'seg4'],
  's_club_cup': [
    'seg0', 'shine', 'rib1', 'rib2', 'conf1', 'conf2', 'conf3', 'conf4',
    'conf5', 'conf6', 'conf7', 'conf8', 'gl1', 'gl2', 'seg13',
  ],
  // Партия 4 — Лимитированные (все 44 медали живые).
  'l_ny_2026': [
    'seg0', 'li1', 'li2', 'li3', 'li4', 'li5', 'seg5', 'snow1', 'snow2', 'seg7',
  ],
  'l_pobeda_2026': [
    'seg0', 'rays', 'seg1', 'gl1', 'gl2', 'seg3', 'tail1', 'tail2',
    'w1A', 'w1B', 'w2A', 'w2B', 'w3A', 'w3B', 'seg8',
  ],
  'l_ysyakh_2026': ['seg0', 'sunrays', 'seg1', 'dance', 'seg2'],
  'l_city_2026': [
    'seg0', 'w1', 'w2', 'w3', 'w4', 'w5', 'w6', 'seg6',
    'fw1a', 'fw1b', 'fw2a', 'fw2b', 'seg10',
  ],
  'l_eco_2026': ['seg0', 'sway', 'seg1'],
  'l_race_2026': ['seg0', 'sway', 'seg1'],
};

/// Таймлайны. Значения = эталон × масштаб эмблемы (esc/ey из renderMedal).
final Map<String, List<EmblemLayer>> emblemMotion = {
  // Чемпион сезона: лучи ордена делают полный оборот за 26 с (SMIL rotate).
  's_champion': [
    EmblemLayer(
      'rays',
      periodMs: 26000,
      keys: [EmblemKey(0, rot: 0), EmblemKey(1, rot: 360)],
    ),
  ],

  // Рассвет: солнце с лучами держится, садится за горизонт и всходит снова
  // (SMIL translate 10 с, сплайны ~easeInOut); дорожка света гаснет в такт.
  'd_dawn': [
    EmblemLayer(
      'sun',
      periodMs: 10000,
      curve: Curves.easeInOut,
      clip: Rect.fromLTWH(-21.84, -20.88, 43.68, 27.04),
      keys: [
        EmblemKey(0),
        EmblemKey(.5),
        EmblemKey(.62, dy: 8.32),
        EmblemKey(.7, dy: 8.32),
        EmblemKey(.88),
        EmblemKey(1),
      ],
    ),
    EmblemLayer(
      'refl',
      periodMs: 10000,
      keys: [
        EmblemKey(0),
        EmblemKey(.52),
        EmblemKey(.64, opacity: 0),
        EmblemKey(.82, opacity: 0),
        EmblemKey(.96),
        EmblemKey(1),
      ],
    ),
  ],

  // Оборона: три стрелы прилетают с разных сторон, впиваются, торчат и тают;
  // щит вздрагивает на каждый удар (CSS shieldHit: 7/23.5/40.5 % цикла 7 с).
  't_defense_7': [
    EmblemLayer(
      'body',
      periodMs: 7000,
      curve: Curves.easeOut,
      pivot: Offset(0, -8),
      keys: [
        EmblemKey(0),
        EmblemKey(.055),
        EmblemKey(.07, dx: -0.99, rot: -1.6),
        EmblemKey(.11),
        EmblemKey(.22),
        EmblemKey(.235, dx: 0.91, rot: 1.3),
        EmblemKey(.275),
        EmblemKey(.39),
        EmblemKey(.405, dx: -0.80, rot: -1.1),
        EmblemKey(.445),
        EmblemKey(1),
      ],
    ),
    EmblemLayer(
      'arr1', // translate(17,-15) rotate(-14): полёт вдоль местной оси X
      periodMs: 7000,
      keys: [
        EmblemKey(0, dx: 13.27, dy: -3.31, opacity: 0),
        EmblemKey(.028, dx: 13.27, dy: -3.31, opacity: 0),
        EmblemKey(.06, opacity: 1),
        EmblemKey(.68, opacity: 1),
        EmblemKey(.73, opacity: 0),
        EmblemKey(1, opacity: 0),
      ],
    ),
    EmblemLayer(
      'arr2', // translate(-17,-3) scale(-1,1) rotate(-9)
      periodMs: 7000,
      keys: [
        EmblemKey(0, dx: -13.51, dy: -2.14, opacity: 0),
        EmblemKey(.2, dx: -13.51, dy: -2.14, opacity: 0),
        EmblemKey(.232, opacity: 1),
        EmblemKey(.68, opacity: 1),
        EmblemKey(.73, opacity: 0),
        EmblemKey(1, opacity: 0),
      ],
    ),
    EmblemLayer(
      'arr3', // translate(14,12) rotate(9)
      periodMs: 7000,
      keys: [
        EmblemKey(0, dx: 13.51, dy: 2.14, opacity: 0),
        EmblemKey(.373, dx: 13.51, dy: 2.14, opacity: 0),
        EmblemKey(.405, opacity: 1),
        EmblemKey(.68, opacity: 1),
        EmblemKey(.73, opacity: 0),
        EmblemKey(1, opacity: 0),
      ],
    ),
  ],

  // Первый бег: бегун в ритме шага, полосы скорости пробегают, искры
  // из-под ноги (CSS runBob/streakOut + SMIL искр).
  'd_first_run': [
    EmblemLayer(
      'runner',
      periodMs: 850,
      alternate: true,
      curve: Curves.easeInOut,
      pivot: Offset(4.16, 2),
      keys: [
        EmblemKey(0, dy: -0.62, rot: -1.4),
        EmblemKey(1, dy: 0.62, rot: 1.2),
      ],
    ),
    EmblemLayer(
      'st1',
      periodMs: 1300,
      keys: [
        EmblemKey(0, dx: 3.12, opacity: 0),
        EmblemKey(.3, dx: 0.78, opacity: .75),
        EmblemKey(1, dx: -4.68, opacity: 0),
      ],
    ),
    EmblemLayer(
      'st2',
      periodMs: 1300,
      delayMs: 250,
      keys: [
        EmblemKey(0, dx: 3.12, opacity: 0),
        EmblemKey(.3, dx: 0.78, opacity: .75),
        EmblemKey(1, dx: -4.68, opacity: 0),
      ],
    ),
    EmblemLayer(
      'st3',
      periodMs: 1300,
      delayMs: 500,
      keys: [
        EmblemKey(0, dx: 3.12, opacity: 0),
        EmblemKey(.3, dx: 0.78, opacity: .75),
        EmblemKey(1, dx: -4.68, opacity: 0),
      ],
    ),
    EmblemLayer(
      'sparks',
      periodMs: 1300,
      keys: [
        EmblemKey(0, opacity: 0),
        EmblemKey(.5, dx: -2.86, dy: 0.52, opacity: .8),
        EmblemKey(1, dx: -5.72, dy: 1.04, opacity: 0),
      ],
    ),
  ],

  // ── Партия 2: Ритм ────────────────────────────────────────────────────
  'r_goal_first': _ring(),
  'r_week_perfect': _week(),
  'r_month_perfect': _month(),
  'r_year_perfect': _year(),
  'r_goal_x2': _mult(),
  'r_goal_x3': _mult(),
  'r_goal_x5': _mult(),
  'r_streak_7': _streak(),
  'r_streak_30': _streak(),
  'r_streak_100': _streak(),
  'r_streak_365': _streak(),

  // ── Партия 2: Территория ──────────────────────────────────────────────
  't_first_zone': _hexcap(),
  't_zones_10': _hexcap(),
  't_zones_50': _hexcap(),
  't_zones_100': _hexcap(),
  't_district': _hexgrid(),
  't_intercept': _swap(),
  't_night_capture': _moon(.50),
  't_pioneer': _flag(),

  // ── Партия 3: Дистанция ───────────────────────────────────────────────
  'd_run_5k': _road(),
  'd_run_10k': _road(),
  'd_half_marathon': _road(),
  'd_marathon': _road(),
  'd_month_100': _road(),
  'd_total_1000': _road(),
  'd_midnight': _moon(.52),
  'd_frost_40': _snowSpin(),
  'd_workouts_100': _run(.38, -8),

  // ── Партия 3: Сезон и лига ────────────────────────────────────────────
  's_season_closed': _finish(),
  's_div_bronze': _div(.52),
  's_div_silver': _div(.52),
  's_div_gold': _div(.52),
  's_div_elite': _div(.50),
  's_club_cup': _cup(),

  // ── Партия 4: Лимитированные ──────────────────────────────────────────
  'l_ny_2026': _fir(),
  'l_pobeda_2026': _star5(),
  'l_ysyakh_2026': _serge(),
  'l_city_2026': _city(),
  'l_eco_2026': _leafSway(),
  'l_race_2026': _mataSway(),
};

// ── Глифовые таймлайны партии 2 (медали одного глифа делят ключи; ─────────
// ассеты у каждой свои — металл ранга красит эмблему).

/// Первая цель: галочка исчезает вместе с кольцом и вбивается заново
/// (SMIL scale 8 с; перерисовка кольца — dash, в статике след полный).
List<EmblemLayer> _ring() => const [
  EmblemLayer('check', periodMs: 8000, pivot: Offset(0, 2), keys: [
    EmblemKey(0),
    EmblemKey(.52),
    EmblemKey(.56, scale: 0, opacity: 0),
    EmblemKey(.9, scale: 0, opacity: 0),
    EmblemKey(.95, scale: 1.3),
    EmblemKey(1),
  ]),
];

/// Идеальная неделя: дни гаснут и зажигаются лесенкой, «7» дышит.
List<EmblemLayer> _week() => [
  for (var i = 0; i < 7; i++)
    EmblemLayer('day$i', periodMs: 8000, keys: [
      const EmblemKey(0),
      const EmblemKey(.36),
      const EmblemKey(.4, opacity: 0),
      EmblemKey(.45 + i * .05, opacity: 0),
      EmblemKey(.48 + i * .05),
      const EmblemKey(1),
    ]),
  const EmblemLayer('seven', periodMs: 5000, keys: [
    EmblemKey(0, opacity: .85),
    EmblemKey(.5),
    EmblemKey(1, opacity: .85),
  ]),
];

/// Идеальный месяц: календарь гаснет и заполняется волной по рядам.
List<EmblemLayer> _month() => [
  for (var r = 0; r < 4; r++)
    EmblemLayer('row$r', periodMs: 9000, keys: [
      const EmblemKey(0),
      const EmblemKey(.34),
      const EmblemKey(.38, opacity: 0),
      EmblemKey(.44 + r * .09, opacity: 0),
      EmblemKey(.48 + r * .09),
      const EmblemKey(1),
    ]),
];

/// Идеальный год: блик обходит кольцо месяцев за 14 с.
List<EmblemLayer> _year() => const [
  EmblemLayer('glint', periodMs: 14000, pivot: Offset(0, 2), keys: [
    EmblemKey(0, rot: 0),
    EmblemKey(1, rot: 360),
  ]),
];

/// Цель ×N: шевроны дышат вверх-вниз, вспышки пробегают снизу вверх.
List<EmblemLayer> _mult() => const [
  EmblemLayer('chev', periodMs: 4200, keys: [
    EmblemKey(0, dy: .57),
    EmblemKey(.5, dy: -.57),
    EmblemKey(1, dy: .57),
  ]),
  EmblemLayer('fl1', periodMs: 3800, keys: [
    EmblemKey(0, opacity: 0),
    EmblemKey(.12, opacity: 0),
    EmblemKey(.19, opacity: .9),
    EmblemKey(.32, opacity: 0),
    EmblemKey(1, opacity: 0),
  ]),
  EmblemLayer('fl2', periodMs: 3800, keys: [
    EmblemKey(0, opacity: 0),
    EmblemKey(.24, opacity: 0),
    EmblemKey(.31, opacity: .9),
    EmblemKey(.44, opacity: 0),
    EmblemKey(1, opacity: 0),
  ]),
  EmblemLayer('fl3', periodMs: 3800, keys: [
    EmblemKey(0, opacity: 0),
    EmblemKey(.36, opacity: 0),
    EmblemKey(.43, opacity: .9),
    EmblemKey(.56, opacity: 0),
    EmblemKey(1, opacity: 0),
  ]),
];

/// Маршрут серии, снятый конвейером с кривой эталона: [s, x, y, угол°].
/// s — доля длины пути, координаты локальные (× esc .38 при переводе).
const List<List<double>> _streakPath = [
  [0, -30, 20, 22.4], [.042, -26.99, 20.92, 7.9], [.083, -23.86, 20.84, -15.9],
  [.125, -21.06, 19.45, -38.9], [.167, -18.83, 17.24, -50.7],
  [.208, -16.92, 14.73, -54.1], [.25, -15.05, 12.19, -52],
  [.292, -13.9, 8, -44.7], [.333, -10.58, 7.79, -32.2],
  [.375, -7.75, 6.43, -16.4], [.417, -4.66, 5.89, -1.6],
  [.458, -1.51, 6.04, 3.2], [.5, 1.62, 5.86, -14.1],
  [.542, 4.49, 4.6, -36.8], [.583, 6.74, 2.41, -52.5],
  [.625, 8.51, -.19, -58.5], [.667, 10.14, -2.89, -58.5],
  [.708, 11.85, -5.54, -54.9], [.75, 13.76, -8.04, -49],
  [.792, 15.95, -10.31, -41.8], [.833, 18.41, -12.28, -34.4],
  [.875, 21.1, -13.91, -27.3], [.917, 23.96, -15.23, -21.1],
  [.958, 26.94, -16.24, -15.8], [1, 30, -17, 0],
];

EmblemKey _cometAt(double t, double s) {
  const esc = .38;
  var row = _streakPath.last;
  for (var i = 1; i < _streakPath.length; i++) {
    if (s <= _streakPath[i][0]) {
      final a = _streakPath[i - 1], b = _streakPath[i];
      final f = (s - a[0]) / (b[0] - a[0]);
      row = [
        s,
        a[1] + (b[1] - a[1]) * f,
        a[2] + (b[2] - a[2]) * f,
        a[3] + (b[3] - a[3]) * f,
      ];
      break;
    }
  }
  return EmblemKey(t, dx: row[1] * esc, dy: row[2] * esc, rot: row[3]);
}

/// Серия: комета стоит на финише, отматывается к старту и пробегает
/// маршрут заново (SMIL animateMotion; перерисовку следа dash-анимацией
/// послойный экспорт не переносит — след живёт полным, это компромисс).
List<EmblemLayer> _streak() => [
  EmblemLayer('comet', periodMs: 7000, pivot: const Offset(0, -8), keys: [
    _cometAt(0, 1),
    _cometAt(.3, 1),
    for (var k = 1; k <= 6; k++) _cometAt(.3 + .03 * k / 6, 1 - k / 6),
    _cometAt(.37, 0),
    for (var k = 1; k <= 24; k++) _cometAt(.37 + .58 * k / 24, k / 24),
    _cometAt(1, 1),
  ]),
];

/// Квартал взят: связи с соседями теплятся, соседние зоны вспыхивают,
/// вымпел полощется (морф двумя кадрами-кроссфейдом).
List<EmblemLayer> _hexcap() => [
  for (var i = 0; i < 3; i++)
    EmblemLayer('link${i + 1}', periodMs: 4200, delayMs: i * 1400, keys: const [
      EmblemKey(0, opacity: .3),
      EmblemKey(.5, opacity: .65),
      EmblemKey(1, opacity: .3),
    ]),
  for (var i = 0; i < 3; i++)
    EmblemLayer('hexfl${i + 1}', periodMs: 4200, delayMs: 400 + i * 1400,
        keys: const [
      EmblemKey(0, opacity: 0),
      EmblemKey(.5, opacity: .35),
      EmblemKey(1, opacity: 0),
    ]),
  const EmblemLayer('pennA', periodMs: 2200, curve: Curves.easeInOut, keys: [
    EmblemKey(0),
    EmblemKey(.5, opacity: 0),
    EmblemKey(1),
  ]),
  const EmblemLayer('pennB', periodMs: 2200, curve: Curves.easeInOut, keys: [
    EmblemKey(0, opacity: 0),
    EmblemKey(.5),
    EmblemKey(1, opacity: 0),
  ]),
];

/// Весь район: связи созвездия теплятся (CSS mlineGlow).
List<EmblemLayer> _hexgrid() => const [
  EmblemLayer('mlines', periodMs: 3800, alternate: true,
      curve: Curves.easeInOut, keys: [
    EmblemKey(0, opacity: .16),
    EmblemKey(1, opacity: .42),
  ]),
];

/// Перехват: эмблема делает один резкий оборот и замирает (CSS swapTurn).
List<EmblemLayer> _swap() => const [
  EmblemLayer('turn', periodMs: 5000, curve: Cubic(.5, 0, .15, 1),
      pivot: Offset(0, 1), keys: [
    EmblemKey(0, rot: 0),
    EmblemKey(.16, rot: 360),
    EmblemKey(1, rot: 360),
  ]),
];

/// Ночь: месяц дрейфует, звёзды мерцают вразнобой, раз в цикл чиркает
/// метеор, одно окно в спящем городе гаснет и зажигается.
List<EmblemLayer> _moon(double esc) => [
  EmblemLayer('wrap', periodMs: 6000, alternate: true,
      curve: Curves.easeInOut, keys: [
    EmblemKey(0, dy: -1.6 * esc),
    EmblemKey(1, dy: 1.6 * esc),
  ]),
  for (var i = 0; i < 3; i++)
    EmblemLayer('tw${i + 1}', periodMs: 4400, delayMs: i * 1400, keys: const [
      EmblemKey(0, opacity: .25),
      EmblemKey(.12, opacity: 1),
      EmblemKey(.24, opacity: .25),
      EmblemKey(1, opacity: .25),
    ]),
  EmblemLayer('meteor', periodMs: 9000, keys: [
    const EmblemKey(0, opacity: 0),
    const EmblemKey(.6, opacity: 0),
    EmblemKey(.64, dx: -8.73 * esc, dy: 6.18 * esc, opacity: .9),
    EmblemKey(.71, dx: -24 * esc, dy: 17 * esc, opacity: 0),
    EmblemKey(1, dx: -24 * esc, dy: 17 * esc, opacity: 0),
  ]),
  const EmblemLayer('window', periodMs: 9000, keys: [
    EmblemKey(0, opacity: .9),
    EmblemKey(.35, opacity: .9),
    EmblemKey(.42, opacity: .15),
    EmblemKey(.78, opacity: .15),
    EmblemKey(.86, opacity: .9),
    EmblemKey(1, opacity: .9),
  ]),
];

/// Первопроходец: вымпел полощется, следы проявляются шаг за шагом
/// к древку, глинты вспыхивают.
List<EmblemLayer> _flag() => [
  const EmblemLayer('pennA', periodMs: 2400, curve: Curves.easeInOut, keys: [
    EmblemKey(0),
    EmblemKey(.5, opacity: 0),
    EmblemKey(1),
  ]),
  const EmblemLayer('pennB', periodMs: 2400, curve: Curves.easeInOut, keys: [
    EmblemKey(0, opacity: 0),
    EmblemKey(.5),
    EmblemKey(1, opacity: 0),
  ]),
  for (var i = 0; i < 5; i++)
    EmblemLayer('step${i + 1}', periodMs: 8000, keys: [
      const EmblemKey(0, opacity: 0),
      EmblemKey(.08 + i * .09, opacity: 0),
      EmblemKey(.12 + i * .09, opacity: .5),
      const EmblemKey(.78, opacity: .5),
      const EmblemKey(.9, opacity: 0),
      const EmblemKey(1, opacity: 0),
    ]),
  const EmblemLayer('gl1', periodMs: 4600, delayMs: 1000,
      pivot: Offset(15.6, -12.77), keys: [
    EmblemKey(0, opacity: 0, scale: .4),
    EmblemKey(.06, opacity: .95, scale: 1),
    EmblemKey(.13, opacity: 0, scale: .5),
    EmblemKey(1, opacity: 0, scale: .4),
  ]),
  const EmblemLayer('gl2', periodMs: 4600, delayMs: 3200,
      pivot: Offset(-12.48, -17.34), keys: [
    EmblemKey(0, opacity: 0, scale: .4),
    EmblemKey(.06, opacity: .95, scale: 1),
    EmblemKey(.13, opacity: 0, scale: .5),
    EmblemKey(1, opacity: 0, scale: .4),
  ]),
];

// ── Глифовые таймлайны партии 3 ────────────────────────────────────────

/// Вспышка-глинт (CSS glint): проявляется с ростом и тает. Общий для
/// дивизионов, кубка и прочих искр.
EmblemLayer _glint(String part, Offset pivot, int delayMs) => EmblemLayer(
  part, periodMs: 4600, delayMs: delayMs, pivot: pivot, keys: const [
    EmblemKey(0, opacity: 0, scale: .4),
    EmblemKey(.06, opacity: .95, scale: 1),
    EmblemKey(.13, opacity: 0, scale: .5),
    EmblemKey(1, opacity: 0, scale: .4),
  ],
);

/// Дорога: разметка бежит к финишу внутри полотна, флажок на горизонте
/// машет (CSS roadFlow/hflagWave; esc .38, ey −8 — у всех road есть плашка).
List<EmblemLayer> _road() => const [
  EmblemLayer('flow', periodMs: 1500,
      clip: Rect.fromLTWH(-3.2, -18.26, 6.4, 23.5), keys: [
    EmblemKey(0),
    EmblemKey(1, dy: 4.94),
  ]),
  EmblemLayer('hflag', periodMs: 2200, alternate: true,
      curve: Curves.easeInOut, pivot: Offset(3.04, -21.68), keys: [
    EmblemKey(0, rot: -4),
    EmblemKey(1, rot: 4),
  ]),
];

/// Мороз −40: гранёная снежинка медленно вращается (CSS spinSlow, 40 с).
List<EmblemLayer> _snowSpin() => const [
  EmblemLayer('spin', periodMs: 40000, pivot: Offset(0, -8), keys: [
    EmblemKey(0, rot: 0),
    EmblemKey(1, rot: 360),
  ]),
];

/// Бегун (глиф run) в произвольном масштабе — пилотные ключи, приведённые
/// к esc/ey медали (у «100 тренировок» эмблема мельче из-за плашки).
List<EmblemLayer> _run(double esc, double ey) {
  final k = esc / .52; // пилотные значения сняты при esc .52
  return [
    EmblemLayer('runner', periodMs: 850, alternate: true,
        curve: Curves.easeInOut, pivot: Offset(8 * esc, ey), keys: [
      EmblemKey(0, dy: -1.2 * esc, rot: -1.4),
      EmblemKey(1, dy: 1.2 * esc, rot: 1.2),
    ]),
    for (var i = 0; i < 3; i++)
      EmblemLayer('st${i + 1}', periodMs: 1300, delayMs: i * 250, keys: [
        EmblemKey(0, dx: 3.12 * k, opacity: 0),
        EmblemKey(.3, dx: 0.78 * k, opacity: .75),
        EmblemKey(1, dx: -4.68 * k, opacity: 0),
      ]),
    EmblemLayer('sparks', periodMs: 1300, keys: [
      const EmblemKey(0, opacity: 0),
      EmblemKey(.5, dx: -5.5 * esc, dy: esc, opacity: .8),
      EmblemKey(1, dx: -11 * esc, dy: 2 * esc, opacity: 0),
    ]),
  ];
}

/// Сезон закрыт: клетчатая ткань полощется на древке (CSS clothSway).
List<EmblemLayer> _finish() => const [
  EmblemLayer('cloth', periodMs: 2000, alternate: true,
      curve: Curves.easeInOut, pivot: Offset(0.5, -11), keys: [
    EmblemKey(0, skewY: -1.8),
    EmblemKey(1, skewY: 1.8),
  ]),
];

/// Дивизион: крылья парят в противофазе зеркала, самоцвет дышит,
/// глинт вспыхивает (CSS wingSway/gemSway/glint).
List<EmblemLayer> _div(double esc) => [
  EmblemLayer('wing1', periodMs: 3600, alternate: true,
      curve: Curves.easeInOut, pivot: Offset(11 * esc, 2), keys: const [
    EmblemKey(0, rot: -2),
    EmblemKey(1, rot: 2),
  ]),
  EmblemLayer('wing2', periodMs: 3600, alternate: true,
      curve: Curves.easeInOut, pivot: Offset(-11 * esc, 2), keys: const [
    EmblemKey(0, rot: 2),
    EmblemKey(1, rot: -2),
  ]),
  const EmblemLayer('gem', periodMs: 5500, alternate: true,
      curve: Curves.easeInOut, pivot: Offset(0, 2), keys: [
    EmblemKey(0, rot: -3.5),
    EmblemKey(1, rot: 3.5),
  ]),
  _glint('gl1', Offset(6 * esc, 2 - 4.4 * esc), 1000),
];

/// Клубный кубок празднует: блик проходит по чаше, серпантин качается,
/// конфетти сыплется с собственным вращением, глинты вспыхивают.
List<EmblemLayer> _cup() {
  const esc = .52;
  // Конфетти из эталона: [x, y, dur мс, begin мс] — конец полёта (x∓7, 34).
  const conf = [
    [-27.0, -42.0, 3600, 0], [-14.0, -46.0, 4200, 1100],
    [7.0, -48.0, 3400, 2000], [22.0, -44.0, 4600, 600],
    [31.0, -42.0, 3800, 2800], [-33.0, -40.0, 4400, 1700],
    [13.0, -46.0, 3500, 3400], [-4.0, -50.0, 4000, 2400],
  ];
  EmblemKey confKey(double t, List<num> c, double o, double r) {
    final endX = c[0] > 0 ? c[0] - 7 : c[0] + 7;
    final x = c[0] + (endX - c[0]) * t;
    final y = c[1] + (34 - c[1]) * t;
    return EmblemKey(t, dx: x * esc, dy: y * esc, opacity: o, rot: r);
  }
  return [
    const EmblemLayer('shine', periodMs: 4200,
        clip: Rect.fromLTWH(-10.4, -14.12, 20.8, 22.9), keys: [
      EmblemKey(0, dx: -12.99, dy: -3.73, opacity: 0),
      EmblemKey(.12, dx: -1.0, dy: -.29, opacity: .55),
      EmblemKey(.26, dx: 12.99, dy: 3.73, opacity: 0),
      EmblemKey(1, dx: 12.99, dy: 3.73, opacity: 0),
    ]),
    const EmblemLayer('rib1', periodMs: 3800,
        curve: Curves.easeInOut, pivot: Offset(-15.6, -15.68), keys: [
      EmblemKey(0, rot: -4), EmblemKey(.5, rot: 4), EmblemKey(1, rot: -4),
    ]),
    const EmblemLayer('rib2', periodMs: 4400,
        curve: Curves.easeInOut, pivot: Offset(15.6, -14.12), keys: [
      EmblemKey(0, rot: 4), EmblemKey(.5, rot: -4), EmblemKey(1, rot: 4),
    ]),
    for (var i = 0; i < 8; i++)
      EmblemLayer('conf${i + 1}', periodMs: conf[i][2] as int,
          delayMs: conf[i][3] as int, pivot: const Offset(0, 2), keys: [
        confKey(0, conf[i], 0, 0),
        confKey(.08, conf[i], .95, 24),
        confKey(.82, conf[i], .95, 246),
        confKey(1, conf[i], 0, 300),
      ]),
    _glint('gl1', const Offset(-13, -6.27), 1000),
    _glint('gl2', const Offset(13, -3.56), 3200),
  ];
}

// ── Глифовые таймлайны партии 4 (Лимитированные; esc .38, ey −8/−10) ───

/// Новый год: гирлянда мигает вразнобой, за ёлкой падает снег.
List<EmblemLayer> _fir() => [
  for (final (i, d) in const [(0, 0), (1, 900), (2, 1600), (3, 400), (4, 2200)])
    EmblemLayer('li${i + 1}', periodMs: 2600, delayMs: d, keys: const [
      EmblemKey(0, opacity: .25),
      EmblemKey(.5, opacity: 1),
      EmblemKey(1, opacity: .25),
    ]),
  const EmblemLayer('snow1', periodMs: 7000, keys: [
    EmblemKey(0, dy: -2.66, opacity: 0),
    EmblemKey(.18, dy: -1.29, opacity: .75),
    EmblemKey(.78, dy: 3.27, opacity: .75),
    EmblemKey(1, dy: 4.94, opacity: 0),
  ]),
  const EmblemLayer('snow2', periodMs: 9500, delayMs: 2800, keys: [
    EmblemKey(0, dy: -3.8, opacity: 0),
    EmblemKey(.2, dy: -2.2, opacity: .6),
    EmblemKey(.8, dy: 2.58, opacity: .6),
    EmblemKey(1, dy: 4.18, opacity: 0),
  ]),
];

/// День Победы: сияние ордена вращается, искры вспыхивают на лучах,
/// георгиевская лента колышется (морф кроссфейдом), хвосты подрагивают.
List<EmblemLayer> _star5() => [
  const EmblemLayer('rays', periodMs: 34000, pivot: Offset(0, -10), keys: [
    EmblemKey(0, rot: 0),
    EmblemKey(1, rot: 360),
  ]),
  _glint('gl1', const Offset(0, -24.44), 1000),
  _glint('gl2', const Offset(13.68, -13.27), 3200),
  const EmblemLayer('tail1', periodMs: 4600, curve: Curves.easeInOut, keys: [
    EmblemKey(0), EmblemKey(.5, dy: -.53), EmblemKey(1),
  ]),
  const EmblemLayer('tail2', periodMs: 4600, curve: Curves.easeInOut, keys: [
    EmblemKey(0), EmblemKey(.5, dy: .57), EmblemKey(1),
  ]),
  for (var i = 1; i <= 3; i++) ...[
    EmblemLayer('w${i}A', periodMs: 4600, curve: Curves.easeInOut, keys: const [
      EmblemKey(0), EmblemKey(.5, opacity: 0), EmblemKey(1),
    ]),
    EmblemLayer('w${i}B', periodMs: 4600, curve: Curves.easeInOut, keys: const [
      EmblemKey(0, opacity: 0), EmblemKey(.5), EmblemKey(1, opacity: 0),
    ]),
  ],
];

/// Ысыах: солнце над сэргэ вращает лучи, осуохай водит хоровод.
List<EmblemLayer> _serge() => const [
  EmblemLayer('sunrays', periodMs: 24000, pivot: Offset(12.52, -20.62), keys: [
    EmblemKey(0, rot: 0),
    EmblemKey(1, rot: 360),
  ]),
  EmblemLayer('dance', periodMs: 5200, keys: [
    EmblemKey(0, dx: -1.16),
    EmblemKey(.5, dx: 1.16),
    EmblemKey(1, dx: -1.16),
  ]),
];

/// День города: окна загораются по очереди и гаснут под утро, два
/// фейерверка взлетают из-за крыш и разрываются снопами искр.
List<EmblemLayer> _city() => [
  for (final (i, d) in const [
    (1, 400), (2, 2200), (3, 3600), (4, 5400), (5, 7100), (6, 8800),
  ])
    EmblemLayer('w$i', periodMs: 12000, delayMs: d, keys: const [
      EmblemKey(0, opacity: 0),
      EmblemKey(.055, opacity: 0),
      EmblemKey(.06, opacity: .95),
      EmblemKey(.74, opacity: .95),
      EmblemKey(.75, opacity: 0),
      EmblemKey(1, opacity: 0),
    ]),
  const EmblemLayer('fw1a', periodMs: 7000, keys: [
    EmblemKey(0, opacity: 0),
    EmblemKey(.02, dy: -3.9, opacity: .9),
    EmblemKey(.1, dy: -19.48, opacity: .9),
    EmblemKey(.13, dy: -23.37, opacity: 0),
    EmblemKey(1, dy: -23.37, opacity: 0),
  ]),
  const EmblemLayer('fw1b', periodMs: 7000, pivot: Offset(-9.12, -21.68), keys: [
    EmblemKey(0, opacity: 0, scale: .25),
    EmblemKey(.12, opacity: 0, scale: .25),
    EmblemKey(.17, opacity: 1, scale: .56),
    EmblemKey(.3, opacity: 0, scale: 1.35),
    EmblemKey(1, opacity: 0, scale: .25),
  ]),
  const EmblemLayer('fw2a', periodMs: 7000, delayMs: 3200, keys: [
    EmblemKey(0, opacity: 0),
    EmblemKey(.02, dy: -3.64, opacity: .9),
    EmblemKey(.1, dy: -18.22, opacity: .9),
    EmblemKey(.13, dy: -21.85, opacity: 0),
    EmblemKey(1, dy: -21.85, opacity: 0),
  ]),
  const EmblemLayer('fw2b', periodMs: 7000, delayMs: 3200,
      pivot: Offset(9.12, -20.16), keys: [
    EmblemKey(0, opacity: 0, scale: .25),
    EmblemKey(.12, opacity: 0, scale: .25),
    EmblemKey(.17, opacity: 1, scale: .56),
    EmblemKey(.3, opacity: 0, scale: 1.35),
    EmblemKey(1, opacity: 0, scale: .25),
  ]),
];

/// Экодень: лист покачивается, подвешенный за черешок (CSS leafSway).
List<EmblemLayer> _leafSway() => const [
  EmblemLayer('sway', periodMs: 4400, alternate: true,
      curve: Curves.easeInOut, pivot: Offset(0, -15.8), keys: [
    EmblemKey(0, rot: -4.5),
    EmblemKey(1, rot: 4.5),
  ]),
];

/// Забег МАТА: эмблема дышит покачиванием (CSS gemSway).
List<EmblemLayer> _mataSway() => const [
  EmblemLayer('sway', periodMs: 5500, alternate: true,
      curve: Curves.easeInOut, pivot: Offset(0, -9), keys: [
    EmblemKey(0, rot: -3.5),
    EmblemKey(1, rot: 3.5),
  ]),
];

/// Аверс медали, живущий своей анимацией. Для медалей без спецификации,
/// незаработанных и при выключенных анимациях системы — обычный статичный
/// [MedalImage] (тот же самый пиксель в пиксель на кадре t0).
class LiveMedalImage extends StatefulWidget {
  final MedalFull medal;
  final double size;

  const LiveMedalImage({super.key, required this.medal, required this.size});

  @override
  State<LiveMedalImage> createState() => _LiveMedalImageState();
}

class _LiveMedalImageState extends State<LiveMedalImage>
    with TickerProviderStateMixin {
  final List<AnimationController> _controllers = [];
  List<EmblemLayer>? _layers;

  @override
  void initState() {
    super.initState();
    _setup();
  }

  @override
  void didUpdateWidget(covariant LiveMedalImage old) {
    super.didUpdateWidget(old);
    if (old.medal.def.id != widget.medal.def.id) _setup();
  }

  void _setup() {
    for (final c in _controllers) {
      c.dispose();
    }
    _controllers.clear();
    _layers = widget.medal.earned ? emblemMotion[widget.medal.def.id] : null;
    final layers = _layers;
    if (layers == null) return;
    for (final l in layers) {
      final c = AnimationController(
        vsync: this,
        duration: Duration(milliseconds: l.periodMs),
      );
      // Фазовый сдвиг лесенок (полосы скорости): цикл запускается позже на
      // delayMs и дальше держит смещение сам — периоды у лесенки одинаковые.
      // До старта контроллер стоит на t=0 (у полос там opacity 0 — невидимы).
      void start() => l.alternate ? c.repeat(reverse: true) : c.repeat();
      if (l.delayMs == 0) {
        start();
      } else {
        Future<void>.delayed(Duration(milliseconds: l.delayMs), () {
          if (mounted && _controllers.contains(c)) start();
        });
      }
      _controllers.add(c);
    }
  }

  @override
  void dispose() {
    for (final c in _controllers) {
      c.dispose();
    }
    super.dispose();
  }

  EmblemKey _sample(EmblemLayer l, double t) {
    final keys = l.keys;
    if (t <= keys.first.t) return keys.first;
    for (var i = 1; i < keys.length; i++) {
      if (t <= keys[i].t) {
        final a = keys[i - 1], b = keys[i];
        final span = b.t - a.t;
        final raw = span <= 0 ? 1.0 : (t - a.t) / span;
        final f = l.curve.transform(raw.clamp(0.0, 1.0));
        return EmblemKey(
          t,
          dx: a.dx + (b.dx - a.dx) * f,
          dy: a.dy + (b.dy - a.dy) * f,
          rot: a.rot + (b.rot - a.rot) * f,
          opacity: a.opacity + (b.opacity - a.opacity) * f,
          scale: a.scale + (b.scale - a.scale) * f,
          skewY: a.skewY + (b.skewY - a.skewY) * f,
        );
      }
    }
    return keys.last;
  }

  @override
  Widget build(BuildContext context) {
    final layers = _layers;
    final motionOff = MediaQuery.of(context).disableAnimations;
    if (layers == null || motionOff) {
      return MedalImage(
        def: widget.medal.def,
        earned: widget.medal.earned,
        size: widget.size,
      );
    }
    final s = widget.size / 116.0; // единицы viewBox → пиксели виджета
    final center = Offset(widget.size / 2, widget.size / 2);
    final parts = emblemParts[widget.medal.def.id]!;
    return SizedBox(
      width: widget.size,
      height: widget.size,
      child: Stack(
        fit: StackFit.expand,
        children: [
          for (final part in parts)
            _isStatic(layers, part)
                ? Image.asset(
                    'assets/medals/anim/${widget.medal.def.id}__$part.webp',
                    filterQuality: FilterQuality.medium,
                  )
                : _layer(
                    layers.firstWhere((l) => l.part == part),
                    layers.indexWhere((l) => l.part == part),
                    s,
                    center,
                  ),
        ],
      ),
    );
  }

  bool _isStatic(List<EmblemLayer> layers, String part) =>
      !layers.any((l) => l.part == part);

  /// Один живой слой. Окно (clip) режется СНАРУЖИ transform: горизонт стоит
  /// на месте, а солнце уходит за него — как clipPath эталона.
  Widget _layer(EmblemLayer l, int i, double s, Offset center) {
    Widget layer = AnimatedBuilder(
      animation: _controllers[i],
      builder: (context, child) {
        final k = _sample(l, _controllers[i].value);
        final pivotPx = center + l.pivot * s;
        final m = Matrix4.identity()
          ..translate(k.dx * s, k.dy * s)
          ..translate(pivotPx.dx, pivotPx.dy)
          ..rotateZ(k.rot * math.pi / 180);
        if (k.scale != 1) m.scale(k.scale, k.scale, 1);
        if (k.skewY != 0) m.setEntry(1, 0, math.tan(k.skewY * math.pi / 180));
        m.translate(-pivotPx.dx, -pivotPx.dy);
        Widget w = Transform(transform: m, child: child);
        if (k.opacity < 1) {
          w = Opacity(opacity: k.opacity.clamp(0.0, 1.0), child: w);
        }
        return w;
      },
      child: Image.asset(
        'assets/medals/anim/${widget.medal.def.id}__${l.part}.webp',
        width: widget.size,
        height: widget.size,
        filterQuality: FilterQuality.medium,
      ),
    );
    final clip = l.clip;
    if (clip != null) {
      layer = ClipRect(
        clipper: _WindowClipper(
          Rect.fromLTWH(
            center.dx + clip.left * s,
            center.dy + clip.top * s,
            clip.width * s,
            clip.height * s,
          ),
        ),
        child: layer,
      );
    }
    return layer;
  }
}

class _WindowClipper extends CustomClipper<Rect> {
  final Rect window;
  const _WindowClipper(this.window);

  @override
  Rect getClip(Size size) => window;

  @override
  bool shouldReclip(covariant _WindowClipper old) => old.window != window;
}
