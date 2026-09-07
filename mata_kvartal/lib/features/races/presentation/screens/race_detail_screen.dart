import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../../../core/theme/app_colors.dart';
import '../../data/race_reminders.dart';
import '../../data/races_provider.dart';

const _months = [
  '', 'января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа',
  'сентября', 'октября', 'ноября', 'декабря'
];

List<Color> _grad(String type) {
  switch (type) {
    case 'trail':
      return const [Color(0xFF12543A), Color(0xFF0A2418)];
    case 'night':
      return const [Color(0xFF3A2170), Color(0xFF140B2C)];
    case 'fest':
      return const [Color(0xFF8A3B12), Color(0xFF331405)];
    case 'relay':
      return const [Color(0xFF0D5C63), Color(0xFF082224)];
    case 'kids':
      return const [Color(0xFF8A5A12), Color(0xFF2A1A05)];
    default:
      return const [Color(0xFF123A7A), Color(0xFF0B1B39)];
  }
}

class RaceDetailScreen extends ConsumerWidget {
  final RaceEvent race;
  const RaceDetailScreen({super.key, required this.race});

  void _snack(BuildContext context, String text) {
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
      content: Text(text),
      behavior: SnackBarBehavior.floating,
      backgroundColor: AppColors.bgElevated,
    ));
  }

  /// Открыть страницу регистрации/забега во внешнем браузере.
  Future<void> _openReg(BuildContext context) async {
    final url = race.regUrl.trim();
    if (url.isEmpty) {
      _snack(context, 'У этого забега пока нет ссылки на регистрацию');
      return;
    }
    final uri = Uri.tryParse(url);
    var ok = false;
    if (uri != null) {
      try {
        ok = await launchUrl(uri, mode: LaunchMode.externalApplication);
      } catch (_) {
        ok = false;
      }
    }
    if (!ok && context.mounted) {
      _snack(context, 'Не удалось открыть ссылку');
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final d = race.date;
    final dateText = d == null ? '' : '${d.day} ${_months[d.month]} ${d.year}';
    final past = race.isPast;
    final planned = ref.watch(plannedRacesProvider).any((r) => r.id == race.id);
    return Scaffold(
      backgroundColor: AppColors.bgDark,
      body: CustomScrollView(
        slivers: [
          SliverAppBar(
            pinned: true,
            expandedHeight: 210,
            backgroundColor: AppColors.bgDark,
            iconTheme: IconThemeData(color: AppColors.ink),
            flexibleSpace: FlexibleSpaceBar(
              background: Stack(
                fit: StackFit.expand,
                children: [
                  if (race.coverUrl.isNotEmpty)
                    Image.network(race.coverUrl, fit: BoxFit.cover,
                        errorBuilder: (_, __, ___) => _gradientCover())
                  else
                    _gradientCover(),
                  const DecoratedBox(
                    decoration: BoxDecoration(
                      gradient: LinearGradient(
                        begin: Alignment.topCenter,
                        end: Alignment.bottomCenter,
                        colors: [Colors.transparent, Color(0xFF060A14)],
                        stops: [0.4, 1.0],
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
          SliverToBoxAdapter(
            child: Padding(
              padding: const EdgeInsets.fromLTRB(20, 18, 20, 40),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(race.title,
                      style: TextStyle(
                          color: AppColors.ink, fontSize: 24, fontWeight: FontWeight.w800, height: 1.1)),
                  const SizedBox(height: 12),
                  _infoRow(CupertinoIcons.calendar, dateText),
                  const SizedBox(height: 8),
                  _infoRow(CupertinoIcons.location_solid,
                      [race.city, race.place].where((s) => s.isNotEmpty).join(' · ')),
                  if (race.region.isNotEmpty) ...[
                    const SizedBox(height: 8),
                    _infoRow(CupertinoIcons.map, race.region),
                  ],
                  if (race.distances.isNotEmpty) ...[
                    const SizedBox(height: 18),
                    Text('Дистанции',
                        style: TextStyle(color: AppColors.textTertiary, fontSize: 12, fontWeight: FontWeight.w700, letterSpacing: 1)),
                    const SizedBox(height: 8),
                    Wrap(
                      spacing: 8,
                      runSpacing: 8,
                      children: [
                        for (final dist in race.distances)
                          Container(
                            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                            decoration: BoxDecoration(
                              color: AppColors.bgCard,
                              borderRadius: BorderRadius.circular(10),
                              border: Border.all(color: AppColors.separator),
                            ),
                            child: Text(dist,
                                style: TextStyle(
                                    color: AppColors.ink, fontSize: 14, fontWeight: FontWeight.w700)),
                          ),
                      ],
                    ),
                  ],
                  if (race.description.isNotEmpty) ...[
                    const SizedBox(height: 20),
                    Text(race.description,
                        style: TextStyle(color: AppColors.textSecondary, fontSize: 14.5, height: 1.5)),
                  ],
                  if (race.points > 0) ...[
                    const SizedBox(height: 20),
                    Container(
                      padding: const EdgeInsets.all(14),
                      decoration: BoxDecoration(
                        color: const Color(0x1A30D158),
                        borderRadius: BorderRadius.circular(14),
                        border: Border.all(color: const Color(0xFF1F5B47)),
                      ),
                      child: Row(
                        children: [
                          Icon(CupertinoIcons.circle_grid_hex_fill,
                              color: AppColors.success, size: 20),
                          const SizedBox(width: 10),
                          Expanded(
                            child: Text('+${race.points} баллов за финиш — в общий баланс экосистемы',
                                style: TextStyle(color: AppColors.ink, fontSize: 13.5)),
                          ),
                        ],
                      ),
                    ),
                  ],
                  const SizedBox(height: 24),
                  if (!past) ...[
                    _planBtn(
                      planned: planned,
                      onTap: () async {
                        final added = await ref
                            .read(plannedRacesProvider.notifier)
                            .toggle(race);
                        // Локальные напоминания: планируем при добавлении, снимаем при удалении.
                        if (added) {
                          await RaceReminders.requestPermission();
                          await RaceReminders.scheduleForRace(race);
                        } else {
                          await RaceReminders.cancelForRace(race.id);
                        }
                        if (!context.mounted) return;
                        _snack(
                          context,
                          added
                              ? 'Сохранено в «Мои старты» — напомним перед стартом'
                              : 'Убрано из «Моих стартов»',
                        );
                      },
                    ),
                    const SizedBox(height: 10),
                    _ghostBtn(
                      race.regUrl.isNotEmpty ? 'Регистрация' : 'Подробнее',
                      () => _openReg(context),
                    ),
                  ] else
                    _ghostBtn('Результаты и фото', () => _snack(context, 'Архив забега — скоро')),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _gradientCover() => DecoratedBox(
        decoration: BoxDecoration(
          gradient: LinearGradient(
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
            colors: _grad(race.type),
          ),
        ),
      );

  Widget _infoRow(IconData icon, String text) => Row(
        children: [
          Icon(icon, size: 16, color: AppColors.electricBlue),
          const SizedBox(width: 8),
          Expanded(
            child: Text(text,
                style: TextStyle(color: AppColors.textSecondary, fontSize: 14)),
          ),
        ],
      );

  Widget _planBtn({required bool planned, required VoidCallback onTap}) => SizedBox(
        width: double.infinity,
        child: FilledButton.icon(
          onPressed: onTap,
          icon: Icon(
            planned ? CupertinoIcons.checkmark_alt : CupertinoIcons.paperplane,
            size: 18,
            color: planned ? AppColors.success : AppColors.ink,
          ),
          label: Text(
            planned ? 'В «Моих стартах»' : 'Планирую поехать',
            style: TextStyle(
                fontSize: 15,
                fontWeight: FontWeight.w700,
                color: planned ? AppColors.success : AppColors.ink),
          ),
          style: FilledButton.styleFrom(
            backgroundColor:
                planned ? const Color(0x1A30D158) : AppColors.electricBlue,
            side: planned
                ? const BorderSide(color: Color(0xFF1F5B47))
                : BorderSide.none,
            padding: const EdgeInsets.symmetric(vertical: 15),
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
          ),
        ),
      );

  Widget _ghostBtn(String text, VoidCallback onTap) => SizedBox(
        width: double.infinity,
        child: OutlinedButton(
          onPressed: onTap,
          style: OutlinedButton.styleFrom(
            side: BorderSide(color: AppColors.separator),
            padding: const EdgeInsets.symmetric(vertical: 15),
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
          ),
          child: Text(text,
              style: TextStyle(fontSize: 15, fontWeight: FontWeight.w700, color: AppColors.ink)),
        ),
      );
}
