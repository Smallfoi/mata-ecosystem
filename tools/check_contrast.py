#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Проверка контраста цветов экосистемы МАТА по двум шкалам сразу.

Правило МАТА (D-127): требование = СТРОГОЕ из двух.
  * APCA (Lc, кандидат в WCAG 3) — цель по читаемости;
  * WCAG 2.x (коэффициент контраста) — обязательный пол: 4,5:1 для текста,
    3:1 для крупного текста и не-текстовых элементов.

Лесенка уровней Lc:
    роль            светлая тема   тёмная тема   пол WCAG
    основной            90             90          4,5:1
    вторичный           75             60          4,5:1
    третий              60             45          4,5:1
    неактивный          30             30            —
    не текст            15             15          3:1

В тёмных темах планка на ступень ниже сознательно: dark-mode часть APCA помечена
автором как preliminary, а требование Lc 75 по светлому тексту на тёмном фоне
вынуждает делать весь вторичный текст почти белым (см. DECISIONS.md D-127).

Использование:
    python tools/check_contrast.py                      # проверить палитру МАТА
    python tools/check_contrast.py --json               # то же, машиночитаемо
    python tools/check_contrast.py --pair "#5F665E" "#F0EFE9" --role secondary
    python tools/check_contrast.py --pair "#5F665E" "#F0EFE9" --role secondary --fix

Код возврата: 0 — всё проходит, 1 — есть провалы.
"""
from __future__ import annotations

import argparse
import colorsys
import json
import sys

# Кириллица в консоли Windows (cp866/cp1251) бьётся — печатаем в UTF-8 явно.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8')
    except (AttributeError, ValueError):
        pass

# --- APCA 0.1.9, константы W3 4g -------------------------------------------
_TRC = 2.4
_RCO, _GCO, _BCO = 0.2126729, 0.7151522, 0.0721750
_NORM_BG, _NORM_TXT = 0.56, 0.57
_REV_TXT, _REV_BG = 0.62, 0.65
_BLK_THRS, _BLK_CLMP = 0.022, 1.414
_SCALE, _OFFSET = 1.14, 0.027
_DELTA_Y_MIN, _LO_CLIP = 0.0005, 0.1


def parse_hex(value: str) -> tuple[int, int, int]:
    """'#F0EFE9' или 'F0EFE9' или '#FFF' -> (r, g, b)."""
    s = value.strip().lstrip('#')
    if len(s) == 3:
        s = ''.join(c * 2 for c in s)
    if len(s) != 6:
        raise ValueError('ожидался цвет вида #RRGGBB, получено: %r' % value)
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def to_hex(rgb) -> str:
    return '#%02X%02X%02X' % tuple(max(0, min(255, int(round(v)))) for v in rgb)


def luminance_apca(color: str) -> float:
    r, g, b = parse_hex(color)
    return (_RCO * (r / 255.0) ** _TRC
            + _GCO * (g / 255.0) ** _TRC
            + _BCO * (b / 255.0) ** _TRC)


def apca(text: str, background: str) -> float:
    """Lc по APCA. Знак: + тёмный текст по светлому, − светлый по тёмному."""
    ty, by = luminance_apca(text), luminance_apca(background)
    ty = ty if ty > _BLK_THRS else ty + (_BLK_THRS - ty) ** _BLK_CLMP
    by = by if by > _BLK_THRS else by + (_BLK_THRS - by) ** _BLK_CLMP
    if abs(by - ty) < _DELTA_Y_MIN:
        return 0.0
    if by > ty:
        sapc = (by ** _NORM_BG - ty ** _NORM_TXT) * _SCALE
        out = 0.0 if sapc < _LO_CLIP else sapc - _OFFSET
    else:
        sapc = (by ** _REV_BG - ty ** _REV_TXT) * _SCALE
        out = 0.0 if sapc > -_LO_CLIP else sapc + _OFFSET
    return out * 100.0


def wcag(color_a: str, color_b: str) -> float:
    """Коэффициент контраста по WCAG 2.x, от 1 до 21."""
    def rel(color: str) -> float:
        r, g, b = parse_hex(color)

        def chan(v: float) -> float:
            v /= 255.0
            return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
        return 0.2126 * chan(r) + 0.7152 * chan(g) + 0.0722 * chan(b)

    a, b = rel(color_a), rel(color_b)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


# --- лесенка уровней --------------------------------------------------------
ROLES = {
    #  роль          Lc светлая  Lc тёмная  пол WCAG
    'primary':      (90, 90, 4.5),
    'secondary':    (75, 60, 4.5),
    'tertiary':     (60, 45, 4.5),
    'disabled':     (30, 30, 0.0),
    'nontext':      (15, 15, 3.0),
}
ROLE_RU = {
    'primary': 'основной', 'secondary': 'вторичный', 'tertiary': 'третий',
    'disabled': 'неактивный', 'nontext': 'не текст',
}


def target_for(role: str, dark: bool) -> tuple[float, float]:
    if role not in ROLES:
        raise ValueError('роль должна быть одной из: %s' % ', '.join(ROLES))
    light_lc, dark_lc, wcag_min = ROLES[role]
    return (dark_lc if dark else light_lc), wcag_min


def suggest(text: str, backgrounds, lc_target: float, wcag_min: float):
    """Ближайший цвет того же тона и насыщенности, проходящий оба порога."""
    r, g, b = [v / 255.0 for v in parse_hex(text)]
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    darker = luminance_apca(backgrounds[0]) > luminance_apca(text)
    step = 0.0012
    for i in range(int(1 / step) + 1):
        new_l = l - i * step if darker else l + i * step
        if not 0.0 <= new_l <= 1.0:
            break
        cand = to_hex([v * 255 for v in colorsys.hls_to_rgb(h, new_l, s)])
        if (min(abs(apca(cand, bg)) for bg in backgrounds) >= lc_target
                and min(wcag(cand, bg) for bg in backgrounds) >= wcag_min):
            return cand
    return None


# --- палитра экосистемы -----------------------------------------------------
# (имя поверхности, тёмная ли, фоны, [(роль токена, цвет, роль по лесенке)])
PALETTE = [
    ('Сайт — светлая', False, ['#F4F1EA', '#FFFDF8', '#FFFFFF'], [
        ('ink', '#111317', 'primary'),
        ('muted', '#6F7278', 'secondary'),
        ('accent-ink (ссылки)', '#167A95', 'secondary'),
    ]),
    ('Сайт — блоки на графите', True, ['#20252B'], [
        ('on-dark', '#FFFFFF', 'primary'),
        ('подпись', '#AEB6C0', 'tertiary'),
    ]),
    ('Квартал — светлая', False, ['#F0EFE9', '#FFFFFF', '#E8E6DA'], [
        ('ink', '#20252B', 'primary'),
        ('muted', '#5F665E', 'secondary'),
        ('faint', '#767E74', 'tertiary'),
        ('disabled', '#A9ACA4', 'disabled'),
        ('success', '#1F7A44', 'secondary'),
        ('warning', '#8F6209', 'secondary'),
        ('danger', '#B33328', 'secondary'),
        ('teal', '#2E6E64', 'secondary'),
    ]),
    ('Квартал — графитовая', True, ['#20252B', '#2A302C', '#2F362F', '#343B35'], [
        ('ink', '#EDEFE8', 'primary'),
        ('muted', '#9AA59D', 'secondary'),
        ('faint', '#7F8880', 'tertiary'),
        ('disabled', '#5A625C', 'disabled'),
        ('success', '#9CD89A', 'secondary'),
        ('warning', '#D9B25C', 'secondary'),
        ('danger', '#E08A73', 'secondary'),
        ('teal', '#9CC9BF', 'secondary'),
    ]),
    ('MATA Store — светлая', False, ['#FFFFFF', '#F4F4F0', '#E4E5E0'], [
        ('black (графит)', '#2A302C', 'primary'),
        ('grey600', '#5A625B', 'secondary'),
        ('grey400', '#A7AEA7', 'tertiary'),
        ('lavender как текст', '#B6B7BF', 'tertiary'),
        ('red', '#E53935', 'secondary'),
        ('success', '#2E7D32', 'secondary'),
    ]),
    ('MATA Store — на графите', True, ['#2A302C'], [
        ('white', '#FFFFFF', 'primary'),
    ]),
    ('Админка — светлая', False, ['#FFFFFF', '#FAFBFC', '#F2F5F7'], [
        ('--m-text', '#20252B', 'primary'),
        ('--m-muted', '#6F7278', 'secondary'),
        ('--m-dim', '#9CA3AF', 'tertiary'),
        ('--m-ok', '#16A34A', 'secondary'),
        ('--m-warn', '#B45309', 'secondary'),
        ('--m-bad', '#DC2626', 'secondary'),
        ('--m-control (рамка)', '#CBD2D6', 'nontext'),
    ]),
    ('Админка — тёмная', True, ['#1F2937', '#111827', '#2A3645'], [
        ('--m-text', '#E5E7EB', 'primary'),
        ('--m-muted', '#9CA3AF', 'secondary'),
        ('--m-dim', '#6B7280', 'tertiary'),
        ('--m-accent', '#57BCD8', 'secondary'),
        ('--m-ok', '#34D399', 'secondary'),
        ('--m-warn', '#FBBF24', 'secondary'),
        ('--m-bad', '#F87171', 'secondary'),
        ('--m-control (рамка)', '#4B5563', 'nontext'),
    ]),
]


def check_palette(as_json: bool, with_fix: bool) -> int:
    failures = 0
    report = []
    for surface, dark, backgrounds, tokens in PALETTE:
        rows = []
        for name, color, role in tokens:
            lc_target, wcag_min = target_for(role, dark)
            lc = min(abs(apca(color, bg)) for bg in backgrounds)
            ratio = min(wcag(color, bg) for bg in backgrounds)
            ok = lc >= lc_target and ratio >= wcag_min
            row = {
                'token': name, 'color': color, 'role': role,
                'lc': round(lc, 1), 'lcTarget': lc_target,
                'wcag': round(ratio, 2), 'wcagMin': wcag_min, 'ok': ok,
            }
            if not ok:
                failures += 1
                if with_fix:
                    row['suggest'] = suggest(color, backgrounds, lc_target, wcag_min)
            rows.append(row)
        report.append({'surface': surface, 'dark': dark,
                       'backgrounds': backgrounds, 'tokens': rows})

    if as_json:
        json.dump({'failures': failures, 'surfaces': report},
                  sys.stdout, ensure_ascii=False, indent=1)
        sys.stdout.write('\n')
        return 1 if failures else 0

    for surface in report:
        print('\n%s   фоны: %s' % (surface['surface'], ', '.join(surface['backgrounds'])))
        print('-' * 84)
        for row in surface['tokens']:
            mark = 'OK  ' if row['ok'] else 'ПЛОХО'
            line = ('  %-5s %-22s %-9s Lc %5.1f (нужно %2d)   %5.2f:1 (нужно %.1f)'
                    % (mark, row['token'], row['color'], row['lc'],
                       row['lcTarget'], row['wcag'], row['wcagMin']))
            if row.get('suggest'):
                line += '   ->  %s' % row['suggest']
            print(line)
    print('\nПровалов: %d' % failures)
    if failures:
        print('Правило и лесенка уровней: docs/DESIGN.md, решение D-127.')
    return 1 if failures else 0


def check_pair(text: str, background: str, role: str, dark: bool, with_fix: bool) -> int:
    lc_target, wcag_min = target_for(role, dark)
    lc = abs(apca(text, background))
    ratio = wcag(text, background)
    ok = lc >= lc_target and ratio >= wcag_min
    print('текст %s на фоне %s — роль «%s»%s'
          % (text.upper(), background.upper(), ROLE_RU[role],
             ', тёмная тема' if dark else ''))
    print('  APCA    Lc %.1f   нужно %d   %s'
          % (lc, lc_target, 'ок' if lc >= lc_target else 'НЕ ПРОХОДИТ'))
    print('  WCAG 2  %.2f:1  нужно %.1f:1  %s'
          % (ratio, wcag_min, 'ок' if ratio >= wcag_min else 'НЕ ПРОХОДИТ'))
    if not ok and with_fix:
        better = suggest(text, [background], lc_target, wcag_min)
        print('  ближайший проходящий того же тона: %s' % (better or 'не найден'))
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Контраст цветов МАТА: APCA (Lc) + WCAG 2 одновременно.')
    parser.add_argument('--pair', nargs=2, metavar=('ТЕКСТ', 'ФОН'),
                        help='проверить одну пару цветов вместо всей палитры')
    parser.add_argument('--role', default='secondary', choices=sorted(ROLES),
                        help='роль текста по лесенке (по умолчанию secondary)')
    parser.add_argument('--dark', action='store_true',
                        help='считать по планке тёмной темы')
    parser.add_argument('--fix', action='store_true',
                        help='подобрать ближайший проходящий цвет того же тона')
    parser.add_argument('--json', action='store_true', dest='as_json',
                        help='машиночитаемый вывод (только для полной палитры)')
    args = parser.parse_args()

    try:
        if args.pair:
            return check_pair(args.pair[0], args.pair[1], args.role,
                              args.dark, args.fix)
        return check_palette(args.as_json, args.fix)
    except ValueError as exc:
        print('Ошибка: %s' % exc, file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
