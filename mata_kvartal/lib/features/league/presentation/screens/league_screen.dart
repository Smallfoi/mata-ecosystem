import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../../core/theme/app_colors.dart';
import '../../../../shared/widgets/tab_visibility.dart';
import '../../data/league_provider.dart';

/// Экран «Лига» — пять зачётов на одних и тех же пробежках.
///
/// Главное правило стратегии: проигравших нет. Поэтому в каждом зачёте на первом
/// месте стоит не таблица, а строка «ты обошёл N из M» — она работает и для того,
/// кто никогда не будет первым.
class LeagueScreen extends ConsumerStatefulWidget {
  const LeagueScreen({super.key});

  @override
  ConsumerState<LeagueScreen> createState() => _LeagueScreenState();
}

class _LeagueScreenState extends ConsumerState<LeagueScreen> with TabVisibility {
  @override
  void onTabShown() {
    // Вернулись на вкладку — перечитываем: экран живёт, сам не обновится.
    ref.invalidate(leagueBoardDataProvider);
    ref.invalidate(runnerProfileProvider);
  }

  @override
  Widget build(BuildContext context) {
    final board = ref.watch(leagueBoardProvider);
    final async = ref.watch(leagueBoardDataProvider);

    return Scaffold(
      backgroundColor: AppColors.bg,
      body: SafeArea(
        child: Column(
          children: [
            const _Header(),
            Expanded(
              child: RefreshIndicator(
                onRefresh: () async => ref.invalidate(leagueBoardDataProvider),
                child: async.when(
                  loading: () => const Center(child: CupertinoActivityIndicator()),
                  error: (_, __) => const _Message(
                    title: 'Не удалось загрузить зачёт',
                    text: 'Проверьте подключение и потяните вниз, чтобы обновить.',
                  ),
                  data: (data) => _BoardView(board: board, data: data),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

// ── Шапка: заголовок, период, список зачётов ───────────────────────────────

class _Header extends ConsumerWidget {
  const _Header();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final board = ref.watch(leagueBoardProvider);
    final period = ref.watch(leaguePeriodProvider);
    return Padding(
      padding: const EdgeInsets.fromLTRB(20, 16, 20, 10),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [
              Expanded(
                child: Text(
                  'Лига',
                  style: Theme.of(context).textTheme.headlineMedium
                      ?.copyWith(fontWeight: FontWeight.w800, height: 1.1),
                ),
              ),
              _PeriodToggle(period: period),
            ],
          ),
          const SizedBox(height: 4),
          // Подсказка идёт отдельной строкой во всю ширину: рядом с переключателем
          // периода она ломалась на четыре строки и выглядела зажатой.
          Text(
            board.hint,
            style: Theme.of(context).textTheme.bodySmall
                ?.copyWith(color: AppColors.textTertiary),
          ),
          const SizedBox(height: 12),
          const _BoardPicker(),
        ],
      ),
    );
  }
}

class _PeriodToggle extends ConsumerWidget {
  final String period;
  const _PeriodToggle({required this.period});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    Widget seg(String value, String label) {
      final active = period == value;
      return GestureDetector(
        onTap: () => ref.read(leaguePeriodProvider.notifier).state = value,
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 160),
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
          decoration: BoxDecoration(
            color: active ? AppColors.electricBlue : Colors.transparent,
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
        color: AppColors.bgElevated,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: AppColors.separator),
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

class _BoardPicker extends ConsumerWidget {
  const _BoardPicker();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final selected = ref.watch(leagueBoardProvider);
    return SizedBox(
      height: 36,
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        clipBehavior: Clip.none,
        padding: const EdgeInsets.only(right: 4),
        itemCount: LeagueBoard.values.length,
        separatorBuilder: (_, __) => const SizedBox(width: 8),
        itemBuilder: (_, i) {
          final board = LeagueBoard.values[i];
          final active = board == selected;
          return GestureDetector(
            onTap: () => ref.read(leagueBoardProvider.notifier).state = board,
            child: AnimatedContainer(
              duration: const Duration(milliseconds: 160),
              alignment: Alignment.center,
              padding: const EdgeInsets.symmetric(horizontal: 14),
              decoration: BoxDecoration(
                color: active ? AppColors.ink : AppColors.bgElevated,
                borderRadius: BorderRadius.circular(10),
                border: Border.all(
                  color: active ? AppColors.ink : AppColors.separator,
                ),
              ),
              child: Text(
                board.title,
                style: TextStyle(
                  fontSize: 13,
                  fontWeight: FontWeight.w600,
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

// ── Тело зачёта ────────────────────────────────────────────────────────────

class _BoardView extends StatelessWidget {
  final LeagueBoard board;
  final LeagueBoardData data;
  const _BoardView({required this.board, required this.data});

  @override
  Widget build(BuildContext context) {
    if (data.needsProfile) {
      return ListView(
        padding: const EdgeInsets.fromLTRB(20, 8, 20, 24),
        children: const [_ProfilePrompt()],
      );
    }

    if (board == LeagueBoard.personal) {
      return ListView(
        padding: const EdgeInsets.fromLTRB(20, 8, 20, 24),
        children: [_PersonalCard(me: data.me, unit: data.unit)],
      );
    }

    final rows = data.top;
    return ListView.separated(
      padding: const EdgeInsets.fromLTRB(20, 8, 20, 24),
      itemCount: rows.length + 1,
      separatorBuilder: (_, __) => const SizedBox(height: 8),
      itemBuilder: (_, i) {
        if (i == 0) {
          return Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _MyPlaceCard(me: data.me, unit: data.unit, groupLabel: data.groupLabel),
              const SizedBox(height: 14),
              if (rows.isEmpty)
                const _Message(
                  title: 'Пока пусто',
                  text: 'В этом периоде ещё никто не бегал. Первая пробежка — и ты в таблице.',
                ),
            ],
          );
        }
        return _Row(row: rows[i - 1], unit: data.unit);
      },
    );
  }
}

/// Моё место. Сначала — сколько человек позади, потом уже место в таблице.
class _MyPlaceCard extends StatelessWidget {
  final LeagueMe me;
  final String unit;
  final String? groupLabel;
  const _MyPlaceCard({required this.me, required this.unit, this.groupLabel});

  @override
  Widget build(BuildContext context) {
    final hasPlace = me.place != null;
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: AppColors.panel,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppColors.separator),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (groupLabel != null) ...[
            Text(
              groupLabel!.toUpperCase(),
              style: TextStyle(
                fontSize: 11,
                letterSpacing: 1.2,
                fontWeight: FontWeight.w700,
                color: AppColors.accentInk,
              ),
            ),
            const SizedBox(height: 8),
          ],
          Text(
            hasPlace
                ? 'Ты обошёл ${me.aheadOf} из ${me.of}'
                : 'В этом периоде пробежек ещё нет',
            style: Theme.of(context).textTheme.titleMedium
                ?.copyWith(fontWeight: FontWeight.w800),
          ),
          const SizedBox(height: 6),
          Text(
            hasPlace
                ? '${me.place} место · ${_amount(me.value, unit)}'
                : 'Пробеги — и появишься в таблице',
            style: Theme.of(context).textTheme.bodySmall
                ?.copyWith(color: AppColors.muted),
          ),
          if (me.behindNext != null && me.behindNext! > 0) ...[
            const SizedBox(height: 6),
            Text(
              'До следующего места ${_amount(me.behindNext!, unit)}',
              style: TextStyle(fontSize: 12, color: AppColors.accentInk),
            ),
          ],
        ],
      ),
    );
  }
}

/// «Мой прогресс»: сравнение с собой в прошлом периоде — зачёт, где выигрывают все.
class _PersonalCard extends StatelessWidget {
  final LeagueMe me;
  final String unit;
  const _PersonalCard({required this.me, required this.unit});

  @override
  Widget build(BuildContext context) {
    final delta = me.delta ?? 0;
    final sign = delta > 0 ? '+' : '';
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        color: AppColors.panel,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppColors.separator),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            '${_fmt(me.value)} $unit',
            style: Theme.of(context).textTheme.headlineMedium
                ?.copyWith(fontWeight: FontWeight.w800),
          ),
          const SizedBox(height: 4),
          Text(
            '${me.runs ?? 0} ${_plural(me.runs ?? 0, 'пробежка', 'пробежки', 'пробежек')} за период',
            style: Theme.of(context).textTheme.bodySmall
                ?.copyWith(color: AppColors.muted),
          ),
          const SizedBox(height: 16),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
            decoration: BoxDecoration(
              color: me.improved ? AppColors.soft : AppColors.bg,
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

class _Row extends StatelessWidget {
  final LeagueRow row;
  final String unit;
  const _Row({required this.row, required this.unit});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      decoration: BoxDecoration(
        color: row.isMe ? AppColors.soft : AppColors.panel,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(
          color: row.isMe ? AppColors.accent : AppColors.separator,
        ),
      ),
      child: Row(
        children: [
          SizedBox(
            width: 28,
            child: Text(
              '${row.place}',
              style: TextStyle(
                fontSize: 15,
                fontWeight: FontWeight.w800,
                color: AppColors.muted,
              ),
            ),
          ),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  row.name,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w600),
                ),
                if ((row.club ?? '').isNotEmpty)
                  Text(
                    row.club!,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(fontSize: 12, color: AppColors.textTertiary),
                  ),
              ],
            ),
          ),
          Text(
            _amount(row.value, unit),
            style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700),
          ),
        ],
      ),
    );
  }
}

/// «Своя лига» без года рождения и пола не работает — сравнивать не с кем.
/// Просим заполнить здесь, а не на входе в приложение: на входе это отсекает людей.
class _ProfilePrompt extends ConsumerWidget {
  const _ProfilePrompt();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        color: AppColors.panel,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppColors.separator),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Своя лига',
            style: Theme.of(context).textTheme.titleMedium
                ?.copyWith(fontWeight: FontWeight.w800),
          ),
          const SizedBox(height: 8),
          Text(
            'Здесь ты соревнуешься только с ровесниками своего пола. Чтобы собрать '
            'твою группу, нужны год рождения и пол — больше ничего.',
            style: TextStyle(fontSize: 14, color: AppColors.muted, height: 1.45),
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
    );
  }
}

class _Message extends StatelessWidget {
  final String title;
  final String text;
  const _Message({required this.title, required this.text});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        color: AppColors.panel,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppColors.separator),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            title,
            style: Theme.of(context).textTheme.titleMedium
                ?.copyWith(fontWeight: FontWeight.w700),
          ),
          const SizedBox(height: 6),
          Text(
            text,
            style: TextStyle(fontSize: 14, color: AppColors.muted, height: 1.45),
          ),
        ],
      ),
    );
  }
}

// ── Профиль бегуна ─────────────────────────────────────────────────────────

/// Год рождения выбираем барабаном, а не полем ввода: это правило владельца для
/// любых чисел и дат в наших приложениях.
Future<void> showRunnerProfileSheet(BuildContext context, WidgetRef ref) async {
  final profile = await ref.read(runnerProfileProvider.future);
  if (!context.mounted) return;

  final thisYear = DateTime.now().year;
  const oldest = 90; // 90 лет — верхняя граница списка, ниже юниоры
  int year = profile.birthYear ?? (thisYear - 30);
  String gender = profile.gender ?? '';

  await showModalBottomSheet<void>(
    context: context,
    backgroundColor: AppColors.paper,
    isScrollControlled: true,
    shape: const RoundedRectangleBorder(
      borderRadius: BorderRadius.vertical(top: Radius.circular(18)),
    ),
    builder: (sheetContext) => StatefulBuilder(
      builder: (context, setSheetState) {
        Widget genderSeg(String value, String label) {
          final active = gender == value;
          return Expanded(
            child: GestureDetector(
              onTap: () => setSheetState(() => gender = value),
              child: AnimatedContainer(
                duration: const Duration(milliseconds: 150),
                alignment: Alignment.center,
                padding: const EdgeInsets.symmetric(vertical: 12),
                decoration: BoxDecoration(
                  color: active ? AppColors.ink : AppColors.panel,
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(
                    color: active ? AppColors.ink : AppColors.separator,
                  ),
                ),
                child: Text(
                  label,
                  style: TextStyle(
                    fontSize: 14,
                    fontWeight: FontWeight.w600,
                    color: active ? AppColors.bg : AppColors.muted,
                  ),
                ),
              ),
            ),
          );
        }

        return SafeArea(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(20, 16, 20, 20),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Профиль бегуна',
                  style: Theme.of(context).textTheme.titleLarge
                      ?.copyWith(fontWeight: FontWeight.w800),
                ),
                const SizedBox(height: 4),
                Text(
                  'Нужны только для того, чтобы собрать твою группу сравнения.',
                  style: TextStyle(fontSize: 13, color: AppColors.muted),
                ),
                const SizedBox(height: 18),
                const Text(
                  'Год рождения',
                  style: TextStyle(fontSize: 13, fontWeight: FontWeight.w700),
                ),
                SizedBox(
                  height: 150,
                  child: CupertinoPicker(
                    itemExtent: 34,
                    scrollController: FixedExtentScrollController(
                      initialItem: thisYear - year,
                    ),
                    onSelectedItemChanged: (i) =>
                        setSheetState(() => year = thisYear - i),
                    children: [
                      for (var y = thisYear; y >= thisYear - oldest; y--)
                        Center(child: Text('$y', style: const TextStyle(fontSize: 20))),
                    ],
                  ),
                ),
                const SizedBox(height: 12),
                const Text(
                  'Пол',
                  style: TextStyle(fontSize: 13, fontWeight: FontWeight.w700),
                ),
                const SizedBox(height: 8),
                Row(
                  children: [
                    genderSeg('m', 'Мужской'),
                    const SizedBox(width: 10),
                    genderSeg('f', 'Женский'),
                  ],
                ),
                const SizedBox(height: 20),
                SizedBox(
                  width: double.infinity,
                  child: FilledButton(
                    onPressed: gender.isEmpty
                        ? null
                        : () async {
                            await saveRunnerProfile(
                              ref,
                              birthYear: year,
                              gender: gender,
                            );
                            if (sheetContext.mounted) {
                              Navigator.of(sheetContext).pop();
                            }
                          },
                    child: const Text('Сохранить'),
                  ),
                ),
              ],
            ),
          ),
        );
      },
    ),
  );
}

// ── Мелочи ─────────────────────────────────────────────────────────────────

String _fmt(double v) =>
    v == v.roundToDouble() ? v.toStringAsFixed(0) : v.toStringAsFixed(1);

/// «3 пробежек» — так не говорят. Число и единицу показываем вместе, чтобы
/// склонение было по числу, а не по строке с сервера.
String _amount(double value, String unit) {
  final text = _fmt(value);
  if (unit == 'пробежек') {
    return '$text ${_plural(value.round(), 'пробежка', 'пробежки', 'пробежек')}';
  }
  return '$text $unit';
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
