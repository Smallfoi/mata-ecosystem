import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../../core/theme/app_colors.dart';
import '../../../../core/theme/app_theme.dart';
import '../../../medals/data/medal_defs.dart';
import '../../../medals/data/medals_provider.dart';
import '../../../medals/presentation/medal_detail.dart';
import '../../../medals/presentation/medal_widgets.dart';

/// Каталог «Все медали» — «Штамп МАТА» (утверждено 01.09.2026, D-64).
///
/// Открывается из Зала славы кнопкой «Все медали»: 44 награды пятью сериями.
/// Открытые — полный металл, закрытые — тот же штамп под обесцвечиванием
/// (42 %), новые три дня носят лаймовый кант. Тап — карточка с чеканкой;
/// у полученных — оборот с личной гравировкой.
class MedalCatalogScreen extends ConsumerWidget {
  const MedalCatalogScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final medals = ref.watch(medalsProvider);

    return Scaffold(
      backgroundColor: AppColors.bg,
      appBar: AppBar(
        backgroundColor: AppColors.bg,
        title: const Text('Все медали'),
      ),
      body: SafeArea(
        child: medals.when(
          loading: () => const Center(child: CircularProgressIndicator()),
          error: (e, _) =>
              _Offline(onRetry: () => ref.invalidate(medalsProvider)),
          data: (list) => _Hall(list: list),
        ),
      ),
    );
  }
}

class _Hall extends StatelessWidget {
  final List<MedalFull> list;
  const _Hall({required this.list});

  @override
  Widget build(BuildContext context) {
    final earned = list.where((m) => m.earned).length;
    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 4, 16, 24),
      children: [
        Padding(
          padding: const EdgeInsets.only(left: 4, bottom: 14),
          child: Text(
            'Штамп МАТА · открыто $earned из ${list.length} · '
            'накопленное не отнимается',
            style: TextStyle(fontSize: 13, color: AppColors.muted),
          ),
        ),
        for (final cat in MedalCat.values) ...[
          _CatSection(
            cat: cat,
            medals: [
              for (final m in list)
                if (m.def.cat == cat) m,
            ],
          ),
          const SizedBox(height: 18),
        ],
      ],
    );
  }
}

class _CatSection extends StatelessWidget {
  final MedalCat cat;
  final List<MedalFull> medals;
  const _CatSection({required this.cat, required this.medals});

  @override
  Widget build(BuildContext context) {
    final earned = medals.where((m) => m.earned).length;
    return Container(
      padding: const EdgeInsets.fromLTRB(14, 12, 14, 14),
      decoration: BoxDecoration(
        color: AppColors.paper,
        borderRadius: BorderRadius.circular(AppTheme.rSm),
        border: Border.all(color: AppColors.line),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  cat.title,
                  style: TextStyle(
                    fontFamily: AppTheme.fontDisplay,
                    fontSize: 15.5,
                    fontWeight: FontWeight.w800,
                    color: AppColors.ink,
                  ),
                ),
              ),
              Text(
                '$earned / ${medals.length}',
                style: TextStyle(
                  fontSize: 12.5,
                  fontWeight: FontWeight.w700,
                  color: earned > 0 ? AppColors.accentInk : AppColors.faint,
                ),
              ),
            ],
          ),
          const SizedBox(height: 2),
          Text(
            cat.note,
            style: TextStyle(
              fontSize: 11.5,
              height: 1.35,
              color: AppColors.muted,
            ),
          ),
          const SizedBox(height: 12),
          GridView.builder(
            shrinkWrap: true,
            physics: const NeverScrollableScrollPhysics(),
            itemCount: medals.length,
            gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
              crossAxisCount: 3,
              mainAxisSpacing: 12,
              crossAxisSpacing: 10,
              childAspectRatio: .8,
            ),
            itemBuilder: (context, i) => _MedalCell(medal: medals[i]),
          ),
        ],
      ),
    );
  }
}

class _MedalCell extends StatelessWidget {
  final MedalFull medal;
  const _MedalCell({required this.medal});

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: () => showMedalDetail(context, medal),
      behavior: HitTestBehavior.opaque,
      child: Column(
        children: [
          Expanded(
            child: LayoutBuilder(
              builder: (context, box) => MedalImage(
                def: medal.def,
                earned: medal.earned,
                isNew: medal.state.isNew,
                size: box.maxHeight,
              ),
            ),
          ),
          const SizedBox(height: 5),
          Text(
            medal.def.name,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: TextStyle(
              fontSize: 10.5,
              fontWeight: FontWeight.w600,
              color: medal.earned ? AppColors.ink : AppColors.faint,
            ),
          ),
        ],
      ),
    );
  }
}

class _Offline extends StatelessWidget {
  final VoidCallback onRetry;
  const _Offline({required this.onRetry});

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            'Зал наград не открылся — нет связи',
            style: TextStyle(fontSize: 13.5, color: AppColors.muted),
          ),
          const SizedBox(height: 10),
          OutlinedButton(onPressed: onRetry, child: const Text('Повторить')),
        ],
      ),
    );
  }
}
