import '../../../../shared/widgets/tab_visibility.dart';
import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:image_picker/image_picker.dart';
import 'package:qr_flutter/qr_flutter.dart';

import '../../../../core/theme/app_colors.dart';
import '../../data/club_provider.dart';
import '../widgets/club_style.dart';

class ClubScreen extends ConsumerStatefulWidget {
  const ClubScreen({super.key});

  @override
  ConsumerState<ClubScreen> createState() => _ClubScreenState();
}

class _ClubScreenState extends ConsumerState<ClubScreen> with TabVisibility {
  final _scrollCtrl = ScrollController(keepScrollOffset: false);

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback(
      (_) => ref.read(clubProvider.notifier).refresh(),
    );
  }

  @override
  void onTabShown() => ref.read(clubProvider.notifier).refresh();

  @override
  void dispose() {
    _scrollCtrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    ref.listen<ClubState>(clubProvider, (previous, next) {
      // Ответ мог прийти, когда экран уже убран из дерева (ушли на другую
      // вкладку). Обращаться к его контексту нельзя — иначе исключение
      // «deactivated widget's ancestor», после которого вкладка остаётся пустой.
      if (!context.mounted) return;
      // Клуб удалили или вышли из него: страница резко становится короче, а
      // прокрутка осталась внизу — без этого экран выглядел бы пустым.
      if (previous?.myClub != null &&
          next.myClub == null &&
          _scrollCtrl.hasClients &&
          _scrollCtrl.offset > 0) {
        _scrollCtrl.jumpTo(0);
      }
      final message = next.message;
      if (message != null && message != previous?.message) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(message), behavior: SnackBarBehavior.floating),
        );
      }
    });
    final state = ref.watch(clubProvider);

    return Scaffold(
      backgroundColor: AppColors.bgDark,
      body: RefreshIndicator(
        onRefresh: () => ref.read(clubProvider.notifier).refresh(),
        child: CustomScrollView(
          controller: _scrollCtrl,
          physics: const AlwaysScrollableScrollPhysics(),
          slivers: [
            _ClubSliverHeader(club: state.myClub),
            SliverPadding(
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 96),
              sliver: SliverList(
                delegate: SliverChildListDelegate([
                  // «Старты» — не часть клуба, а самостоятельный раздел (D-45).
                  // Держим его здесь, а не внутри тел «клуб есть»/«клуба нет»:
                  // так он виден в любом состоянии экрана и не зависит от того,
                  // как эти тела устроены внутри.
                  const _RacesEntryCard(),
                  const SizedBox(height: 14),
                  if (state.error != null) ...[
                    _StatusCard(
                      icon: CupertinoIcons.exclamationmark_triangle_fill,
                      title: 'Не удалось загрузить клубы',
                      subtitle: state.error!,
                      color: AppColors.error,
                      actionLabel: 'Повторить',
                      onAction: () => ref.read(clubProvider.notifier).refresh(),
                    ),
                    const SizedBox(height: 12),
                  ],
                  if (state.isLoading && !state.loaded)
                    const _LoadingCard()
                  else if (state.myClub != null)
                    _MyClubBody(club: state.myClub!)
                  else
                    const _DiscoverBody(),
                ]),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

void _showCreateClubSheet(BuildContext context) {
  showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    useSafeArea: true,
    backgroundColor: AppColors.bgSurface,
    shape: const RoundedRectangleBorder(
      borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
    ),
    builder: (_) => const _ClubFormSheet(),
  );
}

void _showEditClubSheet(BuildContext context, Club club) {
  showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    useSafeArea: true,
    backgroundColor: AppColors.bgSurface,
    shape: const RoundedRectangleBorder(
      borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
    ),
    builder: (_) => _ClubFormSheet(existing: club),
  );
}

void _showClubInviteSheet(BuildContext context, Club club) {
  showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    useSafeArea: true,
    backgroundColor: AppColors.bgSurface,
    shape: const RoundedRectangleBorder(
      borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
    ),
    builder: (_) => _ClubInviteSheet(club: club),
  );
}

class _FitText extends StatelessWidget {
  final String text;
  final TextStyle? style;
  const _FitText(this.text, {this.style});

  @override
  Widget build(BuildContext context) => SizedBox(
    width: double.infinity,
    child: FittedBox(
      fit: BoxFit.scaleDown,
      alignment: Alignment.centerLeft,
      child: Text(text, maxLines: 1, softWrap: false, style: style),
    ),
  );
}

/// Человекочитаемый пробег: «12.5 км», «124 км».
String _kmLabel(double km) =>
    '${km >= 100 ? km.round() : km.toStringAsFixed(1)} км';

/// Выбрать фото из галереи и загрузить как логотип клуба (только владелец).
/// Доступно по тапу на аватарку клуба в шапке и кнопкой в форме редактирования.
Future<void> _pickAndUploadClubLogo(WidgetRef ref) async {
  final picked = await ImagePicker().pickImage(
    source: ImageSource.gallery,
    maxWidth: 800,
    imageQuality: 85,
  );
  if (picked == null) return;
  await ref.read(clubProvider.notifier).uploadLogo(picked.path);
}

/// Иконка «фон клуба» в шапке: тап → меню (загрузить/сменить/убрать фон).
/// Только владелец. Файл грузится сразу (как лого).
Future<void> _editClubCover(
  BuildContext context,
  WidgetRef ref,
  bool hasCover,
) async {
  final action = await showCupertinoModalPopup<String>(
    context: context,
    builder: (ctx) => CupertinoActionSheet(
      title: const Text('Фон клуба'),
      actions: [
        CupertinoActionSheetAction(
          onPressed: () => Navigator.pop(ctx, 'upload'),
          child: Text(hasCover ? 'Сменить фон' : 'Загрузить фон'),
        ),
        if (hasCover)
          CupertinoActionSheetAction(
            isDestructiveAction: true,
            onPressed: () => Navigator.pop(ctx, 'remove'),
            child: const Text('Убрать фон'),
          ),
      ],
      cancelButton: CupertinoActionSheetAction(
        onPressed: () => Navigator.pop(ctx),
        child: const Text('Отмена'),
      ),
    ),
  );
  if (action == 'upload') {
    final picked = await ImagePicker().pickImage(
      source: ImageSource.gallery,
      maxWidth: 1600,
      imageQuality: 85,
    );
    if (picked != null) {
      await ref.read(clubProvider.notifier).uploadCover(picked.path);
    }
  } else if (action == 'remove') {
    await ref.read(clubProvider.notifier).removeCover();
  }
}

class _ClubSliverHeader extends ConsumerWidget {
  final Club? club;
  const _ClubSliverHeader({required this.club});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final hasClub = club != null;
    final s = ClubStyle.byKey(club?.style);
    final cover = club?.cover;
    final hasCover = cover != null && cover.isNotEmpty;
    // Поверх фотографии текст светлый (под ним вуаль), на светлом пресете — тёмный.
    final onHeader = hasCover ? AppColors.onDark : AppColors.ink;
    final onHeaderSoft = hasCover
        ? AppColors.onDark.withValues(alpha: 0.78)
        : AppColors.muted;
    // Логотип в «рамке» пресета (кольцо цвета s.frame).
    Widget ringed(Widget logo) => Container(
      padding: const EdgeInsets.all(2.5),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(58 * 0.28 + 2.5),
        border: Border.all(color: s.frame.withValues(alpha: 0.85), width: 2),
      ),
      child: logo,
    );
    return SliverAppBar(
      expandedHeight: 244,
      pinned: true,
      backgroundColor: AppColors.bgDark,
      // Никаких кнопок в шапке: обновление — свайпом вниз (pull-to-refresh),
      // скан QR — кнопкой «Скан QR» в карточке приглашения.
      title: Text('Клуб', style: Theme.of(context).textTheme.titleLarge),
      flexibleSpace: FlexibleSpaceBar(
        background: Container(
          color: AppColors.bgDark,
          child: Stack(
            fit: StackFit.expand,
            children: [
              // Обложка-баннер (если загружена владельцем) — фон шапки.
              if (hasCover)
                Image.network(
                  resolveClubMediaUrl(cover),
                  fit: BoxFit.cover,
                  errorBuilder: (_, __, ___) => const SizedBox.shrink(),
                ),
              // С обложкой — тёмная вуаль для читаемости; без — градиент пресета.
              DecoratedBox(
                decoration: BoxDecoration(
                  gradient: LinearGradient(
                    colors: hasCover
                        ? [
                            Colors.black.withValues(alpha: 0.10),
                            Colors.black.withValues(alpha: 0.42),
                            Colors.black.withValues(alpha: 0.68),
                          ]
                        : s.headerGradient,
                    begin: Alignment.topCenter,
                    end: Alignment.bottomCenter,
                    stops: const [0.0, 0.6, 1.0],
                  ),
                ),
              ),
              // Анимированная тема — только без обложки (иначе фото — главный фон).
              if (hasClub && !hasCover)
                Positioned.fill(child: ClubHeaderBackground(style: s)),
              // Графит (Ф8): светлые пресеты гасим тёмной вуалью — светлый
              // текст шапки читается, оттенок пресета остаётся подсветкой.
              if (AppColors.isGraphite && !hasCover)
                const DecoratedBox(
                  decoration: BoxDecoration(color: Color(0xD920252B)),
                ),
              SafeArea(
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(20, 16, 20, 12),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    mainAxisAlignment: MainAxisAlignment.end,
                    children: [
                      Row(
                        children: [
                          // Владелец: тап по аватарке — выбрать и загрузить фото-логотип.
                          (hasClub && club!.isOwner)
                              ? GestureDetector(
                                  onTap: () => _pickAndUploadClubLogo(ref),
                                  behavior: HitTestBehavior.opaque,
                                  child: Stack(
                                    clipBehavior: Clip.none,
                                    children: [
                                      ringed(
                                        _ClubLogo(logo: club!.logo, size: 58),
                                      ),
                                      Positioned(
                                        right: -2,
                                        bottom: -2,
                                        child: Container(
                                          padding: const EdgeInsets.all(4),
                                          decoration: BoxDecoration(
                                            color: s.accent,
                                            shape: BoxShape.circle,
                                            border: Border.all(
                                              color: AppColors.bgDark,
                                              width: 2,
                                            ),
                                          ),
                                          child: Icon(
                                            CupertinoIcons.camera_fill,
                                            size: 11,
                                            color: AppColors.ink,
                                          ),
                                        ),
                                      ),
                                    ],
                                  ),
                                )
                              : ringed(
                                  _ClubLogo(logo: club?.logo ?? 'K', size: 58),
                                ),
                          const SizedBox(width: 14),
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                _FitText(
                                  hasClub
                                      ? club!.name
                                      : '\u041a\u043b\u0443\u0431',
                                  style: Theme.of(context)
                                      .textTheme
                                      .headlineSmall
                                      ?.copyWith(
                                        fontWeight: FontWeight.w700,
                                        color: onHeader,
                                      ),
                                ),
                                const SizedBox(height: 2),
                                _FitText(
                                  hasClub
                                      ? '${club!.memberCount} \u0443\u0447\u0430\u0441\u0442\u043d\u0438\u043a\u043e\u0432'
                                      : '\u0421\u043e\u0437\u0434\u0430\u0439 \u043a\u043b\u0443\u0431 \u0438\u043b\u0438 \u043a\u043e\u043c\u0430\u043d\u0434\u0443',
                                  style: Theme.of(context).textTheme.bodySmall
                                      ?.copyWith(color: onHeaderSoft),
                                ),
                              ],
                            ),
                          ),
                          if (hasClub)
                            _ClubBadge(
                              label: club!.isOwner ? 'Владелец' : 'Участник',
                              color: club!.isOwner
                                  ? AppColors.warning
                                  : AppColors.success,
                            ),
                        ],
                      ),
                      const SizedBox(height: 14),
                      Row(
                        children: [
                          _ClubMetricCard(
                            icon: CupertinoIcons.location_north_fill,
                            label:
                                '\u0410\u043a\u0442\u0438\u0432\u043d\u043e\u0441\u0442\u044c',
                            value: hasClub
                                ? _kmLabel(club!.totalKm)
                                : '0 \u043a\u043c',
                            color: s.accent,
                          ),
                          const SizedBox(width: 8),
                          _ClubMetricCard(
                            icon: CupertinoIcons.person_2_fill,
                            label: '\u0421\u043e\u0441\u0442\u0430\u0432',
                            value: hasClub ? '${club!.memberCount}' : '0',
                            color: AppColors.electricBlue,
                          ),
                          const SizedBox(width: 8),
                          _ClubMetricCard(
                            icon: hasClub && club!.isRequestOnly
                                ? CupertinoIcons.lock_fill
                                : CupertinoIcons.check_mark_circled_solid,
                            label: '\u0412\u0445\u043e\u0434',
                            value: hasClub
                                ? (club!.isRequestOnly
                                      ? '\u0417\u0430\u044f\u0432\u043a\u0430'
                                      : '\u041e\u0442\u043a\u0440\u044b\u0442')
                                : '-',
                            color: hasClub && club!.isRequestOnly
                                ? AppColors.warning
                                : AppColors.success,
                          ),
                        ],
                      ),
                    ],
                  ),
                ),
              ),
              // Иконка «фон клуба» — владелец меняет обложку прямо на экране.
              if (hasClub && club!.isOwner)
                Positioned(
                  top: 6,
                  right: 6,
                  child: SafeArea(
                    child: Material(
                      color: Colors.black.withValues(alpha: 0.28),
                      shape: const CircleBorder(),
                      child: InkWell(
                        customBorder: const CircleBorder(),
                        onTap: () => _editClubCover(context, ref, hasCover),
                        child: SizedBox(
                          width: 48,
                          height: 48,
                          child: Icon(
                            CupertinoIcons.photo_on_rectangle,
                            size: 18,
                            color: AppColors.onDark,
                          ),
                        ),
                      ),
                    ),
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }
}

class _DiscoverBody extends ConsumerStatefulWidget {
  const _DiscoverBody();

  @override
  ConsumerState<_DiscoverBody> createState() => _DiscoverBodyState();
}

/// Контроллеры полей живут здесь, а не в экране. Экран при уходе с вкладки
/// уничтожается вместе со своими контроллерами, и поля, которые на них
/// ссылались, переставали отрисовываться — вкладка выглядела пустой (D-47).
class _DiscoverBodyState extends ConsumerState<_DiscoverBody> {
  final _searchCtrl = TextEditingController();
  final _inviteCtrl = TextEditingController();

  @override
  void dispose() {
    _searchCtrl.dispose();
    _inviteCtrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(clubProvider);
    return Column(
      // Виджет — элемент списка слайверов, высота не ограничена:
      // без mainAxisSize.min Column схлопывается до первого потомка.
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _StatusCard(
          icon: CupertinoIcons.person_2_fill,
          title:
              '\u0422\u044b \u043f\u043e\u043a\u0430 \u043d\u0435 \u0432 \u043a\u043b\u0443\u0431\u0435',
          subtitle:
              '\u0421\u043e\u0437\u0434\u0430\u0439 \u0441\u0432\u043e\u0439 \u043a\u043b\u0443\u0431 \u0438\u043b\u0438 \u043a\u043e\u043c\u0430\u043d\u0434\u0443.',
          color: AppColors.electricBlue,
          actionLabel:
              '\u0421\u043e\u0437\u0434\u0430\u0442\u044c \u043a\u043b\u0443\u0431',
          actionIcon: CupertinoIcons.plus,
          onAction: () => _showCreateClubSheet(context),
        ),
        const SizedBox(height: 16),
        _InviteCodeCard(controller: _inviteCtrl),
        const SizedBox(height: 16),
        _SectionHeader(
          title:
              '\u041f\u043e\u0438\u0441\u043a \u043a\u043b\u0443\u0431\u0430',
        ),
        const SizedBox(height: 10),
        TextField(
          controller: _searchCtrl,
          style: TextStyle(color: AppColors.textPrimary),
          textInputAction: TextInputAction.search,
          onSubmitted: (value) =>
              ref.read(clubProvider.notifier).refresh(search: value),
          decoration: InputDecoration(
            hintText:
                '\u041d\u0430\u0437\u0432\u0430\u043d\u0438\u0435 \u0438\u043b\u0438 \u0433\u043e\u0440\u043e\u0434',
            hintStyle: TextStyle(color: AppColors.textTertiary),
            prefixIcon: const Icon(CupertinoIcons.search, size: 18),
            suffixIcon: IconButton(
              tooltip: '\u0418\u0441\u043a\u0430\u0442\u044c',
              icon: const Icon(CupertinoIcons.arrow_right_circle_fill),
              onPressed: () => ref
                  .read(clubProvider.notifier)
                  .refresh(search: _searchCtrl.text),
            ),
            filled: true,
            fillColor: AppColors.bgCard,
            border: OutlineInputBorder(
              borderRadius: BorderRadius.circular(14),
              borderSide: BorderSide(color: AppColors.separator),
            ),
            enabledBorder: OutlineInputBorder(
              borderRadius: BorderRadius.circular(14),
              borderSide: BorderSide(color: AppColors.separator),
            ),
          ),
        ),
        const SizedBox(height: 22),
        _SectionHeader(
          title: '\u041a\u043b\u0443\u0431\u044b',
          trailing: '${state.clubs.length}',
        ),
        const SizedBox(height: 10),
        if (state.clubs.isEmpty)
          const _EmptyCard(
            title:
                '\u041a\u043b\u0443\u0431\u043e\u0432 \u043f\u043e\u043a\u0430 \u043d\u0435\u0442',
            subtitle:
                '\u0421\u043e\u0437\u0434\u0430\u0439 \u043f\u0435\u0440\u0432\u044b\u0439 \u043a\u043b\u0443\u0431.',
          )
        else
          ...state.clubs.map((club) => _ClubListTile(club: club)),
        const SizedBox(height: 12),
        const _DistrictWarCard(),
      ],
    );
  }
}

class _MyClubBody extends ConsumerWidget {
  final Club club;
  const _MyClubBody({required this.club});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(clubProvider);
    return Column(
      // Виджет — элемент списка слайверов, высота не ограничена:
      // без mainAxisSize.min Column схлопывается до первого потомка.
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (club.isOwner) ...[
          _OwnerToolsCard(club: club),
          const SizedBox(height: 14),
        ],
        if (club.description != null) ...[
          _InfoCard(text: club.description!),
          const SizedBox(height: 18),
        ],
        if (club.isOwner) ...[
          _SectionHeader(title: 'Заявки', trailing: '${state.requests.length}'),
          const SizedBox(height: 10),
          if (state.requests.isEmpty)
            const _EmptyCard(
              title: 'Заявок нет',
              subtitle: 'Новые заявки появятся здесь.',
            )
          else
            ...state.requests.map((request) => _RequestTile(request: request)),
          const SizedBox(height: 24),
        ],
        _SectionHeader(title: 'Участники', trailing: '${club.members.length}'),
        const SizedBox(height: 10),
        if (club.members.isEmpty)
          const _EmptyCard(
            title: 'Нет участников',
            subtitle: 'Список подтянется с backend.',
          )
        else
          ...club.members.map((member) => _MemberTile(member: member)),
        const SizedBox(height: 24),
        _SectionHeader(title: 'Клубные вызовы'),
        const SizedBox(height: 10),
        _ClubChallengeSection(club: club),
        const SizedBox(height: 24),
        _SectionHeader(title: 'Захваченные районы'),
        const SizedBox(height: 10),
        _ClubTerritoryCard(club: club),
        const SizedBox(height: 12),
        const _DistrictWarCard(),
        const SizedBox(height: 18),
        SizedBox(
          width: double.infinity,
          child: OutlinedButton.icon(
            icon: const Icon(CupertinoIcons.square_arrow_right, size: 18),
            label: Text(
              club.isOwner && club.memberCount <= 1
                  ? 'Удалить клуб'
                  : 'Выйти из клуба',
            ),
            style: OutlinedButton.styleFrom(
              foregroundColor: AppColors.error,
              side: BorderSide(color: AppColors.error),
              padding: const EdgeInsets.symmetric(vertical: 14),
            ),
            onPressed: state.isMutating
                ? null
                : () => _confirmLeaveClub(context, ref, club),
          ),
        ),
      ],
    );
  }
}

/// Подтверждение выхода из клуба. Для владельца, оставшегося одним участником,
/// это удаление клуба целиком — предупреждаем об этом прямо, а не спрашиваем
/// абстрактное «вы уверены?».
Future<void> _confirmLeaveClub(
  BuildContext context,
  WidgetRef ref,
  Club club,
) async {
  final isDelete = club.isOwner && club.memberCount <= 1;
  final ok = await showDialog<bool>(
    context: context,
    builder: (ctx) => AlertDialog(
      title: Text(isDelete ? 'Удалить клуб?' : 'Выйти из клуба?'),
      content: Text(
        isDelete
            ? 'Клуб «${club.name}» будет удалён вместе с обложкой, участниками '
                  'и вызовами. Отменить это нельзя.'
            : 'Ты перестанешь быть участником клуба «${club.name}». '
                  'Вступить снова можно будет по приглашению или заявке.',
        style: TextStyle(color: AppColors.muted),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(ctx).pop(false),
          child: const Text('Отмена'),
        ),
        FilledButton(
          onPressed: () => Navigator.of(ctx).pop(true),
          style: FilledButton.styleFrom(backgroundColor: AppColors.error),
          child: Text(isDelete ? 'Удалить' : 'Выйти'),
        ),
      ],
    ),
  );
  if (ok != true) return;
  await ref.read(clubProvider.notifier).leaveClub();
}

// ── Клубные челленджи ───────────────────────────────────────────────────────

void _showCreateChallengeSheet(BuildContext context) {
  showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    useSafeArea: true,
    backgroundColor: AppColors.bgSurface,
    shape: const RoundedRectangleBorder(
      borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
    ),
    builder: (_) => const _ChallengeFormSheet(),
  );
}

Future<void> _confirmCancelChallenge(
  BuildContext context,
  WidgetRef ref,
) async {
  final ok = await showCupertinoDialog<bool>(
    context: context,
    builder: (ctx) => CupertinoAlertDialog(
      title: const Text('Завершить челлендж?'),
      content: const Text('Текущая цель и прогресс будут сняты.'),
      actions: [
        CupertinoDialogAction(
          onPressed: () => Navigator.pop(ctx, false),
          child: const Text('Отмена'),
        ),
        CupertinoDialogAction(
          isDestructiveAction: true,
          onPressed: () => Navigator.pop(ctx, true),
          child: const Text('Завершить'),
        ),
      ],
    ),
  );
  if (ok == true) await ref.read(clubProvider.notifier).cancelChallenge();
}

/// Раздел «Клубные вызовы»: активный челлендж (прогресс + вклад) либо
/// приглашение создать (владелец) / пустое состояние (участник).
class _ClubChallengeSection extends ConsumerWidget {
  final Club club;
  const _ClubChallengeSection({required this.club});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final ch = club.challenge;
    final s = ClubStyle.byKey(club.style);
    final state = ref.watch(clubProvider);

    if (ch == null) {
      if (!club.isOwner) {
        return const _FutureModuleCard(
          icon: CupertinoIcons.flag,
          title: 'Челленджей пока нет',
          subtitle:
              'Владелец задаёт общую цель по км — и весь клуб бежит к ней вместе.',
        );
      }
      return Container(
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: AppColors.bgCard,
          borderRadius: BorderRadius.circular(16),
          border: Border.all(color: AppColors.separator),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(CupertinoIcons.flag_fill, color: s.accent, size: 20),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(
                    'Задай цель клубу',
                    style: Theme.of(context).textTheme.titleSmall?.copyWith(
                      fontWeight: FontWeight.w800,
                    ),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 6),
            Text(
              'Общая цель по км на неделю/месяц. Прогресс собирается из пробежек всех участников.',
              style: Theme.of(
                context,
              ).textTheme.bodySmall?.copyWith(color: AppColors.textSecondary),
            ),
            const SizedBox(height: 12),
            SizedBox(
              width: double.infinity,
              child: FilledButton.icon(
                onPressed: state.isMutating
                    ? null
                    : () => _showCreateChallengeSheet(context),
                icon: const Icon(CupertinoIcons.add, size: 18),
                label: const Text('Создать челлендж'),
              ),
            ),
          ],
        ),
      );
    }

    final left = ch.daysLeft >= 1
        ? 'Осталось ${ch.daysLeft} дн.'
        : 'Осталось ${ch.hoursLeft} ч.';
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: AppColors.paper,
        borderRadius: BorderRadius.circular(22),
        border: Border.all(color: AppColors.line),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(
                ch.isDone
                    ? CupertinoIcons.checkmark_seal_fill
                    : CupertinoIcons.flag_fill,
                color: s.accent,
                size: 20,
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Text(
                  ch.title,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: Theme.of(
                    context,
                  ).textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w800),
                ),
              ),
              if (club.isOwner)
                GestureDetector(
                  onTap: state.isMutating
                      ? null
                      : () => _confirmCancelChallenge(context, ref),
                  behavior: HitTestBehavior.opaque,
                  child: Padding(
                    padding: EdgeInsets.all(4),
                    child: Icon(
                      CupertinoIcons.xmark,
                      size: 16,
                      color: AppColors.textSecondary,
                    ),
                  ),
                ),
            ],
          ),
          const SizedBox(height: 14),
          ClipRRect(
            borderRadius: BorderRadius.circular(8),
            child: LinearProgressIndicator(
              value: ch.progress,
              minHeight: 12,
              backgroundColor: AppColors.bgElevated,
              valueColor: AlwaysStoppedAnimation(s.accent),
            ),
          ),
          const SizedBox(height: 8),
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(
                '${_kmLabel(ch.currentKm)} / ${_kmLabel(ch.targetKm)}',
                style: TextStyle(color: s.accent, fontWeight: FontWeight.w800),
              ),
              Text(
                ch.isDone ? 'Цель достигнута 🎉' : left,
                style: Theme.of(
                  context,
                ).textTheme.bodySmall?.copyWith(color: AppColors.textSecondary),
              ),
            ],
          ),
          if (ch.contributions.isNotEmpty) ...[
            const SizedBox(height: 16),
            Text(
              'Вклад участников',
              style: Theme.of(
                context,
              ).textTheme.labelLarge?.copyWith(fontWeight: FontWeight.w800),
            ),
            const SizedBox(height: 8),
            ...ch.contributions
                .take(5)
                .map(
                  (c) => Padding(
                    padding: const EdgeInsets.symmetric(vertical: 4),
                    child: Row(
                      children: [
                        Icon(
                          CupertinoIcons.person_fill,
                          size: 14,
                          color: AppColors.textSecondary,
                        ),
                        const SizedBox(width: 8),
                        Expanded(
                          child: Text(
                            c.name,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: TextStyle(
                              color: AppColors.textPrimary,
                            ),
                          ),
                        ),
                        Text(
                          _kmLabel(c.km),
                          style: TextStyle(
                            color: AppColors.textPrimary,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
          ],
        ],
      ),
    );
  }
}

class _ChallengeFormSheet extends ConsumerStatefulWidget {
  const _ChallengeFormSheet();
  @override
  ConsumerState<_ChallengeFormSheet> createState() =>
      _ChallengeFormSheetState();
}

class _ChallengeFormSheetState extends ConsumerState<_ChallengeFormSheet> {
  final _titleCtrl = TextEditingController(text: 'Цель недели');
  final _kmCtrl = TextEditingController(text: '100');
  int _days = 7;
  String? _error;

  @override
  void dispose() {
    _titleCtrl.dispose();
    _kmCtrl.dispose();
    super.dispose();
  }

  Future<void> _create() async {
    final title = _titleCtrl.text.trim();
    final km = double.tryParse(_kmCtrl.text.trim().replaceAll(',', '.')) ?? 0;
    if (title.isEmpty) {
      setState(() => _error = 'Введи название цели');
      return;
    }
    if (km <= 0) {
      setState(() => _error = 'Цель в км должна быть больше 0');
      return;
    }
    await ref
        .read(clubProvider.notifier)
        .createChallenge(title: title, targetKm: km, days: _days);
    if (!mounted) return;
    final err = ref.read(clubProvider).error;
    if (err == null) {
      Navigator.of(context).pop();
    } else {
      setState(() => _error = err);
    }
  }

  @override
  Widget build(BuildContext context) {
    final bottom = MediaQuery.of(context).viewInsets.bottom;
    final state = ref.watch(clubProvider);
    return Padding(
      padding: EdgeInsets.fromLTRB(16, 16, 16, bottom + (bottom > 0 ? 16 : 96)),
      child: SingleChildScrollView(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          mainAxisSize: MainAxisSize.min,
          children: [
            Row(
              children: [
                Text(
                  'Новый челлендж',
                  style: Theme.of(
                    context,
                  ).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w800),
                ),
                const Spacer(),
                IconButton(
                  tooltip: 'Закрыть',
                  icon: const Icon(CupertinoIcons.xmark),
                  onPressed: () => Navigator.of(context).pop(),
                ),
              ],
            ),
            const SizedBox(height: 12),
            _EditField(
              controller: _titleCtrl,
              label: 'Название цели',
              icon: CupertinoIcons.flag_fill,
            ),
            const SizedBox(height: 10),
            _EditField(
              controller: _kmCtrl,
              label: 'Цель, км',
              icon: CupertinoIcons.location_north_fill,
              keyboardType: const TextInputType.numberWithOptions(
                decimal: true,
              ),
            ),
            const SizedBox(height: 16),
            Text(
              'Длительность',
              style: Theme.of(
                context,
              ).textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w700),
            ),
            const SizedBox(height: 8),
            CupertinoSlidingSegmentedControl<int>(
              groupValue: _days,
              children: const {
                7: Padding(
                  padding: EdgeInsets.symmetric(horizontal: 8, vertical: 6),
                  child: Text('Неделя'),
                ),
                14: Padding(
                  padding: EdgeInsets.symmetric(horizontal: 8, vertical: 6),
                  child: Text('2 недели'),
                ),
                30: Padding(
                  padding: EdgeInsets.symmetric(horizontal: 8, vertical: 6),
                  child: Text('Месяц'),
                ),
              },
              onValueChanged: (v) => setState(() => _days = v ?? 7),
            ),
            if (_error != null) ...[
              const SizedBox(height: 12),
              Text(_error!, style: TextStyle(color: AppColors.error)),
            ],
            const SizedBox(height: 18),
            FilledButton(
              onPressed: state.isMutating ? null : _create,
              child: state.isMutating
                  ? const SizedBox(
                      height: 20,
                      width: 20,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Text('Создать челлендж'),
            ),
          ],
        ),
      ),
    );
  }
}

/// Живая карта «Захваченные районы»: удерживаемая клубом площадь + число зон.
class _ClubTerritoryCard extends StatelessWidget {
  final Club club;
  const _ClubTerritoryCard({required this.club});

  String _area(double m2) {
    if (m2 >= 1000000) return '${(m2 / 1000000).toStringAsFixed(2)} км²';
    if (m2 >= 1000) return '${(m2 / 1000).toStringAsFixed(1)} тыс. м²';
    return '${m2.round()} м²';
  }

  Widget _stat(BuildContext c, String value, String label, Color accent) =>
      Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            value,
            style: TextStyle(
              color: accent,
              fontWeight: FontWeight.w800,
              fontSize: 20,
            ),
          ),
          Text(
            label,
            style: Theme.of(
              c,
            ).textTheme.bodySmall?.copyWith(color: AppColors.textSecondary),
          ),
        ],
      );

  @override
  Widget build(BuildContext context) {
    final s = ClubStyle.byKey(club.style);
    final has = club.territoryPieces > 0;
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: AppColors.bgCard,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AppColors.separator),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(CupertinoIcons.map_fill, color: s.accent, size: 20),
              const SizedBox(width: 10),
              Expanded(
                child: Text(
                  'Территории клуба',
                  style: Theme.of(
                    context,
                  ).textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w800),
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          if (has) ...[
            Row(
              children: [
                Expanded(
                  child: _stat(
                    context,
                    _area(club.territoryAreaM2),
                    'площадь',
                    s.accent,
                  ),
                ),
                Container(width: 1, height: 36, color: AppColors.separator),
                const SizedBox(width: 12),
                Expanded(
                  child: _stat(
                    context,
                    '${club.territoryPieces}',
                    'зон',
                    s.accent,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 10),
            Text(
              'Удержано участниками сейчас. Рейтинг клубов по площади — Рейтинг → «Районы».',
              style: Theme.of(
                context,
              ).textTheme.bodySmall?.copyWith(color: AppColors.textSecondary),
            ),
          ] else
            Text(
              'Пока 0 м². Бегите и замыкайте петли — площадь пойдёт в зачёт клуба. Рейтинг по площади: Рейтинг → «Районы».',
              style: Theme.of(
                context,
              ).textTheme.bodySmall?.copyWith(color: AppColors.textSecondary),
            ),
        ],
      ),
    );
  }
}

/// Вход в календарь забегов. Раздел уехал из нижней панели, но остался
/// самостоятельным маршрутом `/races` — ссылки и «назад» работают как раньше.
class _RacesEntryCard extends StatelessWidget {
  const _RacesEntryCard();

  @override
  Widget build(BuildContext context) => GestureDetector(
    onTap: () => context.push('/races'),
    child: Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: AppColors.paper,
        borderRadius: BorderRadius.circular(22),
        border: Border.all(color: AppColors.line),
      ),
      child: Row(
        children: [
          Container(
            width: 36,
            height: 36,
            decoration: BoxDecoration(
              color: AppColors.soft,
              borderRadius: BorderRadius.circular(12),
            ),
            child: Icon(
              CupertinoIcons.calendar,
              size: 18,
              color: AppColors.accentInk,
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('Старты', style: Theme.of(context).textTheme.titleMedium),
                const SizedBox(height: 2),
                Text(
                  'Календарь забегов',
                  style: Theme.of(context).textTheme.bodySmall,
                ),
              ],
            ),
          ),
          Icon(
            CupertinoIcons.chevron_right,
            size: 18,
            color: AppColors.faint,
          ),
        ],
      ),
    ),
  );
}

class _OwnerToolsCard extends StatelessWidget {
  final Club club;
  const _OwnerToolsCard({required this.club});

  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.all(14),
    decoration: BoxDecoration(
      color: AppColors.paper,
      borderRadius: BorderRadius.circular(22),
      border: Border.all(color: AppColors.line),
    ),
    child: Row(
      children: [
        Container(
          width: 36,
          height: 36,
          decoration: BoxDecoration(
            color: AppColors.soft,
            borderRadius: BorderRadius.circular(12),
          ),
          child: Icon(
            CupertinoIcons.slider_horizontal_3,
            size: 18,
            color: AppColors.accentInk,
          ),
        ),
        const SizedBox(width: 12),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                '\u0423\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u0438\u0435 \u043a\u043b\u0443\u0431\u043e\u043c',
                style: Theme.of(context).textTheme.titleSmall?.copyWith(
                  color: AppColors.textPrimary,
                  fontWeight: FontWeight.w800,
                ),
              ),
              const SizedBox(height: 2),
              Text(
                '\u041d\u0430\u0437\u0432\u0430\u043d\u0438\u0435, \u0433\u043e\u0440\u043e\u0434, \u0438\u043a\u043e\u043d\u043a\u0430 \u0438 \u043f\u0440\u0430\u0432\u0438\u043b\u0430 \u0432\u0445\u043e\u0434\u0430',
                style: Theme.of(
                  context,
                ).textTheme.bodySmall?.copyWith(color: AppColors.textSecondary),
              ),
            ],
          ),
        ),
        const SizedBox(width: 10),
        IconButton.filledTonal(
          tooltip:
              '\u041f\u0440\u0438\u0433\u043b\u0430\u0441\u0438\u0442\u044c \u0432 \u043a\u043b\u0443\u0431',
          onPressed: () => _showClubInviteSheet(context, club),
          icon: const Icon(CupertinoIcons.qrcode, size: 18),
        ),
        const SizedBox(width: 8),
        IconButton.filled(
          tooltip:
              '\u0420\u0435\u0434\u0430\u043a\u0442\u0438\u0440\u043e\u0432\u0430\u0442\u044c \u043a\u043b\u0443\u0431',
          onPressed: () => _showEditClubSheet(context, club),
          icon: const Icon(CupertinoIcons.pencil, size: 18),
        ),
      ],
    ),
  );
}

class _InviteCodeCard extends ConsumerWidget {
  final TextEditingController controller;
  const _InviteCodeCard({required this.controller});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(clubProvider);
    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        color: AppColors.paper,
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: AppColors.line),
        boxShadow: [
          BoxShadow(
            color: AppColors.graphite.withValues(alpha: 0.06),
            blurRadius: 24,
            offset: const Offset(0, 10),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // \u0428\u0430\u043f\u043a\u0430: \u0438\u043a\u043e\u043d\u043a\u0430-\u0447\u0438\u043f + \u0437\u0430\u0433\u043e\u043b\u043e\u0432\u043e\u043a-\u0434\u0435\u0439\u0441\u0442\u0432\u0438\u0435 + \u043f\u043e\u0434\u0441\u043a\u0430\u0437\u043a\u0430.
          Row(
            children: [
              Container(
                width: 46,
                height: 46,
                decoration: BoxDecoration(
                  color: AppColors.soft,
                  borderRadius: BorderRadius.circular(14),
                ),
                child: Icon(
                  CupertinoIcons.person_2,
                  color: AppColors.accentInk,
                  size: 22,
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '\u0412\u0441\u0442\u0443\u043f\u0438\u0442\u044c \u0432 \u043a\u043b\u0443\u0431',
                      style: Theme.of(context).textTheme.titleMedium?.copyWith(
                        color: AppColors.ink,
                        fontWeight: FontWeight.w800,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      '\u041e\u0442\u0441\u043a\u0430\u043d\u0438\u0440\u0443\u0439\u0442\u0435 QR \u0434\u0440\u0443\u0433\u0430 \u0438\u043b\u0438 \u0432\u0432\u0435\u0434\u0438\u0442\u0435 \u043a\u043e\u0434',
                      style: TextStyle(color: AppColors.muted, fontSize: 12, height: 1.3),
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 16),
          // \u041e\u0441\u043d\u043e\u0432\u043d\u043e\u0435 \u0434\u0435\u0439\u0441\u0442\u0432\u0438\u0435 \u2014 \u0441\u043a\u0430\u043d QR (\u043a\u0430\u043a \u0432 \u0422\u0438\u043d\u044c\u043a\u043e\u0444\u0444/Taobao): \u0433\u0440\u0430\u0444\u0438\u0442\u043e\u0432\u0430\u044f \u043a\u043d\u043e\u043f\u043a\u0430.
          SizedBox(
            width: double.infinity,
            height: 52,
            child: FilledButton.icon(
              onPressed: () => context.push('/club/scan'),
              icon: const Icon(CupertinoIcons.qrcode_viewfinder, size: 20),
              label: const Text(
                '\u0421\u043a\u0430\u043d\u0438\u0440\u043e\u0432\u0430\u0442\u044c QR',
                style: TextStyle(fontWeight: FontWeight.w700, fontSize: 15),
              ),
              style: FilledButton.styleFrom(
                backgroundColor: AppColors.graphite,
                foregroundColor: AppColors.onDark,
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(14),
                ),
              ),
            ),
          ),
          const SizedBox(height: 14),
          // \u0420\u0430\u0437\u0434\u0435\u043b\u0438\u0442\u0435\u043b\u044c \u00ab\u0438\u043b\u0438 \u043a\u043e\u0434 \u0432\u0440\u0443\u0447\u043d\u0443\u044e\u00bb.
          Row(
            children: [
              Expanded(child: Divider(color: AppColors.line)),
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 10),
                child: Text(
                  '\u0438\u043b\u0438 \u043a\u043e\u0434 \u0432\u0440\u0443\u0447\u043d\u0443\u044e',
                  style: TextStyle(color: AppColors.faint, fontSize: 11),
                ),
              ),
              Expanded(child: Divider(color: AppColors.line)),
            ],
          ),
          const SizedBox(height: 12),
          TextField(
            controller: controller,
            style: TextStyle(color: AppColors.ink),
            textInputAction: TextInputAction.done,
            onSubmitted: (_) => _submit(context, ref),
            decoration: InputDecoration(
              hintText: '\u041a\u043e\u0434 \u0438\u043b\u0438 \u0441\u0441\u044b\u043b\u043a\u0430 \u043f\u0440\u0438\u0433\u043b\u0430\u0448\u0435\u043d\u0438\u044f',
              hintStyle: TextStyle(color: AppColors.faint),
              prefixIcon: Icon(
                CupertinoIcons.ticket,
                size: 18,
                color: AppColors.muted,
              ),
              filled: true,
              fillColor: AppColors.soft,
              contentPadding: const EdgeInsets.symmetric(vertical: 14),
              border: OutlineInputBorder(
                borderRadius: BorderRadius.circular(14),
                borderSide: BorderSide.none,
              ),
              enabledBorder: OutlineInputBorder(
                borderRadius: BorderRadius.circular(14),
                borderSide: BorderSide.none,
              ),
              focusedBorder: OutlineInputBorder(
                borderRadius: BorderRadius.circular(14),
                borderSide: BorderSide(color: AppColors.accentInk, width: 1.5),
              ),
            ),
          ),
          const SizedBox(height: 10),
          SizedBox(
            width: double.infinity,
            height: 48,
            child: FilledButton(
              onPressed: state.isMutating ? null : () => _submit(context, ref),
              style: FilledButton.styleFrom(
                backgroundColor: AppColors.soft,
                foregroundColor: AppColors.accentInk,
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(14),
                ),
              ),
              child: Text(
                state.isMutating ? '\u041e\u0442\u043f\u0440\u0430\u0432\u043b\u044f\u0435\u043c\u2026' : '\u0412\u0441\u0442\u0443\u043f\u0438\u0442\u044c',
                style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 15),
              ),
            ),
          ),
        ],
      ),
    );
  }

  void _submit(BuildContext context, WidgetRef ref) {
    FocusScope.of(context).unfocus();
    ref.read(clubProvider.notifier).joinByInvite(controller.text);
  }
}

class _ClubInviteSheet extends StatelessWidget {
  final Club club;
  const _ClubInviteSheet({required this.club});

  String get _link => 'https://kvartal.app/club/${club.id}';

  @override
  Widget build(BuildContext context) {
    final bottom = MediaQuery.of(context).viewInsets.bottom;
    return Padding(
      padding: EdgeInsets.fromLTRB(16, 16, 16, bottom + 96),
      child: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                _ClubLogo(logo: club.logo, size: 46),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      _FitText(
                        club.name,
                        style: Theme.of(context).textTheme.titleMedium
                            ?.copyWith(fontWeight: FontWeight.w800),
                      ),
                      const SizedBox(height: 2),
                      Text(
                        '\u041f\u0440\u0438\u0433\u043b\u0430\u0448\u0435\u043d\u0438\u0435 \u0432 \u043a\u043b\u0443\u0431',
                        style: Theme.of(context).textTheme.bodySmall?.copyWith(
                          color: AppColors.textSecondary,
                        ),
                      ),
                    ],
                  ),
                ),
                IconButton(
                  tooltip: '\u0417\u0430\u043a\u0440\u044b\u0442\u044c',
                  icon: const Icon(CupertinoIcons.xmark),
                  onPressed: () => Navigator.of(context).pop(),
                ),
              ],
            ),
            const SizedBox(height: 18),
            Center(
              child: Container(
                padding: const EdgeInsets.all(14),
                decoration: BoxDecoration(
                  color: AppColors.ink,
                  borderRadius: BorderRadius.circular(18),
                ),
                child: QrImageView(
                  data: _link,
                  version: QrVersions.auto,
                  size: 196,
                  backgroundColor: AppColors.panel,
                  eyeStyle: const QrEyeStyle(
                    eyeShape: QrEyeShape.square,
                    color: Color(0xFF111827),
                  ),
                  dataModuleStyle: const QrDataModuleStyle(
                    dataModuleShape: QrDataModuleShape.square,
                    color: Color(0xFF111827),
                  ),
                ),
              ),
            ),
            const SizedBox(height: 16),
            // \u0414\u043e\u0441\u0442\u0430\u0442\u043e\u0447\u043d\u043e QR-\u043a\u043e\u0434\u0430 \u0438 \u0441\u0441\u044b\u043b\u043a\u0438. \u0421\u0430\u043c\u0443 \u0441\u0441\u044b\u043b\u043a\u0443 \u043d\u0435 \u043f\u043e\u043a\u0430\u0437\u044b\u0432\u0430\u0435\u043c \u2014 \u0442\u043e\u043b\u044c\u043a\u043e
            // \u0434\u0435\u0439\u0441\u0442\u0432\u0438\u0435 \u00ab\u043a\u043e\u043f\u0438\u0440\u043e\u0432\u0430\u0442\u044c\u00bb (\u043a\u043e\u0434 \u043a\u043b\u0443\u0431\u0430 \u0443\u0431\u0440\u0430\u043b\u0438 \u0437\u0430 \u043d\u0435\u043d\u0430\u0434\u043e\u0431\u043d\u043e\u0441\u0442\u044c\u044e).
            _InviteValueCard(
              icon: CupertinoIcons.link,
              title:
                  '\u0421\u0441\u044b\u043b\u043a\u0430 \u043f\u0440\u0438\u0433\u043b\u0430\u0448\u0435\u043d\u0438\u044f',
              value:
                  '\u041d\u0430\u0436\u043c\u0438\u0442\u0435, \u0447\u0442\u043e\u0431\u044b \u0441\u043a\u043e\u043f\u0438\u0440\u043e\u0432\u0430\u0442\u044c',
              copyText: _link,
            ),
          ],
        ),
      ),
    );
  }
}

class _InviteValueCard extends StatelessWidget {
  final IconData icon;
  final String title, value, copyText;
  const _InviteValueCard({
    required this.icon,
    required this.title,
    required this.value,
    required this.copyText,
  });

  Future<void> _copy(BuildContext context) async {
    await Clipboard.setData(ClipboardData(text: copyText));
    if (!context.mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(
        content: Text(
          '\u0421\u043a\u043e\u043f\u0438\u0440\u043e\u0432\u0430\u043d\u043e',
        ),
        behavior: SnackBarBehavior.floating,
      ),
    );
  }

  @override
  Widget build(BuildContext context) => Material(
    color: Colors.transparent,
    child: InkWell(
      onTap: () => _copy(context),
      borderRadius: BorderRadius.circular(14),
      child: Ink(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: AppColors.bgCard,
          borderRadius: BorderRadius.circular(14),
          border: Border.all(color: AppColors.separator),
        ),
        child: Row(
          children: [
            Icon(icon, size: 18, color: AppColors.electricBlue),
            const SizedBox(width: 10),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    title,
                    style: Theme.of(context).textTheme.labelMedium?.copyWith(
                      color: AppColors.textTertiary,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                  const SizedBox(height: 2),
                  _FitText(
                    value,
                    style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                      color: AppColors.textPrimary,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ],
              ),
            ),
            IconButton.filledTonal(
              tooltip:
                  '\u0421\u043a\u043e\u043f\u0438\u0440\u043e\u0432\u0430\u0442\u044c',
              icon: const Icon(CupertinoIcons.doc_on_doc, size: 18),
              onPressed: () => _copy(context),
            ),
          ],
        ),
      ),
    ),
  );
}

class _ClubListTile extends ConsumerWidget {
  final Club club;
  const _ClubListTile({required this.club});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(clubProvider);
    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: AppColors.bgCard,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppColors.separator),
      ),
      child: Row(
        children: [
          _ClubLogo(logo: club.logo, size: 44),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _FitText(
                  club.name,
                  style: Theme.of(context).textTheme.titleSmall?.copyWith(
                    color: AppColors.textPrimary,
                    fontWeight: FontWeight.w800,
                  ),
                ),
                const SizedBox(height: 3),
                _FitText(
                  '${club.city ?? '\u0411\u0435\u0437 \u0433\u043e\u0440\u043e\u0434\u0430'} - ${club.memberCount} \u0447\u0435\u043b. - ${_kmLabel(club.totalKm)}',
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: AppColors.textSecondary,
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(width: 10),
          FilledButton(
            onPressed: state.isMutating
                ? null
                : () => ref.read(clubProvider.notifier).joinClub(club),
            child: Text(club.isRequestOnly ? 'Заявка' : 'Вступить'),
          ),
        ],
      ),
    );
  }
}

class _MemberTile extends StatelessWidget {
  final ClubMember member;
  const _MemberTile({required this.member});

  @override
  Widget build(BuildContext context) {
    final isOwner = member.role == 'owner';
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: AppColors.bgCard,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppColors.separator),
      ),
      child: Row(
        children: [
          CircleAvatar(
            radius: 19,
            backgroundColor: AppColors.bgElevated,
            child: Text(
              member.name.trim().isEmpty ? '?' : member.name.trim()[0],
              style: const TextStyle(fontWeight: FontWeight.w700),
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _FitText(
                  member.name,
                  style: Theme.of(context).textTheme.titleSmall?.copyWith(
                    color: AppColors.textPrimary,
                  ),
                ),
                if (isOwner)
                  Text(
                    'Владелец',
                    style: Theme.of(
                      context,
                    ).textTheme.labelSmall?.copyWith(color: AppColors.warning),
                  ),
              ],
            ),
          ),
          Text(
            _kmLabel(member.km),
            style: TextStyle(
              color: AppColors.electricBlue,
              fontSize: 14,
              fontWeight: FontWeight.w700,
            ),
          ),
        ],
      ),
    );
  }
}

class _RequestTile extends ConsumerWidget {
  final ClubJoinRequest request;
  const _RequestTile({required this.request});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(clubProvider);
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: AppColors.bgCard,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppColors.separator),
      ),
      child: Row(
        children: [
          Expanded(
            child: _FitText(
              request.name,
              style: Theme.of(context).textTheme.titleSmall,
            ),
          ),
          IconButton(
            tooltip: 'Отклонить',
            onPressed: state.isMutating
                ? null
                : () =>
                      ref.read(clubProvider.notifier).rejectRequest(request.id),
            icon: Icon(
              CupertinoIcons.xmark_circle_fill,
              color: AppColors.error,
            ),
          ),
          IconButton(
            tooltip: 'Одобрить',
            onPressed: state.isMutating
                ? null
                : () => ref
                      .read(clubProvider.notifier)
                      .approveRequest(request.id),
            icon: Icon(
              CupertinoIcons.check_mark_circled_solid,
              color: AppColors.success,
            ),
          ),
        ],
      ),
    );
  }
}

class _ClubFormSheet extends ConsumerStatefulWidget {
  final Club? existing;
  const _ClubFormSheet({this.existing});
  @override
  ConsumerState<_ClubFormSheet> createState() => _ClubFormSheetState();
}

class _ClubFormSheetState extends ConsumerState<_ClubFormSheet> {
  late final TextEditingController _nameCtrl;
  late final TextEditingController _cityCtrl;
  late final TextEditingController _descriptionCtrl;
  String _logo = 'K';
  String _joinPolicy = 'open';
  String _style = 'minimal';
  String? _error;

  @override
  void initState() {
    super.initState();
    final club = widget.existing;
    _nameCtrl = TextEditingController(text: club?.name ?? '');
    _cityCtrl = TextEditingController(
      text: club?.city ?? '\u042f\u043a\u0443\u0442\u0441\u043a',
    );
    _descriptionCtrl = TextEditingController(text: club?.description ?? '');
    _logo = club?.logo ?? 'K';
    _joinPolicy = club?.joinPolicy ?? 'open';
    _style = club?.style ?? 'minimal';
  }

  bool get _isEdit => widget.existing != null;

  @override
  void dispose() {
    _nameCtrl.dispose();
    _cityCtrl.dispose();
    _descriptionCtrl.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    final name = _nameCtrl.text.trim();
    if (name.isEmpty) {
      setState(() => _error = 'Введи название клуба');
      return;
    }
    final notifier = ref.read(clubProvider.notifier);
    if (_isEdit) {
      await notifier.updateClub(
        name: name,
        city: _cityCtrl.text.trim(),
        description: _descriptionCtrl.text.trim(),
        logo: _logo,
        joinPolicy: _joinPolicy,
        style: _style,
      );
    } else {
      await notifier.createClub(
        name: name,
        city: _cityCtrl.text.trim(),
        description: _descriptionCtrl.text.trim(),
        logo: _logo,
        joinPolicy: _joinPolicy,
        style: _style,
      );
    }
    if (!mounted) return;
    if (ref.read(clubProvider).error == null) {
      Navigator.of(context).pop();
    } else {
      setState(() => _error = ref.read(clubProvider).error);
    }
  }

  @override
  Widget build(BuildContext context) {
    final bottom = MediaQuery.of(context).viewInsets.bottom;
    final bottomGap = bottom > 0 ? 16.0 : 96.0;
    final state = ref.watch(clubProvider);
    return Padding(
      padding: EdgeInsets.fromLTRB(16, 16, 16, bottom + bottomGap),
      child: SingleChildScrollView(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          mainAxisSize: MainAxisSize.min,
          children: [
            Row(
              children: [
                Text(
                  _isEdit
                      ? '\u0420\u0435\u0434\u0430\u043a\u0442\u0438\u0440\u043e\u0432\u0430\u0442\u044c \u043a\u043b\u0443\u0431'
                      : '\u0421\u043e\u0437\u0434\u0430\u0442\u044c \u043a\u043b\u0443\u0431',
                  style: Theme.of(
                    context,
                  ).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w800),
                ),
                const Spacer(),
                IconButton(
                  tooltip: 'Закрыть',
                  icon: const Icon(CupertinoIcons.xmark),
                  onPressed: () => Navigator.of(context).pop(),
                ),
              ],
            ),
            const SizedBox(height: 12),
            _EditField(
              controller: _nameCtrl,
              label: 'Название клуба',
              icon: CupertinoIcons.person_2_fill,
            ),
            const SizedBox(height: 10),
            _EditField(
              controller: _cityCtrl,
              label: 'Город',
              icon: CupertinoIcons.location_fill,
            ),
            const SizedBox(height: 10),
            _EditField(
              controller: _descriptionCtrl,
              label: 'Описание',
              icon: CupertinoIcons.text_alignleft,
              maxLines: 3,
            ),
            const SizedBox(height: 14),
            // Логотип/фон фото грузятся на экране клуба (тап по аватарке и
            // иконка фона) — здесь только выбор буквы/эмодзи (по «Сохранить»).
            _LogoPicker(
              value: _logo,
              onChanged: (value) => setState(() => _logo = value),
            ),
            const SizedBox(height: 14),
            _StylePicker(
              value: _style,
              onChanged: (value) => setState(() => _style = value),
            ),
            const SizedBox(height: 14),
            CupertinoSlidingSegmentedControl<String>(
              groupValue: _joinPolicy,
              children: const {
                'open': Padding(
                  padding: EdgeInsets.symmetric(horizontal: 8),
                  child: Text('Открытый'),
                ),
                'request': Padding(
                  padding: EdgeInsets.symmetric(horizontal: 8),
                  child: Text('По заявке'),
                ),
              },
              onValueChanged: (value) {
                if (value != null) setState(() => _joinPolicy = value);
              },
            ),
            if (_error != null) ...[
              const SizedBox(height: 12),
              Text(_error!, style: TextStyle(color: AppColors.error)),
            ],
            const SizedBox(height: 18),
            SizedBox(
              height: 52,
              child: FilledButton(
                onPressed: state.isMutating ? null : _save,
                child: state.isMutating
                    ? const SizedBox(
                        width: 22,
                        height: 22,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : Text(
                        _isEdit
                            ? '\u0421\u043e\u0445\u0440\u0430\u043d\u0438\u0442\u044c'
                            : '\u0421\u043e\u0437\u0434\u0430\u0442\u044c',
                      ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _LogoPicker extends StatelessWidget {
  final String value;
  final ValueChanged<String> onChanged;
  const _LogoPicker({required this.value, required this.onChanged});

  @override
  Widget build(BuildContext context) {
    const logos = [
      'K',
      'Q',
      'RUN',
      '\u{26A1}',
      '\u{1F43A}',
      '\u{1F43B}',
      '\u{1F98A}',
      '\u{1F989}',
      '\u{1F3D4}',
      '\u{1F525}',
      '\u{1F3C3}',
      '\u{2B50}',
    ];

    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: AppColors.bgCard,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppColors.separator),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              _ClubLogo(logo: value, size: 48),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '\u041b\u043e\u0433\u043e\u0442\u0438\u043f \u043a\u043b\u0443\u0431\u0430',
                      style: Theme.of(context).textTheme.titleSmall?.copyWith(
                        color: AppColors.textPrimary,
                        fontWeight: FontWeight.w800,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      '\u0412\u044b\u0431\u0435\u0440\u0438 \u0431\u0443\u043a\u0432\u0443 \u0438\u043b\u0438 \u044d\u043c\u043e\u0434\u0437\u0438 \u0434\u043b\u044f \u043a\u043b\u0443\u0431\u0430.',
                      style: Theme.of(context).textTheme.bodySmall?.copyWith(
                        color: AppColors.textSecondary,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: logos.map((logo) {
              final selected = logo == value;
              return GestureDetector(
                onTap: () => onChanged(logo),
                child: AnimatedContainer(
                  duration: const Duration(milliseconds: 160),
                  width: 48,
                  height: 44,
                  alignment: Alignment.center,
                  decoration: BoxDecoration(
                    color: selected
                        ? AppColors.electricBlue.withValues(alpha: 0.20)
                        : AppColors.bgElevated,
                    borderRadius: BorderRadius.circular(12),
                    border: Border.all(
                      color: selected
                          ? AppColors.electricBlue
                          : AppColors.separator,
                    ),
                  ),
                  child: Text(
                    logo,
                    style: const TextStyle(
                      fontSize: 17,
                      fontWeight: FontWeight.w800,
                    ),
                  ),
                ),
              );
            }).toList(),
          ),
        ],
      ),
    );
  }
}

/// Пикер пресета оформления клуба: чипы с мини-превью (градиент + акцент-точка).
class _StylePicker extends StatelessWidget {
  final String value;
  final ValueChanged<String> onChanged;
  const _StylePicker({required this.value, required this.onChanged});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: AppColors.bgCard,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppColors.separator),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Стиль клуба',
            style: Theme.of(context).textTheme.titleSmall?.copyWith(
              color: AppColors.textPrimary,
              fontWeight: FontWeight.w800,
            ),
          ),
          const SizedBox(height: 2),
          Text(
            'Цвет, фон шапки и рамка логотипа — одним тапом.',
            style: Theme.of(
              context,
            ).textTheme.bodySmall?.copyWith(color: AppColors.textSecondary),
          ),
          const SizedBox(height: 12),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: ClubStyle.all.map((st) {
              final selected = st.key == value;
              return GestureDetector(
                onTap: () => onChanged(st.key),
                // Вся плашка кликабельна, а не только текст (иначе тап по «пустой»
                // части чипа не выбирает пресет).
                behavior: HitTestBehavior.opaque,
                child: AnimatedContainer(
                  duration: const Duration(milliseconds: 160),
                  padding: const EdgeInsets.symmetric(
                    horizontal: 12,
                    vertical: 9,
                  ),
                  decoration: BoxDecoration(
                    gradient: LinearGradient(
                      colors: [st.headerGradient[0], st.headerGradient[1]],
                      begin: Alignment.topLeft,
                      end: Alignment.bottomRight,
                    ),
                    borderRadius: BorderRadius.circular(12),
                    border: Border.all(
                      color: selected ? st.accent : AppColors.separator,
                      width: selected ? 2 : 1,
                    ),
                  ),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Container(
                        width: 14,
                        height: 14,
                        decoration: BoxDecoration(
                          color: st.accent,
                          shape: BoxShape.circle,
                          border: Border.all(color: AppColors.muted),
                        ),
                      ),
                      const SizedBox(width: 8),
                      Text(
                        st.label,
                        style: TextStyle(
                          color: AppColors.ink,
                          fontWeight: selected
                              ? FontWeight.w800
                              : FontWeight.w600,
                          fontSize: 13,
                        ),
                      ),
                    ],
                  ),
                ),
              );
            }).toList(),
          ),
        ],
      ),
    );
  }
}

class _EditField extends StatelessWidget {
  final TextEditingController controller;
  final String label;
  final IconData icon;
  final int maxLines;
  final TextInputType? keyboardType;
  const _EditField({
    required this.controller,
    required this.label,
    required this.icon,
    this.maxLines = 1,
    this.keyboardType,
  });
  @override
  Widget build(BuildContext context) => TextField(
    controller: controller,
    maxLines: maxLines,
    keyboardType: keyboardType,
    style: TextStyle(color: AppColors.textPrimary),
    decoration: InputDecoration(
      labelText: label,
      prefixIcon: Icon(icon, size: 18),
      filled: true,
      fillColor: AppColors.bgCard,
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: BorderSide(color: AppColors.separator),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: BorderSide(color: AppColors.separator),
      ),
    ),
  );
}

class _SectionHeader extends StatelessWidget {
  final String title;
  final String? trailing;
  const _SectionHeader({required this.title, this.trailing});
  @override
  Widget build(BuildContext context) => Row(
    mainAxisAlignment: MainAxisAlignment.spaceBetween,
    children: [
      Text(
        title,
        style: Theme.of(
          context,
        ).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700),
      ),
      if (trailing != null)
        Text(
          trailing!,
          style: Theme.of(
            context,
          ).textTheme.bodySmall?.copyWith(color: AppColors.textTertiary),
        ),
    ],
  );
}

class _ClubMetricCard extends StatelessWidget {
  final IconData icon;
  final String label;
  final String value;
  final Color color;
  const _ClubMetricCard({
    required this.icon,
    required this.label,
    required this.value,
    required this.color,
  });

  @override
  Widget build(BuildContext context) => Expanded(
    child: Container(
      height: 82,
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 9),
      decoration: BoxDecoration(
        color: AppColors.glassPaper,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppColors.line),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(icon, size: 14, color: color),
              const SizedBox(width: 5),
              Expanded(
                child: _FitText(
                  label,
                  style: Theme.of(context).textTheme.labelSmall?.copyWith(
                    color: AppColors.textSecondary,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
            ],
          ),
          const Spacer(),
          _FitText(
            value,
            style: Theme.of(context).textTheme.titleMedium?.copyWith(
              color: AppColors.textPrimary,
              fontWeight: FontWeight.w900,
            ),
          ),
        ],
      ),
    ),
  );
}

class _ClubLogo extends StatelessWidget {
  final String logo;
  final double size;
  const _ClubLogo({required this.logo, required this.size});

  @override
  Widget build(BuildContext context) {
    // Фото-логотип (загружен владельцем) рисуем картинкой; иначе — буква/эмодзи.
    if (clubLogoIsPhoto(logo)) {
      return ClipRRect(
        borderRadius: BorderRadius.circular(size * 0.28),
        child: Image.network(
          resolveClubMediaUrl(logo),
          width: size,
          height: size,
          fit: BoxFit.cover,
          errorBuilder: (_, __, ___) => _letter(context),
        ),
      );
    }
    return _letter(context);
  }

  Widget _letter(BuildContext context) => Container(
    width: size,
    height: size,
    decoration: BoxDecoration(
      color: AppColors.electricBlue.withValues(alpha: 0.2),
      borderRadius: BorderRadius.circular(size * 0.28),
      border: Border.all(color: AppColors.electricBlue.withValues(alpha: 0.45)),
    ),
    alignment: Alignment.center,
    child: Text(
      logo.isEmpty ? 'K' : logo,
      style: TextStyle(
        fontSize: size * 0.32,
        fontWeight: FontWeight.w900,
        color: AppColors.electricBlue,
      ),
    ),
  );
}

class _ClubBadge extends StatelessWidget {
  final String label;
  final Color color;
  const _ClubBadge({required this.label, required this.color});
  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
    decoration: BoxDecoration(
      color: AppColors.glassPaper,
      borderRadius: BorderRadius.circular(999),
      border: Border.all(color: AppColors.line),
    ),
    child: Text(
      label,
      // Тёмный текст по цветной плашке: цветной по цветному не проходит норму.
      style: TextStyle(color: color, fontSize: 12, fontWeight: FontWeight.w800),
    ),
  );
}

class _StatusCard extends StatelessWidget {
  final IconData icon;
  final String title, subtitle;
  final Color color;
  final String? actionLabel;
  final IconData? actionIcon;
  final VoidCallback? onAction;
  const _StatusCard({
    required this.icon,
    required this.title,
    required this.subtitle,
    required this.color,
    this.actionLabel,
    this.actionIcon,
    this.onAction,
  });
  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.all(16),
    decoration: BoxDecoration(
      color: AppColors.bgCard,
      borderRadius: BorderRadius.circular(16),
      border: Border.all(color: color.withValues(alpha: 0.25)),
    ),
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Icon(icon, color: color, size: 24),
        const SizedBox(width: 12),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                title,
                style: Theme.of(context).textTheme.titleSmall?.copyWith(
                  color: AppColors.textPrimary,
                  fontWeight: FontWeight.w800,
                ),
              ),
              const SizedBox(height: 4),
              Text(
                subtitle,
                style: Theme.of(
                  context,
                ).textTheme.bodySmall?.copyWith(color: AppColors.textSecondary),
              ),
              if (actionLabel != null && onAction != null) ...[
                const SizedBox(height: 12),
                SizedBox(
                  width: double.infinity,
                  height: 44,
                  child: FilledButton.icon(
                    onPressed: onAction,
                    icon: Icon(
                      actionIcon ?? CupertinoIcons.arrow_right,
                      size: 17,
                    ),
                    label: Text(actionLabel!),
                  ),
                ),
              ],
            ],
          ),
        ),
      ],
    ),
  );
}

class _LoadingCard extends StatelessWidget {
  const _LoadingCard();
  @override
  Widget build(BuildContext context) => const Center(
    child: Padding(
      padding: EdgeInsets.all(32),
      child: CircularProgressIndicator(),
    ),
  );
}

class _EmptyCard extends StatelessWidget {
  final String title, subtitle;
  const _EmptyCard({required this.title, required this.subtitle});
  @override
  Widget build(BuildContext context) => _StatusCard(
    icon: CupertinoIcons.circle,
    title: title,
    subtitle: subtitle,
    color: AppColors.textTertiary,
  );
}

class _InfoCard extends StatelessWidget {
  final String text;
  const _InfoCard({required this.text});
  @override
  Widget build(BuildContext context) => Container(
    width: double.infinity,
    padding: const EdgeInsets.all(16),
    decoration: BoxDecoration(
      color: AppColors.bgCard,
      borderRadius: BorderRadius.circular(16),
      border: Border.all(color: AppColors.separator),
    ),
    child: Text(
      text,
      style: Theme.of(
        context,
      ).textTheme.bodyMedium?.copyWith(color: AppColors.textSecondary),
    ),
  );
}

class _FutureModuleCard extends StatelessWidget {
  final IconData icon;
  final String title, subtitle;
  const _FutureModuleCard({
    required this.icon,
    required this.title,
    required this.subtitle,
  });
  @override
  Widget build(BuildContext context) => _StatusCard(
    icon: icon,
    title: title,
    subtitle: subtitle,
    color: AppColors.info,
  );
}

/// Ф6 «Клубная война»: щит района — реальный лидерборд районов
/// (GET /leaderboard/districts). Мой район подсвечен лаймом.
class _DistrictWarCard extends ConsumerWidget {
  const _DistrictWarCard();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(clubWarProvider);
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: AppColors.paper,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AppColors.line),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Война района',
            style: Theme.of(context).textTheme.titleMedium?.copyWith(
              fontWeight: FontWeight.w800,
            ),
          ),
          const SizedBox(height: 2),
          Text(
            'Чей клуб держит больше земли',
            style: TextStyle(fontSize: 12, color: AppColors.muted),
          ),
          const SizedBox(height: 12),
          async.when(
            loading: () => const Center(
              child: Padding(
                padding: EdgeInsets.all(12),
                child: CupertinoActivityIndicator(),
              ),
            ),
            error: (_, __) => Text(
              'Не удалось загрузить районы — потяни вниз, чтобы обновить.',
              style: TextStyle(fontSize: 12.5, color: AppColors.faint),
            ),
            data: (war) {
              if (war.standings.isEmpty && war.threats.isEmpty) {
                return Text(
                  'Пока никто не захватил территорию. Замкни первый круг!',
                  style: TextStyle(fontSize: 12.5, color: AppColors.faint),
                );
              }
              final maxArea = war.standings
                  .map((d) => d.areaM2)
                  .fold<double>(1, (a, b) => a > b ? a : b);
              return Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  for (final d in war.standings) ...[
                    Padding(
                      padding: const EdgeInsets.only(bottom: 8),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Row(
                            children: [
                              Expanded(
                                child: Text(
                                  d.isMine
                                      ? '${d.name} · твой клуб'
                                      : d.name,
                                  maxLines: 1,
                                  overflow: TextOverflow.ellipsis,
                                  style: TextStyle(
                                    fontSize: 13,
                                    fontWeight: d.isMine
                                        ? FontWeight.w800
                                        : FontWeight.w600,
                                    color: AppColors.ink,
                                  ),
                                ),
                              ),
                              Text(
                                _fmtArea(d.areaM2),
                                style: TextStyle(
                                  fontSize: 12,
                                  fontWeight: FontWeight.w700,
                                  color: d.isMine
                                      ? AppColors.limeDeep
                                      : AppColors.muted,
                                ),
                              ),
                            ],
                          ),
                          const SizedBox(height: 4),
                          ClipRRect(
                            borderRadius: BorderRadius.circular(3),
                            child: LinearProgressIndicator(
                              value: (d.areaM2 / maxArea).clamp(0.02, 1.0),
                              minHeight: 5,
                              backgroundColor: AppColors.soft,
                              valueColor: AlwaysStoppedAnimation(
                                d.isMine
                                    ? AppColors.limeDeep
                                    : AppColors.zoneNeutral,
                              ),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ],
                  if (war.threats.isNotEmpty) ...[
                    const SizedBox(height: 6),
                    Text(
                      'Угрозы недели',
                      style: TextStyle(
                        fontSize: 12.5,
                        fontWeight: FontWeight.w800,
                        color: AppColors.warm,
                      ),
                    ),
                    const SizedBox(height: 6),
                    for (final t in war.threats.take(5))
                      Padding(
                        padding: const EdgeInsets.only(bottom: 5),
                        child: Row(
                          children: [
                            Icon(
                              CupertinoIcons.flag_fill,
                              size: 12,
                              color: AppColors.warm,
                            ),
                            const SizedBox(width: 7),
                            Expanded(
                              child: Text(
                                '${t.attackerName} отрезал '
                                '${_fmtArea(t.areaM2)} у '
                                '${t.mine ? 'тебя' : t.victimName}',
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: TextStyle(
                                  fontSize: 12.5,
                                  color: AppColors.ink,
                                ),
                              ),
                            ),
                          ],
                        ),
                      ),
                    const SizedBox(height: 4),
                    SizedBox(
                      width: double.infinity,
                      child: OutlinedButton(
                        onPressed: () => context.go('/run'),
                        child: const Text('Вернуть бегом'),
                      ),
                    ),
                  ],
                ],
              );
            },
          ),
        ],
      ),
    );
  }

  static String _fmtArea(double m2) {
    if (m2 >= 10000) return '${(m2 / 10000).toStringAsFixed(1)} га';
    return '${m2.round()} м²';
  }
}
