import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mata_ui/mata_ui.dart';

import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_states.dart';
import '../data/blocks_summary_provider.dart';

/// «Мои кварталы» (D-74, Ф3б + Ф4).
///
/// Отвечает на три вопроса: сколько города моё в этом сезоне и сколько до конца
/// сезона; где мой дом (несгораемый квартал); кто держит районы и какой клуб
/// впереди. Захват — режим, а не главное обещание Квартала (владелец 17.09),
/// поэтому экран спокойный: цифры и списки, без игровых эффектов.
class BlocksScreen extends ConsumerWidget {
  const BlocksScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(blocksSummaryProvider);
    return Scaffold(
      backgroundColor: AppColors.bg,
      appBar: AppBar(
        backgroundColor: AppColors.bg,
        surfaceTintColor: Colors.transparent,
        title: const Text('Мои кварталы'),
      ),
      body: RefreshIndicator(
        onRefresh: () async => ref.invalidate(blocksSummaryProvider),
        child: async.when(
          loading: () => const MataLoading(),
          error: (_, __) => _scrollable(
            MataError(
              title: 'Не удалось загрузить кварталы',
              titleStyle: AppStates.title,
              hint: 'Проверьте подключение.',
              hintStyle: AppStates.hint,
              iconColor: AppStates.icon,
              retryLabel: 'Повторить',
              onRetry: () => ref.invalidate(blocksSummaryProvider),
              retryBuilder: AppStates.retry,
            ),
          ),
          data: (s) => s == null
              ? _scrollable(
                  MataEmpty(
                    icon: CupertinoIcons.person_crop_circle,
                    iconColor: AppStates.icon,
                    title: 'Войдите в аккаунт',
                    titleStyle: AppStates.title,
                    hint: 'Кварталы привязаны к аккаунту.',
                    hintStyle: AppStates.hint,
                  ),
                )
              : _Body(summary: s),
        ),
      ),
    );
  }

  static Widget _scrollable(Widget child) => ListView(
    physics: const AlwaysScrollableScrollPhysics(),
    children: [const SizedBox(height: 60), child],
  );
}

class _Body extends StatelessWidget {
  final BlocksSummary summary;
  const _Body({required this.summary});

  @override
  Widget build(BuildContext context) {
    final s = summary;
    // Свои районы сверху; «Без района» (окраины без имени в OSM) — всегда в конце.
    const noName = 'Без района';
    final districts = [...s.districts]
      ..sort((a, b) {
        if ((a.district == noName) != (b.district == noName)) {
          return a.district == noName ? 1 : -1;
        }
        return b.mine != a.mine
            ? b.mine.compareTo(a.mine)
            : a.district.compareTo(b.district);
      });
    return ListView(
      physics: const AlwaysScrollableScrollPhysics(),
      // Снизу — место под плавающую кнопку «Бег» таб-бара.
      padding: const EdgeInsets.fromLTRB(20, 8, 20, 120),
      children: [
        _ScoreCard(summary: s),
        const SizedBox(height: 12),
        _HomeCard(home: s.home),
        const SizedBox(height: 24),
        const _SectionTitle(
          'Районы',
          'Квартал твой до конца месяца. Лидер района — у кого больше кварталов в сезоне.',
        ),
        const SizedBox(height: 10),
        for (final d in districts) ...[
          _DistrictRow(d: d),
          const SizedBox(height: 8),
        ],
        const SizedBox(height: 16),
        const _SectionTitle(
          'Клубы',
          'Кварталы участников клуба складываются. Домашние кварталы не считаются.',
        ),
        const SizedBox(height: 10),
        if (s.clubs.isEmpty)
          _Note(
            s.inClub
                ? 'В этом сезоне клубы ещё не взяли ни одного квартала. Ваш может стать первым.'
                : 'В этом сезоне клубы ещё не взяли ни одного квартала. Вступите в клуб, чтобы играть командой.',
          )
        else
          for (final c in s.clubs) ...[
            _ClubRow(c: c),
            const SizedBox(height: 8),
          ],
      ],
    );
  }
}

class _ScoreCard extends StatelessWidget {
  final BlocksSummary summary;
  const _ScoreCard({required this.summary});

  @override
  Widget build(BuildContext context) {
    final s = summary;
    final days = s.daysLeft(DateTime.now());
    final pct = s.cityPercent.toStringAsFixed(s.cityPercent >= 10 ? 0 : 1)
        .replaceAll('.', ',');
    return _Panel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Сезон · ${days <= 1 ? 'последний день' : 'ещё ${_days(days)}'}',
            style: TextStyle(fontSize: 13, color: AppColors.muted),
          ),
          const SizedBox(height: 6),
          Text.rich(
            TextSpan(
              children: [
                TextSpan(
                  text: '${s.mine}',
                  style: TextStyle(
                    fontSize: 34,
                    fontWeight: FontWeight.w800,
                    color: AppColors.ink,
                    fontFeatures: const [FontFeature.tabularFigures()],
                  ),
                ),
                TextSpan(
                  text: ' из ${s.total}',
                  style: TextStyle(fontSize: 18, color: AppColors.muted),
                ),
              ],
            ),
          ),
          const SizedBox(height: 4),
          Text(
            s.mine == 0
                ? 'Пока ни одного. Замкните круг вокруг квартала в режиме «Захват» — он станет вашим.'
                : '$pct% города',
            style: TextStyle(fontSize: 14, color: AppColors.ink, height: 1.35),
          ),
          const SizedBox(height: 12),
          ClipRRect(
            borderRadius: BorderRadius.circular(4),
            child: LinearProgressIndicator(
              value: s.total == 0 ? 0 : s.mine / s.total,
              minHeight: 6,
              backgroundColor: AppColors.soft,
              color: AppColors.accent,
            ),
          ),
        ],
      ),
    );
  }

  static String _days(int n) {
    final m10 = n % 10, m100 = n % 100;
    final w = m10 == 1 && m100 != 11
        ? 'день'
        : (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14))
            ? 'дня'
            : 'дней';
    return '$n $w';
  }
}

class _HomeCard extends ConsumerStatefulWidget {
  final HomeBlock? home;
  const _HomeCard({required this.home});

  @override
  ConsumerState<_HomeCard> createState() => _HomeCardState();
}

class _HomeCardState extends ConsumerState<_HomeCard> {
  bool _busy = false;

  Future<void> _chooseHere() async {
    final actions = ref.read(homeActionsProvider);
    // Индикатор — только пока ждём сеть и GPS; на время диалога его нет.
    final here = await _busyWhile(actions.blockHere);
    if (!mounted || here is! BlockHere?) return;
    if (here == null) {
      _toast('Рядом нет городских кварталов. Дом можно выбрать, стоя у себя во дворе.');
      return;
    }
    if (here.isHome) {
      _toast('Этот квартал уже ваш дом.');
      return;
    }
    if (!here.canBeHome) {
      _toast('Этот квартал занят. Сначала заберите его пробежкой, потом сделайте домом.');
      return;
    }
    final ok = await _confirm(here);
    if (ok != true || !mounted) return;
    final done = await _busyWhile(() async {
      await actions.setHome(here.blockId);
      return true;
    });
    if (mounted && done == true) _toast('Готово: это ваш дом.');
  }

  /// Выполнить шаг с индикатором; ошибку показать человеку и вернуть [_failed].
  Future<Object?> _busyWhile<T>(Future<T> Function() step) async {
    setState(() => _busy = true);
    try {
      return await step();
    } on HomeError catch (e) {
      if (mounted) _toast(e.message);
      return _failed;
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  static const _failed = Object();

  Future<bool?> _confirm(BlockHere here) => showCupertinoDialog<bool>(
    context: context,
    builder: (ctx) => CupertinoAlertDialog(
      title: const Text('Сделать этот квартал домом?'),
      content: Text(
        '${here.district != null ? '${here.district}. ' : ''}'
        'Дом не сгорает в конце сезона и его нельзя перехватить. Другие видят '
        'его занятым, но не видят, что он ваш.'
        '${widget.home != null ? ' Прежний дом перестанет быть домом.' : ''}',
      ),
      actions: [
        CupertinoDialogAction(
          onPressed: () => Navigator.pop(ctx, false),
          child: const Text('Отмена'),
        ),
        CupertinoDialogAction(
          isDefaultAction: true,
          onPressed: () => Navigator.pop(ctx, true),
          child: const Text('Сделать домом'),
        ),
      ],
    ),
  );

  void _toast(String text) => ScaffoldMessenger.of(context)
    ..hideCurrentSnackBar()
    ..showSnackBar(SnackBar(content: Text(text)));

  @override
  Widget build(BuildContext context) {
    final home = widget.home;
    return _Panel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Icon(CupertinoIcons.house_fill, color: AppColors.accent, size: 24),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      home == null ? 'Дом не выбран' : 'Домашний квартал',
                      style: TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.w700,
                        color: AppColors.ink,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      home == null
                          ? 'Один квартал можно сделать домом: он не сгорает и не перехватывается.'
                          : '${home.district ?? 'Якутск'} · виден другим только как занятый',
                      style: TextStyle(fontSize: 13, color: AppColors.muted, height: 1.35),
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 10),
          Padding(
            padding: const EdgeInsets.only(left: 36),
            child: _busy
                ? const SizedBox(
                    height: 36,
                    child: Align(
                      alignment: Alignment.centerLeft,
                      child: SizedBox(
                        width: 22,
                        height: 22,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      ),
                    ),
                  )
                : TextButton(
                    style: TextButton.styleFrom(
                      padding: EdgeInsets.zero,
                      minimumSize: const Size(0, 36),
                      alignment: Alignment.centerLeft,
                    ),
                    onPressed: _chooseHere,
                    child: Text(
                      home == null ? 'Сделать домом квартал, где я стою' : 'Сменить на квартал, где я стою',
                    ),
                  ),
          ),
        ],
      ),
    );
  }
}

class _DistrictRow extends StatelessWidget {
  final DistrictScore d;
  const _DistrictRow({required this.d});

  @override
  Widget build(BuildContext context) {
    final leader = d.leader;
    return _Panel(
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  d.district,
                  style: TextStyle(
                    fontSize: 15,
                    fontWeight: FontWeight.w700,
                    color: AppColors.ink,
                  ),
                ),
              ),
              Text(
                'мои ${d.mine} из ${d.total}',
                style: TextStyle(
                  fontSize: 13,
                  color: d.mine > 0 ? AppColors.ink : AppColors.muted,
                  fontFeatures: const [FontFeature.tabularFigures()],
                ),
              ),
            ],
          ),
          const SizedBox(height: 4),
          Text(
            leader == null
                ? 'Район свободен — лидера нет'
                : leader.isMe
                    ? 'Лидер — вы · ${leader.blocks}'
                    : 'Лидер — ${leader.name} · ${leader.blocks}',
            style: TextStyle(fontSize: 13, color: AppColors.muted),
          ),
        ],
      ),
    );
  }
}

class _ClubRow extends StatelessWidget {
  final ClubScore c;
  const _ClubRow({required this.c});

  @override
  Widget build(BuildContext context) => _Panel(
    padding: const EdgeInsets.fromLTRB(16, 12, 16, 12),
    borderColor: c.isMine ? AppColors.accent : null,
    child: Row(
      children: [
        SizedBox(
          width: 28,
          child: Text(
            '${c.place}',
            style: TextStyle(
              fontSize: 15,
              fontWeight: FontWeight.w800,
              color: AppColors.muted,
            ),
          ),
        ),
        Expanded(
          child: Text(
            c.isMine ? '${c.name} · ваш клуб' : c.name,
            style: TextStyle(fontSize: 15, color: AppColors.ink),
          ),
        ),
        Text(
          '${c.blocks}',
          style: TextStyle(
            fontSize: 15,
            fontWeight: FontWeight.w700,
            color: AppColors.ink,
            fontFeatures: const [FontFeature.tabularFigures()],
          ),
        ),
      ],
    ),
  );
}

class _SectionTitle extends StatelessWidget {
  final String title;
  final String hint;
  const _SectionTitle(this.title, this.hint);

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      Text(
        title,
        style: TextStyle(
          fontSize: 18,
          fontWeight: FontWeight.w800,
          color: AppColors.ink,
        ),
      ),
      const SizedBox(height: 2),
      Text(hint, style: TextStyle(fontSize: 13, color: AppColors.muted, height: 1.35)),
    ],
  );
}

class _Note extends StatelessWidget {
  final String text;
  const _Note(this.text);

  @override
  Widget build(BuildContext context) => Text(
    text,
    style: TextStyle(fontSize: 14, color: AppColors.muted, height: 1.4),
  );
}

class _Panel extends StatelessWidget {
  final Widget child;
  final EdgeInsets padding;
  final Color? borderColor;
  const _Panel({
    required this.child,
    this.padding = const EdgeInsets.all(16),
    this.borderColor,
  });

  @override
  Widget build(BuildContext context) => Container(
    padding: padding,
    decoration: BoxDecoration(
      color: AppColors.panel,
      borderRadius: BorderRadius.circular(14),
      border: Border.all(color: borderColor ?? AppColors.separator),
    ),
    child: child,
  );
}
