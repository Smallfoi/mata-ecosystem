import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../../core/theme/app_colors.dart';
import '../../../../shared/widgets/tab_visibility.dart';
import '../../data/trails_provider.dart';

/// Список троп: где человек уже бегал и что есть рядом.
class TrailsScreen extends ConsumerStatefulWidget {
  const TrailsScreen({super.key});

  @override
  ConsumerState<TrailsScreen> createState() => _TrailsScreenState();
}

class _TrailsScreenState extends ConsumerState<TrailsScreen> with TabVisibility {
  @override
  void onTabShown() => ref.invalidate(trailsProvider);

  @override
  Widget build(BuildContext context) {
    final async = ref.watch(trailsProvider);
    return Scaffold(
      backgroundColor: AppColors.bg,
      body: SafeArea(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 16, 20, 4),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    'Тропы',
                    style: Theme.of(context).textTheme.headlineMedium
                        ?.copyWith(fontWeight: FontWeight.w800, height: 1.1),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    'Участки, по которым бегают регулярно. Пробежал — прохождение '
                    'засчитается само.',
                    style: TextStyle(fontSize: 14, color: AppColors.muted, height: 1.4),
                  ),
                ],
              ),
            ),
            Expanded(
              child: RefreshIndicator(
                onRefresh: () async => ref.invalidate(trailsProvider),
                child: async.when(
                  loading: () => const Center(child: CupertinoActivityIndicator()),
                  error: (_, __) => _message(
                    context,
                    'Не удалось загрузить тропы',
                    'Проверьте подключение и потяните вниз.',
                  ),
                  data: (items) => items.isEmpty
                      ? _message(
                          context,
                          'Троп пока нет',
                          'Тропы появятся, когда их отметят бегуны или клубы. '
                          'Твои пробежки на них засчитаются автоматически.',
                        )
                      : ListView.separated(
                          padding: const EdgeInsets.fromLTRB(20, 12, 20, 24),
                          itemCount: items.length,
                          separatorBuilder: (_, __) => const SizedBox(height: 10),
                          itemBuilder: (_, i) => _TrailCard(trail: items[i]),
                        ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _message(BuildContext context, String title, String text) => ListView(
    padding: const EdgeInsets.fromLTRB(20, 12, 20, 24),
    children: [
      Container(
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
      ),
    ],
  );
}

class _TrailCard extends StatelessWidget {
  final Trail trail;
  const _TrailCard({required this.trail});

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: () => context.push('/trails/detail', extra: trail),
      child: Container(
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: AppColors.panel,
          borderRadius: BorderRadius.circular(14),
          border: Border.all(
            color: trail.attemptedByMe ? AppColors.accent : AppColors.separator,
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
                    style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
                  ),
                  const SizedBox(height: 3),
                  Text(
                    [
                      trail.lengthLabel,
                      if ((trail.city ?? '').isNotEmpty) trail.city!,
                      if (trail.attemptedByMe) 'ты здесь бегал',
                      if (trail.createdByMe) 'твоя тропа',
                    ].join(' · '),
                    style: TextStyle(fontSize: 13, color: AppColors.muted),
                  ),
                ],
              ),
            ),
            Icon(Icons.chevron_right, color: AppColors.muted),
          ],
        ),
      ),
    );
  }
}

/// Тропа: четыре доски — у каждой свой победитель, как и в лиге.
class TrailDetailScreen extends ConsumerWidget {
  final Trail trail;
  const TrailDetailScreen({super.key, required this.trail});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final board = ref.watch(trailBoardProvider);
    final async = ref.watch(trailBoardDataProvider(trail.id));

    return Scaffold(
      backgroundColor: AppColors.bg,
      appBar: AppBar(
        backgroundColor: AppColors.bg,
        elevation: 0,
        title: Text(trail.name, style: const TextStyle(fontWeight: FontWeight.w700)),
      ),
      body: SafeArea(
        top: false,
        child: Column(
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 4, 20, 12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    '${trail.lengthLabel} · ${board.hint}',
                    style: TextStyle(fontSize: 13, color: AppColors.muted),
                  ),
                  const SizedBox(height: 12),
                  SizedBox(
                    height: 36,
                    child: ListView.separated(
                      scrollDirection: Axis.horizontal,
                      itemCount: TrailBoard.values.length,
                      separatorBuilder: (_, __) => const SizedBox(width: 8),
                      itemBuilder: (_, i) {
                        final b = TrailBoard.values[i];
                        final active = b == board;
                        return GestureDetector(
                          onTap: () =>
                              ref.read(trailBoardProvider.notifier).state = b,
                          child: AnimatedContainer(
                            duration: const Duration(milliseconds: 160),
                            alignment: Alignment.center,
                            padding: const EdgeInsets.symmetric(horizontal: 14),
                            decoration: BoxDecoration(
                              color: active ? AppColors.ink : AppColors.panel,
                              borderRadius: BorderRadius.circular(10),
                              border: Border.all(
                                color: active ? AppColors.ink : AppColors.separator,
                              ),
                            ),
                            child: Text(
                              b.title,
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
                  ),
                ],
              ),
            ),
            Expanded(
              child: async.when(
                loading: () => const Center(child: CupertinoActivityIndicator()),
                error: (_, __) => Center(
                  child: Text(
                    'Не удалось загрузить доску',
                    style: TextStyle(color: AppColors.muted),
                  ),
                ),
                data: (data) => _BoardBody(trail: trail, data: data),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _BoardBody extends StatelessWidget {
  final Trail trail;
  final TrailBoardData data;
  const _BoardBody({required this.trail, required this.data});

  @override
  Widget build(BuildContext context) {
    if (data.needsProfile) {
      return _card(
        context,
        'Своя лига',
        'Здесь ты соревнуешься только с ровесниками своего пола. Заполни год '
        'рождения и пол в зачёте «Своя лига» на экране лиги — и группа соберётся.',
      );
    }

    if (data.board == TrailBoard.mine) {
      if (data.attempts.isEmpty) {
        return _card(
          context,
          'Ты здесь ещё не бегал',
          'Пробеги по этой тропе — прохождение засчитается само, отмечать ничего не нужно.',
        );
      }
      return ListView.separated(
        padding: const EdgeInsets.fromLTRB(20, 4, 20, 24),
        itemCount: data.attempts.length + 1,
        separatorBuilder: (_, __) => const SizedBox(height: 8),
        itemBuilder: (_, i) {
          if (i == 0) {
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
                  Text(
                    'Личный рекорд ${formatDuration(data.myBest ?? 0)}',
                    style: Theme.of(context).textTheme.titleMedium
                        ?.copyWith(fontWeight: FontWeight.w800),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    'Прохождений: ${data.myAttempts}',
                    style: TextStyle(fontSize: 14, color: AppColors.muted),
                  ),
                ],
              ),
            );
          }
          final a = data.attempts[i - 1];
          final d = DateTime.fromMillisecondsSinceEpoch(a.startedAtMs);
          final best = a.durationS == data.myBest;
          return Container(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
            decoration: BoxDecoration(
              color: best ? AppColors.soft : AppColors.panel,
              borderRadius: BorderRadius.circular(12),
              border: Border.all(
                color: best ? AppColors.accent : AppColors.separator,
              ),
            ),
            child: Row(
              children: [
                Expanded(
                  child: Text(
                    '${d.day.toString().padLeft(2, '0')}.${d.month.toString().padLeft(2, '0')}.${d.year}',
                    style: const TextStyle(fontSize: 15),
                  ),
                ),
                Text(
                  formatDuration(a.durationS),
                  style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700),
                ),
              ],
            ),
          );
        },
      );
    }

    if (data.top.isEmpty) {
      return _card(
        context,
        'Пока пусто',
        'На этой тропе ещё нет прохождений. Первое может быть твоим.',
      );
    }

    return ListView.separated(
      padding: const EdgeInsets.fromLTRB(20, 4, 20, 24),
      itemCount: data.top.length + 1,
      separatorBuilder: (_, __) => const SizedBox(height: 8),
      itemBuilder: (_, i) {
        if (i == 0) {
          final hasPlace = data.place != null;
          return Container(
            width: double.infinity,
            padding: const EdgeInsets.all(16),
            margin: const EdgeInsets.only(bottom: 6),
            decoration: BoxDecoration(
              color: AppColors.panel,
              borderRadius: BorderRadius.circular(14),
              border: Border.all(color: AppColors.separator),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  hasPlace
                      ? 'Ты обошёл ${data.aheadOf} из ${data.of}'
                      : 'Ты здесь ещё не бегал',
                  style: Theme.of(context).textTheme.titleMedium
                      ?.copyWith(fontWeight: FontWeight.w800),
                ),
                const SizedBox(height: 4),
                Text(
                  hasPlace
                      ? '${data.place} место · ${_value(data.value ?? 0, data.unit)}'
                      : 'Пробеги тропу — попадёшь в таблицу',
                  style: TextStyle(fontSize: 14, color: AppColors.muted),
                ),
              ],
            ),
          );
        }
        final row = data.top[i - 1];
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
                        style: TextStyle(
                          fontSize: 12,
                          color: AppColors.textTertiary,
                        ),
                      ),
                  ],
                ),
              ),
              Text(
                _value(row.value, data.unit),
                style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700),
              ),
            ],
          ),
        );
      },
    );
  }

  /// Время показываем как время, а не как число секунд.
  static String _value(int v, String unit) =>
      unit == 'с' ? formatDuration(v) : '$v $unit';

  Widget _card(BuildContext context, String title, String text) => ListView(
    padding: const EdgeInsets.fromLTRB(20, 4, 20, 24),
    children: [
      Container(
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
      ),
    ],
  );
}
