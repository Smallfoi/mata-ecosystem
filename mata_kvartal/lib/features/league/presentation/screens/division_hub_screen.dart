import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../../../../core/theme/app_colors.dart';
import '../../../../core/theme/app_theme.dart';
import '../../../../shared/widgets/tab_visibility.dart';
import '../../../celebration/season_ceremony.dart';
import '../../../trails/data/trails_provider.dart';
import '../../data/division_provider.dart';
import '../../data/league_provider.dart';
import 'league_screen.dart' show showRunnerProfileSheet;

/// Хаб «Лига» — вариант Д «Дивизион» (Ф0, утверждён владельцем 31.08.2026).
///
/// Герой экрана — твой дивизион: эмблема-плита уровня, шкала позиции с зонами
/// вылета и повышения, форма недели точками-днями. Зачёты и тропы — чипы над
/// таблицей. При скролле шапка сжимается в строку «Проспект · #6».
class DivisionHubScreen extends ConsumerStatefulWidget {
  const DivisionHubScreen({super.key});

  @override
  ConsumerState<DivisionHubScreen> createState() => _DivisionHubScreenState();
}

/// Что открыто в хабе: четыре зачёта, «ты против себя» и тропы.
enum HubTab { km, consistency, mylane, clubs, personal, trails }

extension HubTabInfo on HubTab {
  String get title => switch (this) {
    HubTab.km => 'Километры',
    HubTab.consistency => 'Постоянство',
    HubTab.mylane => 'Своя лига',
    HubTab.clubs => 'Клубы',
    HubTab.personal => 'Прогресс',
    HubTab.trails => 'Тропы',
  };

  LeagueBoard? get board => switch (this) {
    HubTab.km => LeagueBoard.absolute,
    HubTab.consistency => LeagueBoard.consistency,
    HubTab.mylane => LeagueBoard.mylane,
    HubTab.clubs => LeagueBoard.club,
    HubTab.personal => LeagueBoard.personal,
    HubTab.trails => null,
  };
}

final hubTabProvider = StateProvider<HubTab>((_) => HubTab.km);

class _DivisionHubScreenState extends ConsumerState<DivisionHubScreen>
    with TabVisibility {
  final _scroll = ScrollController();
  bool _seasonChecked = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _maybeShowSeason());
  }

  /// Итог прошлого сезона: церемония показывается один раз на месяц
  /// (Ф5; отметка о показе — локально, как решили в аудите).
  Future<void> _maybeShowSeason() async {
    if (_seasonChecked || !mounted) return;
    _seasonChecked = true;
    try {
      final result = await ref.read(seasonLatestProvider.future);
      if (result == null || !mounted) return;
      final prefs = await SharedPreferences.getInstance();
      final key = 'kvartal.season.seen.${result.month}';
      if (prefs.getBool(key) ?? false) return;
      await prefs.setBool(key, true);
      if (!mounted) return;
      await showSeasonCeremony(context, result: result);
    } catch (_) {
      _seasonChecked = false; // офлайн — попробуем при следующем входе
    }
  }

  @override
  void dispose() {
    _scroll.dispose();
    super.dispose();
  }

  @override
  void onTabShown() {
    ref.invalidate(leagueBoardDataProvider);
    ref.invalidate(runnerLevelProvider);
    ref.invalidate(trailsProvider);
  }

  @override
  Widget build(BuildContext context) {
    final tab = ref.watch(hubTabProvider);
    final level = ref.watch(runnerLevelProvider).valueOrNull;
    final boardAsync = ref.watch(leagueBoardDataProvider);
    final form = ref.watch(weekFormProvider);
    final period = ref.watch(leaguePeriodProvider);
    final me = boardAsync.valueOrNull?.me;
    // Серверный дивизион (Ф0): имя группы, «N бегунов твоего уровня»,
    // моё место и движение за сутки. На неделе — источник шкалы и таблицы.
    final division = ref.watch(divisionProvider).valueOrNull;
    final divisionWeek = period == 'week' &&
        (tab == HubTab.km || tab == HubTab.consistency);

    return Scaffold(
      backgroundColor: AppColors.bg,
      body: SafeArea(
        bottom: false,
        child: RefreshIndicator(
          onRefresh: () async {
            ref.invalidate(leagueBoardDataProvider);
            ref.invalidate(runnerLevelProvider);
            ref.invalidate(trailsProvider);
          },
          child: CustomScrollView(
            controller: _scroll,
            physics: const AlwaysScrollableScrollPhysics(),
            slivers: [
              SliverPersistentHeader(
                pinned: true,
                delegate: _DivisionHeaderDelegate(
                  level: level,
                  divisionName: division?.name,
                  divisionSize: division?.size ?? 0,
                  movement: divisionWeek ? division?.myMovement : null,
                  place: tab == HubTab.trails || tab == HubTab.personal
                      ? null
                      : (divisionWeek ? division?.myPlace : me?.place),
                  of: tab == HubTab.trails || tab == HubTab.personal
                      ? null
                      : (divisionWeek ? division?.size : me?.of),
                  period: period,
                  form: form,
                  showLadder:
                      tab != HubTab.trails && tab != HubTab.personal,
                  noLadderText: tab == HubTab.trails
                      ? 'Пробеги тропу — прохождение засчитается само'
                      : 'Зачёт без мест — ты против себя',
                  onCompactTap: () => _scroll.animateTo(
                    0,
                    duration: AppTheme.durFast,
                    curve: AppTheme.ease,
                  ),
                ),
              ),
              const SliverToBoxAdapter(child: _HubChips()),
              if (tab == HubTab.trails)
                const _TrailsBody()
              else if (divisionWeek && division != null &&
                  division.members.isNotEmpty)
                _DivisionBody(division: division, tab: tab)
              else
                _BoardBody(tab: tab),
              const SliverToBoxAdapter(child: SizedBox(height: 110)),
            ],
          ),
        ),
      ),
    );
  }
}

// ── Шапка-дивизион (сжимается при скролле) ─────────────────────────────────

class _DivisionHeaderDelegate extends SliverPersistentHeaderDelegate {
  final RunnerLevel? level;
  final String? divisionName;
  final int divisionSize;
  final int? movement;
  final int? place;
  final int? of;
  final String period;
  final List<bool> form;
  final bool showLadder;
  final String noLadderText;
  final VoidCallback onCompactTap;

  const _DivisionHeaderDelegate({
    required this.level,
    this.divisionName,
    this.divisionSize = 0,
    this.movement,
    required this.place,
    required this.of,
    required this.period,
    required this.form,
    required this.showLadder,
    required this.noLadderText,
    required this.onCompactTap,
  });

  @override
  double get maxExtent => 306;

  @override
  double get minExtent => 62;

  @override
  bool shouldRebuild(_DivisionHeaderDelegate old) =>
      old.divisionName != divisionName ||
      old.divisionSize != divisionSize ||
      old.movement != movement ||
      old.level != level ||
      old.place != place ||
      old.of != of ||
      old.period != period ||
      old.form.join() != form.join() ||
      old.showLadder != showLadder ||
      old.noLadderText != noLadderText;

  @override
  Widget build(BuildContext context, double shrinkOffset, bool overlaps) {
    final t = (shrinkOffset / (maxExtent - minExtent)).clamp(0.0, 1.0);
    final fullOpacity = (1 - t * 1.6).clamp(0.0, 1.0);
    final compactOpacity = ((t - 0.55) * 2.3).clamp(0.0, 1.0);

    return Container(
      color: AppColors.bg,
      child: Stack(
        fit: StackFit.expand,
        children: [
          // Полная шапка.
          IgnorePointer(
            ignoring: fullOpacity == 0,
            child: Opacity(
              opacity: fullOpacity,
              child: SingleChildScrollView(
                physics: const NeverScrollableScrollPhysics(),
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(20, 12, 20, 0),
                  child: Column(
                    children: [
                      Row(
                        children: [
                          Expanded(
                            child: Text(
                              'Лига',
                              style: Theme.of(context).textTheme.headlineMedium
                                  ?.copyWith(
                                    fontWeight: FontWeight.w800,
                                    height: 1.1,
                                  ),
                            ),
                          ),
                          const _PeriodToggle(),
                        ],
                      ),
                      const SizedBox(height: 12),
                      _DivisionCard(
                        level: level,
                        divisionName: divisionName,
                        divisionSize: divisionSize,
                        place: place,
                        of: of,
                        period: period,
                        form: form,
                        showLadder: showLadder,
                        noLadderText: noLadderText,
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
          // Компакт-строка: «Проспект · #6».
          IgnorePointer(
            ignoring: compactOpacity == 0,
            child: Opacity(
              opacity: compactOpacity,
              child: GestureDetector(
                behavior: HitTestBehavior.opaque,
                onTap: onCompactTap,
                child: Container(
                  alignment: Alignment.center,
                  padding: const EdgeInsets.symmetric(horizontal: 20),
                  decoration: BoxDecoration(
                    color: AppColors.bg,
                    border: Border(bottom: BorderSide(color: AppColors.line)),
                  ),
                  child: Row(
                    children: [
                      Container(
                        width: 26,
                        height: 26,
                        alignment: Alignment.center,
                        decoration: BoxDecoration(
                          color: AppColors.lime,
                          borderRadius: BorderRadius.circular(8),
                        ),
                        child: Text(
                          level?.roman ?? '–',
                          style: const TextStyle(
                            fontFamily: AppTheme.fontDisplay,
                            fontSize: 9.5,
                            fontWeight: FontWeight.w800,
                            color: Color(0xFF171C19),
                          ),
                        ),
                      ),
                      const SizedBox(width: 10),
                      Expanded(
                        child: Text(
                          [
                            divisionName ?? level?.title ?? 'Лига',
                            if (place != null) '#$place',
                            if (movement != null && movement != 0)
                              movement! > 0
                                  ? '▲$movement'
                                  : '▼${-movement!}',
                          ].join(' · '),
                          style: TextStyle(
                            fontFamily: AppTheme.fontDisplay,
                            fontSize: 15,
                            fontWeight: FontWeight.w800,
                            color: AppColors.ink,
                          ),
                        ),
                      ),
                      Icon(
                        CupertinoIcons.chevron_up,
                        size: 16,
                        color: AppColors.faint,
                      ),
                    ],
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

/// Графитовая карточка дивизиона: эмблема, имя, шкала позиции, форма недели.
class _DivisionCard extends StatelessWidget {
  final RunnerLevel? level;
  final String? divisionName;
  final int divisionSize;
  final int? place;
  final int? of;
  final String period;
  final List<bool> form;
  final bool showLadder;
  final String noLadderText;

  const _DivisionCard({
    required this.level,
    this.divisionName,
    this.divisionSize = 0,
    required this.place,
    required this.of,
    required this.period,
    required this.form,
    required this.showLadder,
    required this.noLadderText,
  });

  String get _resetLabel => switch (period) {
    'month' => 'сброс 1-го числа',
    'q90' => 'скользящее окно 90 дней',
    _ => 'сброс в вс 23:59',
  };

  @override
  Widget build(BuildContext context) {
    // «Твоего уровня» — правда дивизиона: группа собрана по пожизненным км.
    final meta = divisionSize > 0
        ? '$divisionSize ${_plural(divisionSize, 'бегун', 'бегуна', 'бегунов')} '
            'твоего уровня · $_resetLabel'
        : of != null && of! > 0
            ? '$of ${_plural(of!, 'бегун', 'бегуна', 'бегунов')} в зачёте · $_resetLabel'
            : _resetLabel;
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(16, 14, 16, 12),
      decoration: BoxDecoration(
        color: AppColors.block,
        borderRadius: BorderRadius.circular(16),
      ),
      child: Column(
        children: [
          // Эмблема-плита дивизиона (лайм, врезная тень снизу).
          Container(
            width: 64,
            height: 64,
            alignment: Alignment.center,
            decoration: BoxDecoration(
              // Плита с «врезанной» нижней гранью — как на макете
              // (inset 0 -5px 0 rgba(32,37,43,.14)).
              gradient: const LinearGradient(
                begin: Alignment.topCenter,
                end: Alignment.bottomCenter,
                stops: [0, .88, .88, 1],
                colors: [
                  AppColors.lime,
                  AppColors.lime,
                  Color(0xFFCBDE52),
                  Color(0xFFCBDE52),
                ],
              ),
              borderRadius: BorderRadius.circular(18),
            ),
            child: Text(
              level?.roman ?? '–',
              style: const TextStyle(
                fontFamily: AppTheme.fontDisplay,
                fontSize: 19,
                fontWeight: FontWeight.w800,
                color: Color(0xFF171C19),
              ),
            ),
          ),
          const SizedBox(height: 8),
          Text(
            divisionName != null
                ? 'Дивизион «$divisionName»'
                : level != null
                    ? 'Дивизион «${level!.title}»'
                    : 'Твой дивизион',
            style: const TextStyle(
              fontFamily: AppTheme.fontDisplay,
              fontSize: 16,
              fontWeight: FontWeight.w800,
              color: Color(0xFFEDEFE8),
            ),
          ),
          const SizedBox(height: 2),
          Text(
            meta,
            style: const TextStyle(
              fontSize: 11,
              fontWeight: FontWeight.w600,
              color: Color(0xFF9AA59D),
            ),
          ),
          const SizedBox(height: 10),
          if (showLadder)
            _PositionLadder(place: place, of: of)
          else
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 8),
              child: Text(
                noLadderText,
                style: const TextStyle(
                  fontSize: 11,
                  fontWeight: FontWeight.w600,
                  color: Color(0xFF9AA59D),
                ),
              ),
            ),
          const SizedBox(height: 10),
          _WeekForm(form: form),
          const SizedBox(height: 5),
          const Text(
            'форма недели · пн–вс',
            style: TextStyle(
              fontSize: 9.5,
              fontWeight: FontWeight.w600,
              letterSpacing: .6,
              color: Color(0xFF9AA59D),
            ),
          ),
        ],
      ),
    );
  }
}

/// Шкала позиции: слева зона вылета (тёплый), справа зона повышения (лайм).
class _PositionLadder extends StatelessWidget {
  final int? place;
  final int? of;

  const _PositionLadder({required this.place, required this.of});

  @override
  Widget build(BuildContext context) {
    final hasPlace = place != null && of != null && of! > 0;
    final fraction = !hasPlace
        ? null
        : of! <= 1
        ? 1.0
        : ((of! - place!) / (of! - 1)).clamp(0.0, 1.0);
    return SizedBox(
      height: 40,
      child: LayoutBuilder(
        builder: (context, box) {
          final w = box.maxWidth - 8;
          return Stack(
            clipBehavior: Clip.none,
            children: [
              Positioned(
                left: 4,
                top: 4,
                child: Text(
                  'ВЫЛЕТ',
                  style: TextStyle(
                    fontSize: 7.5,
                    fontWeight: FontWeight.w700,
                    letterSpacing: .5,
                    color: AppColors.warm.withValues(alpha: .9),
                  ),
                ),
              ),
              Positioned(
                right: 4,
                top: 4,
                child: const Text(
                  'ВЫШЕ',
                  style: TextStyle(
                    fontSize: 7.5,
                    fontWeight: FontWeight.w700,
                    letterSpacing: .5,
                    color: AppColors.lime,
                  ),
                ),
              ),
              // Дорожка с зонами.
              Positioned(
                left: 4,
                right: 4,
                top: 21,
                child: Container(
                  height: 5,
                  decoration: BoxDecoration(
                    borderRadius: BorderRadius.circular(3),
                    color: const Color(0xFF4A5248),
                  ),
                  clipBehavior: Clip.antiAlias,
                  child: Row(
                    children: [
                      Container(
                        width: w * .18,
                        color: AppColors.warm.withValues(alpha: .75),
                      ),
                      const Spacer(),
                      Container(width: w * .18, color: AppColors.lime),
                    ],
                  ),
                ),
              ),
              if (fraction != null)
                Positioned(
                  left: 4 + w * fraction - 11,
                  top: 13,
                  child: Container(
                    width: 22,
                    height: 22,
                    alignment: Alignment.center,
                    decoration: BoxDecoration(
                      color: AppColors.lime,
                      borderRadius: BorderRadius.circular(8),
                      border: Border.all(
                        color: const Color(0xFF171C19),
                        width: 2,
                      ),
                    ),
                    child: Text(
                      '#$place',
                      style: const TextStyle(
                        fontFamily: AppTheme.fontDisplay,
                        fontSize: 8,
                        fontWeight: FontWeight.w800,
                        color: Color(0xFF171C19),
                      ),
                    ),
                  ),
                )
              else
                const Positioned(
                  left: 0,
                  right: 0,
                  top: 30,
                  child: Text(
                    'пробеги в этом периоде — займёшь место',
                    textAlign: TextAlign.center,
                    style: TextStyle(
                      fontSize: 9,
                      fontWeight: FontWeight.w600,
                      color: Color(0xFF9AA59D),
                    ),
                  ),
                ),
            ],
          );
        },
      ),
    );
  }
}

/// Семь точек-дней текущей недели; дни с пробежкой — лайм.
class _WeekForm extends StatelessWidget {
  final List<bool> form;

  const _WeekForm({required this.form});

  @override
  Widget build(BuildContext context) {
    final today = DateTime.now().weekday - 1;
    return Row(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        for (var i = 0; i < 7; i++) ...[
          Container(
            width: 15,
            height: 15,
            decoration: BoxDecoration(
              color: (i < form.length && form[i])
                  ? AppColors.lime
                  : const Color(0xFF31382F),
              borderRadius: BorderRadius.circular(5),
              border: i == today
                  ? Border.all(color: const Color(0xFF9AA59D), width: 1)
                  : null,
            ),
          ),
          if (i < 6) const SizedBox(width: 4),
        ],
      ],
    );
  }
}

class _PeriodToggle extends ConsumerWidget {
  const _PeriodToggle();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final period = ref.watch(leaguePeriodProvider);
    Widget seg(String value, String label) {
      final active = period == value;
      return GestureDetector(
        onTap: () => ref.read(leaguePeriodProvider.notifier).state = value,
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 160),
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
          decoration: BoxDecoration(
            color: active ? AppColors.ink : Colors.transparent,
            borderRadius: BorderRadius.circular(8),
          ),
          child: Text(
            label,
            style: TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.w600,
              color: active ? AppColors.bg : AppColors.muted,
            ),
          ),
        ),
      );
    }

    return Container(
      padding: const EdgeInsets.all(3),
      decoration: BoxDecoration(
        color: AppColors.paper,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: AppColors.line),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          seg('week', 'Неделя'),
          seg('month', 'Месяц'),
          seg('q90', '90 дней'),
        ],
      ),
    );
  }
}

// ── Чипы зачётов ───────────────────────────────────────────────────────────

class _HubChips extends ConsumerWidget {
  const _HubChips();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final selected = ref.watch(hubTabProvider);
    return SizedBox(
      height: 54,
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        clipBehavior: Clip.none,
        padding: const EdgeInsets.fromLTRB(20, 10, 20, 8),
        itemCount: HubTab.values.length,
        separatorBuilder: (_, __) => const SizedBox(width: 8),
        itemBuilder: (_, i) {
          final tab = HubTab.values[i];
          final active = tab == selected;
          return GestureDetector(
            onTap: () {
              ref.read(hubTabProvider.notifier).state = tab;
              final board = tab.board;
              if (board != null) {
                ref.read(leagueBoardProvider.notifier).state = board;
              }
            },
            child: AnimatedContainer(
              duration: const Duration(milliseconds: 160),
              alignment: Alignment.center,
              padding: const EdgeInsets.symmetric(horizontal: 14),
              decoration: BoxDecoration(
                color: active ? AppColors.ink : AppColors.paper,
                borderRadius: BorderRadius.circular(10),
                border: Border.all(
                  color: active ? AppColors.ink : AppColors.line,
                ),
              ),
              child: Text(
                tab.title,
                style: TextStyle(
                  fontSize: 13,
                  fontWeight: FontWeight.w700,
                  color: active ? AppColors.bg : AppColors.muted,
                ),
              ),
            ),
          );
        },
      ),
    );
  }
}

// ── Тело дивизиона (неделя: Километры/Постоянство) ─────────────────────────

class _DivisionBody extends StatelessWidget {
  final DivisionData division;
  final HubTab tab;

  const _DivisionBody({required this.division, required this.tab});

  @override
  Widget build(BuildContext context) {
    final rows = [
      for (final m in division.members)
        LeagueRow(
          id: m.userId,
          name: m.name,
          club: m.club,
          value: m.km,
          place: m.place,
          isMe: m.isMe,
        ),
    ];
    final movement = {
      for (final m in division.members) m.userId: m.movement,
    };
    final podium = rows.length >= 3;
    final listRows = podium ? rows.sublist(3) : rows;
    return SliverPadding(
      padding: const EdgeInsets.fromLTRB(20, 4, 20, 0),
      sliver: SliverList.separated(
        itemCount: listRows.length + (podium ? 1 : 0),
        separatorBuilder: (_, __) => const SizedBox(height: 8),
        itemBuilder: (_, i) {
          if (podium && i == 0) {
            return _TopThree(rows: rows.take(3).toList(), unit: 'км');
          }
          final row = listRows[podium ? i - 1 : i];
          return _HubRow(
            row: row,
            unit: 'км',
            movement: movement[row.id],
          );
        },
      ),
    );
  }
}

// ── Тело зачёта ────────────────────────────────────────────────────────────

class _BoardBody extends ConsumerWidget {
  final HubTab tab;

  const _BoardBody({required this.tab});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(leagueBoardDataProvider);
    return async.when(
      loading: () => const SliverToBoxAdapter(
        child: Padding(
          padding: EdgeInsets.only(top: 60),
          child: Center(child: CupertinoActivityIndicator()),
        ),
      ),
      error: (_, __) => const SliverToBoxAdapter(
        child: _HubMessage(
          title: 'Не удалось загрузить зачёт',
          text: 'Проверь подключение и потяни вниз, чтобы обновить.',
        ),
      ),
      data: (data) {
        if (data.needsProfile) {
          return const SliverToBoxAdapter(child: _ProfileNeeded());
        }
        if (tab == HubTab.personal) {
          return SliverToBoxAdapter(
            child: Padding(
              padding: const EdgeInsets.fromLTRB(20, 4, 20, 0),
              child: _SelfProgress(me: data.me, unit: data.unit),
            ),
          );
        }
        final rows = data.top;
        if (rows.isEmpty) {
          return const SliverToBoxAdapter(
            child: _HubMessage(
              title: 'Пока пусто',
              text:
                  'В этом периоде ещё никто не бегал. '
                  'Первая пробежка — и ты в таблице.',
            ),
          );
        }
        final podium = rows.length >= 3;
        final listRows = podium ? rows.sublist(3) : rows;
        return SliverPadding(
          padding: const EdgeInsets.fromLTRB(20, 4, 20, 0),
          sliver: SliverList.separated(
            itemCount: listRows.length + (podium ? 1 : 0),
            separatorBuilder: (_, __) => const SizedBox(height: 8),
            itemBuilder: (_, i) {
              if (podium && i == 0) {
                return _TopThree(rows: rows.take(3).toList(), unit: data.unit);
              }
              final row = listRows[podium ? i - 1 : i];
              return _HubRow(row: row, unit: data.unit);
            },
          ),
        );
      },
    );
  }
}

/// Подиум топ-3 — всегда над таблицей, когда участников не меньше трёх.
class _TopThree extends StatelessWidget {
  final List<LeagueRow> rows;
  final String unit;

  const _TopThree({required this.rows, required this.unit});

  @override
  Widget build(BuildContext context) {
    Widget slot(LeagueRow row, {required bool first}) {
      return Expanded(
        child: GestureDetector(
          behavior: HitTestBehavior.opaque,
          onTap: row.isMe
              ? null
              : () => showRivalProfileSheet(context, row, unit),
          child: Padding(
          padding: EdgeInsets.only(top: first ? 0 : 14),
          child: Column(
            children: [
              Container(
                width: first ? 34 : 28,
                height: first ? 34 : 28,
                alignment: Alignment.center,
                decoration: BoxDecoration(
                  color: first ? AppColors.lime : AppColors.soft,
                  borderRadius: BorderRadius.circular(first ? 11 : 9),
                ),
                child: Text(
                  '${row.place}',
                  style: TextStyle(
                    fontFamily: AppTheme.fontDisplay,
                    fontSize: first ? 15 : 12.5,
                    fontWeight: FontWeight.w800,
                    color: first ? const Color(0xFF171C19) : AppColors.ink,
                  ),
                ),
              ),
              const SizedBox(height: 6),
              Text(
                _shortName(row.name),
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                textAlign: TextAlign.center,
                style: TextStyle(
                  fontSize: 12.5,
                  fontWeight: row.isMe ? FontWeight.w800 : FontWeight.w600,
                  color: AppColors.ink,
                ),
              ),
              const SizedBox(height: 1),
              Text(
                _amount(row.value, unit),
                style: TextStyle(
                  fontSize: 11.5,
                  fontWeight: FontWeight.w700,
                  fontFeatures: const [FontFeature.tabularFigures()],
                  color: AppColors.muted,
                ),
              ),
            ],
          ),
          ),
        ),
      );
    }

    return Container(
      padding: const EdgeInsets.fromLTRB(12, 14, 12, 12),
      decoration: BoxDecoration(
        color: AppColors.paper,
        borderRadius: BorderRadius.circular(AppTheme.rSm),
        border: Border.all(color: AppColors.line),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          slot(rows[1], first: false),
          slot(rows[0], first: true),
          slot(rows[2], first: false),
        ],
      ),
    );
  }
}

class _HubRow extends StatelessWidget {
  final LeagueRow row;
  final String unit;

  /// Движение места за сутки (дивизион): ▲ поднялся / ▼ опустился.
  final int? movement;

  const _HubRow({required this.row, required this.unit, this.movement});

  @override
  Widget build(BuildContext context) {
    final me = row.isMe;
    return GestureDetector(
      onTap: me ? null : () => _showRivalSheet(context),
      child: Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      decoration: BoxDecoration(
        color: me ? AppColors.block : AppColors.paper,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: me ? AppColors.limeDeep : AppColors.line),
      ),
      child: Row(
        children: [
          SizedBox(
            width: 30,
            child: Text(
              '${row.place}',
              style: TextStyle(
                fontFamily: AppTheme.fontDisplay,
                fontSize: 14,
                fontWeight: FontWeight.w800,
                color: me ? AppColors.lime : AppColors.muted,
              ),
            ),
          ),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  me ? '${row.name} · Вы' : row.name,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                    fontSize: 14.5,
                    fontWeight: me ? FontWeight.w800 : FontWeight.w600,
                    color: me ? const Color(0xFFEDEFE8) : AppColors.ink,
                  ),
                ),
                if ((row.club ?? '').isNotEmpty)
                  Text(
                    row.club!,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(
                      fontSize: 12,
                      color: me ? const Color(0xFF9AA59D) : AppColors.faint,
                    ),
                  ),
              ],
            ),
          ),
          if (movement != null && movement != 0) ...[
            Text(
              movement! > 0 ? '▲${movement!}' : '▼${-movement!}',
              style: TextStyle(
                fontSize: 12,
                fontWeight: FontWeight.w800,
                color: movement! > 0 ? AppColors.limeDeep : AppColors.warm,
              ),
            ),
            const SizedBox(width: 8),
          ],
          Text(
            _amount(row.value, unit),
            style: TextStyle(
              fontSize: 14.5,
              fontWeight: FontWeight.w800,
              fontFeatures: const [FontFeature.tabularFigures()],
              color: me ? AppColors.lime : AppColors.ink,
            ),
          ),
        ],
      ),
      ),
    );
  }

  void _showRivalSheet(BuildContext context) =>
      showRivalProfileSheet(context, row, unit);
}

/// Ф5: профиль соперника — только цифры. Маршруты и кварталы скрыты
/// сознательно: чужие GPS-треки не показываем никогда.
void showRivalProfileSheet(BuildContext context, LeagueRow row, String unit) {
  showModalBottomSheet<void>(
      context: context,
      backgroundColor: AppColors.paper,
      builder: (_) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(20, 18, 20, 20),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Container(
                    width: 44,
                    height: 44,
                    alignment: Alignment.center,
                    decoration: BoxDecoration(
                      color: AppColors.soft,
                      borderRadius: BorderRadius.circular(14),
                    ),
                    child: Text(
                      row.name.isEmpty ? '?' : row.name[0].toUpperCase(),
                      style: TextStyle(
                        fontFamily: AppTheme.fontDisplay,
                        fontSize: 18,
                        fontWeight: FontWeight.w800,
                        color: AppColors.ink,
                      ),
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          row.name,
                          style: TextStyle(
                            fontFamily: AppTheme.fontDisplay,
                            fontSize: 17,
                            fontWeight: FontWeight.w800,
                            color: AppColors.ink,
                          ),
                        ),
                        if ((row.club ?? '').isNotEmpty)
                          Text(
                            row.club!,
                            style: TextStyle(
                              fontSize: 12.5,
                              color: AppColors.muted,
                            ),
                          ),
                      ],
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 14),
              Container(
                width: double.infinity,
                padding: const EdgeInsets.symmetric(
                  horizontal: 14,
                  vertical: 12,
                ),
                decoration: BoxDecoration(
                  color: AppColors.soft,
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Text(
                  '#${row.place} в зачёте · ${_amount(row.value, unit)}',
                  style: TextStyle(
                    fontSize: 14,
                    fontWeight: FontWeight.w800,
                    color: AppColors.ink,
                  ),
                ),
              ),
              const SizedBox(height: 10),
              Text(
                'Маршруты и кварталы соперника скрыты — в Лиге видны '
                'только цифры. Твои треки другим тоже не видны.',
                style: TextStyle(
                  fontSize: 12.5,
                  height: 1.45,
                  color: AppColors.faint,
                ),
              ),
            ],
          ),
        ),
      ),
    );
}

/// «Прогресс» — ты против себя в прошлом периоде: зачёт, где выигрывают все.
class _SelfProgress extends StatelessWidget {
  final LeagueMe me;
  final String unit;

  const _SelfProgress({required this.me, required this.unit});

  @override
  Widget build(BuildContext context) {
    final delta = me.delta ?? 0;
    final sign = delta > 0 ? '+' : '';
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        color: AppColors.paper,
        borderRadius: BorderRadius.circular(AppTheme.rSm),
        border: Border.all(color: AppColors.line),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            '${_fmt(me.value)} $unit',
            style: Theme.of(
              context,
            ).textTheme.headlineMedium?.copyWith(fontWeight: FontWeight.w800),
          ),
          const SizedBox(height: 4),
          Text(
            '${me.runs ?? 0} ${_plural(me.runs ?? 0, 'пробежка', 'пробежки', 'пробежек')} за период',
            style: Theme.of(
              context,
            ).textTheme.bodySmall?.copyWith(color: AppColors.muted),
          ),
          const SizedBox(height: 16),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
            decoration: BoxDecoration(
              color: AppColors.soft,
              borderRadius: BorderRadius.circular(10),
            ),
            child: Row(
              children: [
                Icon(
                  me.improved ? Icons.trending_up : Icons.trending_flat,
                  size: 18,
                  color: me.improved ? AppColors.success : AppColors.muted,
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    me.improved
                        ? 'Лучше прошлого периода на $sign${_fmt(delta)} $unit'
                        : 'В прошлом периоде было ${_fmt(me.prevValue ?? 0)} $unit',
                    style: TextStyle(fontSize: 13, color: AppColors.ink),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _ProfileNeeded extends ConsumerWidget {
  const _ProfileNeeded();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(20, 4, 20, 0),
      child: Container(
        padding: const EdgeInsets.all(18),
        decoration: BoxDecoration(
          color: AppColors.paper,
          borderRadius: BorderRadius.circular(AppTheme.rSm),
          border: Border.all(color: AppColors.line),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Своя лига',
              style: Theme.of(
                context,
              ).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w800),
            ),
            const SizedBox(height: 8),
            Text(
              'Здесь ты соревнуешься только с ровесниками своего пола. '
              'Чтобы собрать твою группу, нужны год рождения и пол — '
              'больше ничего.',
              style: TextStyle(
                fontSize: 14,
                color: AppColors.muted,
                height: 1.45,
              ),
            ),
            const SizedBox(height: 16),
            SizedBox(
              width: double.infinity,
              child: FilledButton(
                onPressed: () => showRunnerProfileSheet(context, ref),
                child: const Text('Заполнить'),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _HubMessage extends StatelessWidget {
  final String title;
  final String text;

  const _HubMessage({required this.title, required this.text});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(20, 4, 20, 0),
      child: Container(
        width: double.infinity,
        padding: const EdgeInsets.all(18),
        decoration: BoxDecoration(
          color: AppColors.paper,
          borderRadius: BorderRadius.circular(AppTheme.rSm),
          border: Border.all(color: AppColors.line),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              title,
              style: Theme.of(
                context,
              ).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700),
            ),
            const SizedBox(height: 6),
            Text(
              text,
              style: TextStyle(
                fontSize: 14,
                color: AppColors.muted,
                height: 1.45,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

// ── Тропы ──────────────────────────────────────────────────────────────────

class _TrailsBody extends ConsumerWidget {
  const _TrailsBody();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(trailsProvider);
    return async.when(
      loading: () => const SliverToBoxAdapter(
        child: Padding(
          padding: EdgeInsets.only(top: 60),
          child: Center(child: CupertinoActivityIndicator()),
        ),
      ),
      error: (_, __) => const SliverToBoxAdapter(
        child: _HubMessage(
          title: 'Не удалось загрузить тропы',
          text: 'Проверь подключение и потяни вниз, чтобы обновить.',
        ),
      ),
      data: (trails) {
        if (trails.isEmpty) {
          return const SliverToBoxAdapter(
            child: _HubMessage(
              title: 'Пока нет троп',
              text:
                  'Тропа — это отрезок, где бегуны меряются временем. '
                  'Пробеги маршрут — сервер сам заметит прохождение.',
            ),
          );
        }
        final mine = trails.where((t) => t.attemptedByMe).length;
        return SliverPadding(
          padding: const EdgeInsets.fromLTRB(20, 4, 20, 0),
          sliver: SliverList.separated(
            itemCount: trails.length + 1,
            separatorBuilder: (_, __) => const SizedBox(height: 8),
            itemBuilder: (_, i) {
              if (i == 0) {
                return Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 14,
                    vertical: 12,
                  ),
                  decoration: BoxDecoration(
                    color: AppColors.block,
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: Row(
                    children: [
                      const Expanded(
                        child: Text(
                          'Троп пройдено',
                          style: TextStyle(
                            fontSize: 13,
                            fontWeight: FontWeight.w600,
                            color: Color(0xFF9AA59D),
                          ),
                        ),
                      ),
                      Text(
                        '$mine из ${trails.length}',
                        style: const TextStyle(
                          fontFamily: AppTheme.fontDisplay,
                          fontSize: 14,
                          fontWeight: FontWeight.w800,
                          color: AppColors.lime,
                        ),
                      ),
                    ],
                  ),
                );
              }
              final trail = trails[i - 1];
              return _TrailRow(trail: trail);
            },
          ),
        );
      },
    );
  }
}

class _TrailRow extends StatelessWidget {
  final Trail trail;

  const _TrailRow({required this.trail});

  @override
  Widget build(BuildContext context) {
    final city = trail.city;
    final leader = trail.frequentLeaderName;
    final meta = [
      trail.lengthLabel,
      if (city != null && city.isNotEmpty) city,
      if (trail.myBestS != null)
        'твоё лучшее ${formatDuration(trail.myBestS!)}'
      else if (trail.attemptedByMe)
        'ты здесь бегал',
      if (leader != null)
        trail.frequentLeaderIsMe ? 'чаще всех: ты' : 'чаще всех: $leader',
    ].join(' · ');
    return Material(
      color: AppColors.paper,
      borderRadius: BorderRadius.circular(12),
      child: InkWell(
        onTap: () => context.push('/trails/detail', extra: trail),
        borderRadius: BorderRadius.circular(12),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(12),
            border: Border.all(
              color: trail.attemptedByMe ? AppColors.limeDeep : AppColors.line,
            ),
          ),
          child: Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      trail.name,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(
                        fontSize: 14.5,
                        fontWeight: FontWeight.w700,
                        color: AppColors.ink,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      meta,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(fontSize: 12, color: AppColors.faint),
                    ),
                  ],
                ),
              ),
              Icon(
                CupertinoIcons.chevron_right,
                size: 16,
                color: AppColors.faint,
              ),
            ],
          ),
        ),
      ),
    );
  }
}

// ── Мелочи ─────────────────────────────────────────────────────────────────

String _fmt(double v) =>
    v == v.roundToDouble() ? v.toStringAsFixed(0) : v.toStringAsFixed(1);

String _amount(double value, String unit) {
  final text = _fmt(value);
  if (unit == 'пробежек') {
    return '$text ${_plural(value.round(), 'пробежка', 'пробежки', 'пробежек')}';
  }
  return '$text $unit';
}

/// «Иван Быстрый» → «Иван Б.» — подиум не режет имена многоточием.
String _shortName(String name) {
  final parts = name.trim().split(RegExp(r'\s+'));
  if (parts.length < 2 || parts[0].length > 10) return name;
  return '${parts[0]} ${parts[1][0]}.';
}

String _plural(int n, String one, String few, String many) {
  final mod100 = n % 100;
  if (mod100 >= 11 && mod100 <= 14) return many;
  return switch (n % 10) {
    1 => one,
    2 || 3 || 4 => few,
    _ => many,
  };
}
