import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../../core/theme/app_colors.dart';
import '../../data/races_provider.dart';

const _months = [
  '', 'янв', 'фев', 'мар', 'апр', 'мая', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'
];

class _TypeStyle {
  final List<Color> grad;
  final String emoji;
  const _TypeStyle(this.grad, this.emoji);
}

_TypeStyle _typeStyle(String type) {
  switch (type) {
    case 'trail':
      return const _TypeStyle([Color(0xFF12543A), Color(0xFF0A2418)], '🌲');
    case 'night':
      return const _TypeStyle([Color(0xFF3A2170), Color(0xFF140B2C)], '🌙');
    case 'fest':
      return const _TypeStyle([Color(0xFF8A3B12), Color(0xFF331405)], '🎉');
    case 'relay':
      return const _TypeStyle([Color(0xFF0D5C63), Color(0xFF082224)], '🤝');
    case 'kids':
      return const _TypeStyle([Color(0xFF8A5A12), Color(0xFF2A1A05)], '🧒');
    default:
      return const _TypeStyle([Color(0xFF123A7A), Color(0xFF0B1B39)], '🏃');
  }
}

class _StatusStyle {
  final Color color;
  final String label;
  const _StatusStyle(this.color, this.label);
}

_StatusStyle _statusStyle(String s) {
  switch (s) {
    case 'open':
      return _StatusStyle(AppColors.success, 'Регистрация');
    case 'closed':
      return _StatusStyle(AppColors.textTertiary, 'Регистрация закрыта');
    case 'done':
      return _StatusStyle(AppColors.textTertiary, 'Завершён');
    default:
      return _StatusStyle(AppColors.warning, 'Скоро');
  }
}

class RacesScreen extends ConsumerStatefulWidget {
  const RacesScreen({super.key});

  @override
  ConsumerState<RacesScreen> createState() => _RacesScreenState();
}

class _RacesScreenState extends ConsumerState<RacesScreen> {
  int _segment = 0; // 0 = ближайшие, 1 = прошедшие

  void _openRegionPicker(BuildContext context) {
    showModalBottomSheet<void>(
      context: context,
      backgroundColor: Colors.transparent,
      isScrollControlled: true,
      builder: (_) => const _RegionPicker(),
    );
  }

  @override
  Widget build(BuildContext context) {
    final async = ref.watch(racesProvider);
    final sel = ref.watch(raceSelectionProvider);
    final region = async.valueOrNull?.region ?? '';
    // Подпись чипа: имя из ленты; пока грузится — запасная из выбора; иначе «Мой регион».
    final chipLabel = region.isNotEmpty
        ? region
        : (sel.label.isNotEmpty ? sel.label : 'Мой регион');
    return DecoratedBox(
      decoration: BoxDecoration(
        color: AppColors.bg,
      ),
      child: SafeArea(
        bottom: false,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(
              padding: EdgeInsets.fromLTRB(20, 14, 20, 2),
              child: Text(
                'Старты',
                style: TextStyle(
                  color: AppColors.ink,
                  fontSize: 30,
                  fontWeight: FontWeight.w800,
                  letterSpacing: 0.2,
                ),
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 0, 20, 12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    'Календарь беговых событий',
                    style: TextStyle(color: AppColors.textSecondary, fontSize: 13),
                  ),
                  const SizedBox(height: 6),
                  // Кликабельный чип региона — открывает выбор (мой регион / вся Россия /
                  // крупные марафоны / любой регион).
                  _RegionChip(
                    label: chipLabel,
                    onTap: () => _openRegionPicker(context),
                  ),
                ],
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 0, 20, 8),
              child: _Segmented(
                index: _segment,
                labels: const ['Ближайшие', 'Прошедшие'],
                onChanged: (i) => setState(() => _segment = i),
              ),
            ),
            Expanded(
              child: async.when(
                loading: () => Center(
                  child: CircularProgressIndicator(color: AppColors.electricBlue),
                ),
                error: (_, __) =>
                    const _Empty('Не удалось загрузить старты. Проверьте связь.'),
                data: (feed) {
                  final list = feed.items
                      .where((r) => _segment == 0 ? !r.isPast : r.isPast)
                      .toList();
                  list.sort((a, b) {
                    final da = a.date, db = b.date;
                    if (da == null || db == null) return 0;
                    return _segment == 0 ? da.compareTo(db) : db.compareTo(da);
                  });
                  if (list.isEmpty) {
                    if (sel.mode == RegionMode.saved) {
                      return const _Empty(
                          'В «Моих стартах» пока пусто.\nОтметь забег «Планирую поехать» — он появится здесь.');
                    }
                    final where = region.isNotEmpty ? ' в регионе «$region»' : '';
                    return _Empty(_segment == 0
                        ? 'Пока нет ближайших стартов$where'
                        : 'Архив пуст$where');
                  }
                  return RefreshIndicator(
                    color: AppColors.electricBlue,
                    onRefresh: () => ref.refresh(racesProvider.future),
                    child: ListView.separated(
                      padding: const EdgeInsets.fromLTRB(16, 6, 16, 28),
                      itemCount: list.length,
                      separatorBuilder: (_, __) => const SizedBox(height: 14),
                      itemBuilder: (_, i) => _RaceCard(race: list[i]),
                    ),
                  );
                },
              ),
            ),
          ],
        ),
      ),
    );
  }
}

// ── Чип региона в шапке (открывает пикер) ─────────────────────────────────────

class _RegionChip extends StatelessWidget {
  final String label;
  final VoidCallback onTap;
  const _RegionChip({required this.label, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      behavior: HitTestBehavior.opaque,
      child: Container(
        padding: const EdgeInsets.fromLTRB(11, 6, 9, 6),
        decoration: BoxDecoration(
          color: AppColors.electricBlue.withValues(alpha: 0.14),
          borderRadius: BorderRadius.circular(999),
          border: Border.all(color: AppColors.electricBlue.withValues(alpha: 0.42)),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(CupertinoIcons.placemark_fill,
                size: 13, color: AppColors.electricBlue),
            const SizedBox(width: 5),
            ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 230),
              child: Text(
                label,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(
                  color: AppColors.accentInk,
                  fontSize: 13,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ),
            const SizedBox(width: 3),
            Icon(CupertinoIcons.chevron_down,
                size: 12, color: AppColors.electricBlue),
          ],
        ),
      ),
    );
  }
}

// ── Пикер региона (bottom sheet) ──────────────────────────────────────────────

String _pluralRaces(int n) {
  final a = n % 100, b = n % 10;
  if (a >= 11 && a <= 14) return 'забегов';
  if (b == 1) return 'забег';
  if (b >= 2 && b <= 4) return 'забега';
  return 'забегов';
}

class _RegionPicker extends ConsumerWidget {
  const _RegionPicker();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final sel = ref.watch(raceSelectionProvider);
    final regionsAsync = ref.watch(raceRegionsProvider);
    final plannedCount = ref.watch(plannedRacesProvider).length;

    void choose(RegionSelection s) {
      ref.read(raceSelectionProvider.notifier).state = s;
      Navigator.of(context).pop();
    }

    return Container(
      constraints: BoxConstraints(
        maxHeight: MediaQuery.of(context).size.height * 0.72,
      ),
      decoration: BoxDecoration(
        color: AppColors.soft,
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
        border: Border(top: BorderSide(color: AppColors.separator)),
      ),
      child: SafeArea(
        top: false,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              width: 40,
              height: 4,
              margin: EdgeInsets.only(top: 10, bottom: 6),
              decoration: BoxDecoration(
                color: AppColors.line,
                borderRadius: BorderRadius.circular(2),
              ),
            ),
            Padding(
              padding: EdgeInsets.fromLTRB(20, 6, 20, 8),
              child: Align(
                alignment: Alignment.centerLeft,
                child: Text(
                  'Показать старты',
                  style: TextStyle(
                    color: AppColors.ink,
                    fontSize: 16,
                    fontWeight: FontWeight.w800,
                  ),
                ),
              ),
            ),
            Flexible(
              child: ListView(
                padding: EdgeInsets.fromLTRB(12, 0, 12, 8),
                children: [
                  if (plannedCount > 0)
                    _RegionOption(
                      emoji: '⭐',
                      title: 'Мои старты',
                      subtitle: '$plannedCount ${_pluralRaces(plannedCount)} — планирую поехать',
                      selected: sel.mode == RegionMode.saved,
                      onTap: () => choose(RegionSelection.saved),
                    ),
                  _RegionOption(
                    emoji: '📍',
                    title: 'Мой регион',
                    selected: sel.mode == RegionMode.myRegion,
                    onTap: () => choose(RegionSelection.my),
                  ),
                  _RegionOption(
                    emoji: '🇷🇺',
                    title: 'Вся Россия',
                    subtitle: 'все забеги страны',
                    selected: sel.mode == RegionMode.all,
                    onTap: () => choose(RegionSelection.russia),
                  ),
                  _RegionOption(
                    emoji: '⭐',
                    title: 'Крупные марафоны',
                    subtitle: 'главные старты страны — для поездок',
                    selected: sel.mode == RegionMode.majors,
                    onTap: () => choose(RegionSelection.majors),
                  ),
                  Divider(color: AppColors.separator, height: 18),
                  ...regionsAsync.when(
                    loading: () => [
                      Padding(
                        padding: EdgeInsets.all(18),
                        child: Center(
                          child: CircularProgressIndicator(
                              color: AppColors.electricBlue),
                        ),
                      ),
                    ],
                    error: (_, __) => [
                      Padding(
                        padding: EdgeInsets.all(16),
                        child: Text('Не удалось загрузить регионы',
                            style: TextStyle(color: AppColors.textTertiary)),
                      ),
                    ],
                    data: (regions) => regions
                        .map((r) => _RegionOption(
                              emoji: '📍',
                              title: r.name,
                              subtitle: '${r.count} ${_pluralRaces(r.count)}',
                              selected: sel.mode == RegionMode.region &&
                                  sel.slug == r.slug,
                              onTap: () =>
                                  choose(RegionSelection.region(r.slug, r.name)),
                            ))
                        .toList(),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _RegionOption extends StatelessWidget {
  final String emoji;
  final String title;
  final String? subtitle;
  final bool selected;
  final VoidCallback onTap;
  const _RegionOption({
    required this.emoji,
    required this.title,
    this.subtitle,
    required this.selected,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      behavior: HitTestBehavior.opaque,
      child: Container(
        margin: const EdgeInsets.symmetric(vertical: 3),
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 11),
        decoration: BoxDecoration(
          color: selected
              ? AppColors.electricBlue.withValues(alpha: 0.14)
              : Colors.transparent,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(
            color: selected
                ? AppColors.electricBlue.withValues(alpha: 0.42)
                : Colors.transparent,
          ),
        ),
        child: Row(
          children: [
            SizedBox(
              width: 26,
              child: Text(emoji, style: const TextStyle(fontSize: 16)),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    title,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(
                      color: AppColors.ink,
                      fontSize: 14.5,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  if (subtitle != null)
                    Padding(
                      padding: const EdgeInsets.only(top: 1),
                      child: Text(
                        subtitle!,
                        style: TextStyle(
                            color: AppColors.textTertiary, fontSize: 11.5),
                      ),
                    ),
                ],
              ),
            ),
            if (selected)
              Icon(CupertinoIcons.check_mark,
                  size: 16, color: AppColors.electricBlue),
          ],
        ),
      ),
    );
  }
}

class _Segmented extends StatelessWidget {
  final int index;
  final List<String> labels;
  final ValueChanged<int> onChanged;
  const _Segmented({required this.index, required this.labels, required this.onChanged});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(4),
      decoration: BoxDecoration(
        color: AppColors.paper,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.separator),
      ),
      child: Row(
        children: [
          for (var i = 0; i < labels.length; i++)
            Expanded(
              child: GestureDetector(
                onTap: () => onChanged(i),
                child: AnimatedContainer(
                  duration: const Duration(milliseconds: 150),
                  padding: const EdgeInsets.symmetric(vertical: 9),
                  alignment: Alignment.center,
                  decoration: BoxDecoration(
                    color: i == index ? AppColors.bgCard : Colors.transparent,
                    borderRadius: BorderRadius.circular(9),
                  ),
                  child: Text(
                    labels[i],
                    style: TextStyle(
                      color: i == index ? AppColors.ink : AppColors.textTertiary,
                      fontSize: 13.5,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }
}

class _RaceCard extends StatelessWidget {
  final RaceEvent race;
  const _RaceCard({required this.race});

  @override
  Widget build(BuildContext context) {
    final ts = _typeStyle(race.type);
    final ss = _statusStyle(race.regStatus);
    final d = race.date;
    return GestureDetector(
      onTap: () => context.push('/races/detail', extra: race),
      child: Container(
        decoration: BoxDecoration(
          color: AppColors.bgCard,
          borderRadius: BorderRadius.circular(20),
          border: Border.all(color: AppColors.separator),
        ),
        clipBehavior: Clip.antiAlias,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // cover
            SizedBox(
              height: race.isPast ? 96 : 124,
              child: Stack(
                fit: StackFit.expand,
                children: [
                  DecoratedBox(
                    decoration: BoxDecoration(
                      gradient: LinearGradient(
                        begin: Alignment.topLeft,
                        end: Alignment.bottomRight,
                        colors: ts.grad,
                      ),
                    ),
                  ),
                  Positioned(
                    right: -6,
                    top: 8,
                    child: Opacity(
                      opacity: 0.16,
                      child: Text(ts.emoji, style: const TextStyle(fontSize: 92)),
                    ),
                  ),
                  const DecoratedBox(
                    decoration: BoxDecoration(
                      gradient: LinearGradient(
                        begin: Alignment.topCenter,
                        end: Alignment.bottomCenter,
                        colors: [Colors.transparent, Color(0xCC060A14)],
                        stops: [0.35, 1.0],
                      ),
                    ),
                  ),
                  if (race.typeLabel.isNotEmpty)
                    Positioned(
                      left: 12,
                      top: 12,
                      child: _pill(race.typeLabel, const Color(0xCFCFE0FF), const Color(0xFF06101F)),
                    ),
                  Positioned(
                    right: 12,
                    top: 12,
                    child: _statusPill(ss),
                  ),
                  if (d != null)
                    Positioned(
                      left: 12,
                      bottom: 12,
                      child: _dateChip(d),
                    ),
                ],
              ),
            ),
            // body
            Padding(
              padding: const EdgeInsets.fromLTRB(14, 12, 14, 14),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    race.title,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(
                      color: AppColors.ink,
                      fontSize: 18,
                      fontWeight: FontWeight.w800,
                      height: 1.1,
                    ),
                  ),
                  const SizedBox(height: 6),
                  Row(
                    children: [
                      Icon(CupertinoIcons.location_solid,
                          size: 13, color: AppColors.electricBlue),
                      const SizedBox(width: 5),
                      Expanded(
                        child: Text(
                          [race.city, race.place].where((s) => s.isNotEmpty).join(' · '),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: TextStyle(color: AppColors.textSecondary, fontSize: 12.5),
                        ),
                      ),
                    ],
                  ),
                  if (!race.isPast && race.distances.isNotEmpty) ...[
                    const SizedBox(height: 10),
                    Wrap(
                      spacing: 6,
                      runSpacing: 6,
                      children: [
                        for (final dist in race.distances)
                          Container(
                            padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 5),
                            decoration: BoxDecoration(
                              color: AppColors.soft,
                              borderRadius: BorderRadius.circular(8),
                              border: Border.all(color: AppColors.separator),
                            ),
                            child: Text(
                              dist,
                              style: TextStyle(
                                color: AppColors.ink,
                                fontSize: 12,
                                fontWeight: FontWeight.w600,
                              ),
                            ),
                          ),
                      ],
                    ),
                  ],
                  if (!race.isPast && race.points > 0) ...[
                    const SizedBox(height: 10),
                    Row(
                      children: [
                        Icon(CupertinoIcons.circle_grid_hex_fill,
                            size: 14, color: AppColors.success),
                        const SizedBox(width: 6),
                        Text(
                          '+${race.points} баллов за финиш',
                          style: TextStyle(
                              color: AppColors.success, fontSize: 12.5, fontWeight: FontWeight.w600),
                        ),
                      ],
                    ),
                  ],
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  static Widget _pill(String text, Color bg, Color fg) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 5),
        decoration: BoxDecoration(color: bg, borderRadius: BorderRadius.circular(8)),
        child: Text(text,
            style: TextStyle(color: fg, fontSize: 11, fontWeight: FontWeight.w700)),
      );

  static Widget _statusPill(_StatusStyle ss) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
        decoration: BoxDecoration(
          color: AppColors.glassPaper,
          borderRadius: BorderRadius.circular(999),
          border: Border.all(color: AppColors.line),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              width: 7,
              height: 7,
              decoration: BoxDecoration(color: ss.color, shape: BoxShape.circle),
            ),
            const SizedBox(width: 6),
            Text(ss.label,
                style: TextStyle(color: ss.color, fontSize: 11, fontWeight: FontWeight.w700)),
          ],
        ),
      );

  static Widget _dateChip(DateTime d) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 11, vertical: 7),
        decoration: BoxDecoration(
          color: AppColors.glassPaper,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: AppColors.line),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(
              d.day.toString().padLeft(2, '0'),
              style: TextStyle(
                  color: AppColors.ink, fontSize: 24, fontWeight: FontWeight.w800, height: 0.95),
            ),
            Text(
              _months[d.month].toUpperCase(),
              style: TextStyle(
                  color: AppColors.muted, fontSize: 11, fontWeight: FontWeight.w700, letterSpacing: 1),
            ),
          ],
        ),
      );
}

class _Empty extends StatelessWidget {
  final String text;
  const _Empty(this.text);

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(CupertinoIcons.calendar, size: 44, color: AppColors.textTertiary),
            const SizedBox(height: 12),
            Text(text,
                textAlign: TextAlign.center,
                style: TextStyle(color: AppColors.textSecondary, fontSize: 14)),
          ],
        ),
      ),
    );
  }
}
