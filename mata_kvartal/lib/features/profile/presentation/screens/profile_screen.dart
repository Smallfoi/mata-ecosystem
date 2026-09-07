import '../../../../shared/widgets/tab_visibility.dart';
import 'dart:async';

import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:image_picker/image_picker.dart';

import '../../../../core/api/api_config.dart';
import '../../../../core/theme/app_colors.dart';
import '../../../auth/data/auth_provider.dart';
import '../../../loyalty/data/loyalty_provider.dart';
import '../../../loyalty/presentation/widgets/loyalty_card.dart';
import '../../../notifications/data/notifications_provider.dart';
import '../../../run/data/completed_runs_provider.dart';
import '../../../medals/data/medal_defs.dart';
import '../../../medals/data/medals_provider.dart';
import '../../data/me_stats_provider.dart';
import '../../data/digest_service.dart';
import '../../../league/data/division_provider.dart';
import '../../../../core/theme/app_theme.dart';
import '../../../../shared/widgets/kvartal_logo.dart';
import '../../../shoes/data/shoes_provider.dart';
import '../../../workouts/data/health_sync.dart';
import '../../../territory/data/territory_provider.dart';

class ProfileScreen extends ConsumerStatefulWidget {
  const ProfileScreen({super.key});

  @override
  ConsumerState<ProfileScreen> createState() => _ProfileScreenState();
}

class _ProfileScreenState extends ConsumerState<ProfileScreen>
    with WidgetsBindingObserver, TabVisibility {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    // При показе профиля тянем баланс/обувь И свежий профиль (единый аватар).
    WidgetsBinding.instance.addPostFrameCallback((_) => _refresh());
  }

  @override
  void onTabShown() => _refresh();   // вернулись на вкладку — тянем свежее

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    // Вернулись в приложение → перечитать профиль (аватар мог смениться в другом).
    if (state == AppLifecycleState.resumed) {
      ref.read(authProvider.notifier).restoreSession();
      ref.read(loyaltyProvider.notifier).refresh();
      ref.read(healthSyncProvider.notifier).autoSync();
      ref.read(notificationsProvider.notifier).refresh();
    }
  }

  /// Pull-to-refresh: тянем баланс/профиль/статистику с бэка прямо на экране.
  /// (обновление между переходами экранов остаётся — это в дополнение к нему).
  Future<void> _refresh() async {
    ref.invalidate(footprintAreaProvider);
    await Future.wait([
      ref.read(loyaltyProvider.notifier).refresh(),
      ref.read(shoesProvider.notifier).refresh(),
      ref.read(authProvider.notifier).restoreSession(),
      ref.read(completedRunsProvider.notifier).load(),
      // Лента: счётчик на колокольчике живёт здесь, поэтому обновляем его
      // вместе с экраном — иначе он показывал бы цифру со времени входа.
      ref.read(notificationsProvider.notifier).refresh(),
      // Тренировки с часов: пришли в Health Connect — подтянем и начислим.
      ref.read(healthSyncProvider.notifier).autoSync(),
    ]);
      // Ф7: свежий дайджест недели + перепланирование уведомления вс 20:00.
    ref.invalidate(weekDigestProvider);
    unawaited(ref.read(weekDigestProvider.future).catchError((_) => null));
}

  @override
  Widget build(BuildContext context) {
    final auth = ref.watch(authProvider);
    final user = auth.user;

    return Scaffold(
      backgroundColor: AppColors.bgDark,
      body: RefreshIndicator(
        onRefresh: _refresh,
        color: AppColors.electricBlue,
        backgroundColor: AppColors.bgCard,
        child: CustomScrollView(
          // Свой ключ хранения прокрутки: иначе позиция делится с экраном Клуба.
          key: const PageStorageKey<String>('profile-scroll'),
          physics: const AlwaysScrollableScrollPhysics(),
          slivers: [
            _ProfileAppBar(user: user),
            SliverToBoxAdapter(
              child: Padding(
                // extendBody:true + полупрозрачный таб-бар перекрывают низ контента.
                // Нижний запас 96px, чтобы блок «Активность» (последний) не обрезался
                // под баром (как в club_screen).
                padding: const EdgeInsets.fromLTRB(16, 16, 16, 96),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    // Ф4 «Статус бегуна»: уровень города + недельный стрик.
                    const _LevelHeader(),
                    const SizedBox(height: 12),
                    const _StreakRow(),
                    const SizedBox(height: 12),
                    const _PointsCard(),
                    const SizedBox(height: 12),
                    const _StatsRow(),
                    const SizedBox(height: 12),
                    const _FootprintCard(),
                    const SizedBox(height: 12),
                    const _ShoesCard(),
                    const SizedBox(height: 12),
                    // «Сервис» больше не отдельная вкладка внизу (D-45): вход сюда.
                    _SettingsTile(
                      icon: CupertinoIcons.wrench,
                      label: 'Сервис · инструменты бегуна',
                      onTap: () => context.push('/tools'),
                    ),
                    _AccountCard(user: user),
                    const SizedBox(height: 12),
                    const _TrophyEntryRow(),
                    const SizedBox(height: 24),
                    Text(
                      'Активность',
                      style: Theme.of(context).textTheme.titleMedium?.copyWith(
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    const SizedBox(height: 10),
                    const _ActivityHeatmap(),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// Счётчик непрочитанного: постоянная пара «заливка + текст», одинаковая в обеих
/// темах — маленькая цифра обязана читаться всегда.
const Color _badgeFill = Color(0xFFD9483B);
const Color _badgeInk = Color(0xFFFFFFFF);

class _NotificationsBell extends StatelessWidget {
  final int unread;
  const _NotificationsBell({required this.unread});

  @override
  Widget build(BuildContext context) {
    return Stack(
      alignment: Alignment.center,
      children: [
        IconButton(
          tooltip: 'Уведомления',
          icon: const Icon(CupertinoIcons.bell, size: 20),
          onPressed: () => context.push('/profile/notifications'),
        ),
        if (unread > 0)
          Positioned(
            right: 6,
            top: 8,
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 4),
              constraints: const BoxConstraints(minWidth: 16, minHeight: 16),
              decoration: BoxDecoration(
                // Константная пара к заливке: `error` в графитовой теме светлеет
                // до лососевого, а `ink` там же становится почти белым — цифра
                // на счётчике пропадала. На цветной заливке инвертируемые токены
                // не используем (правило владельца после бага с лаймом).
                color: _badgeFill,
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: AppColors.bgDark, width: 1.5),
              ),
              alignment: Alignment.center,
              child: Text(
                unread > 9 ? '9+' : '$unread',
                style: const TextStyle(
                  color: _badgeInk,
                  fontSize: 9,
                  fontWeight: FontWeight.w800,
                  height: 1,
                ),
              ),
            ),
          ),
      ],
    );
  }
}

class _ProfileAppBar extends ConsumerWidget {
  final AuthUser? user;
  const _ProfileAppBar({required this.user});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final name = user?.name.trim().isNotEmpty == true
        ? user!.name
        : 'Бегун КВАРТАЛ';
    final city = user?.city?.trim().isNotEmpty == true
        ? user!.city!
        : 'Город не выбран';

    return SliverAppBar(
      expandedHeight: 228,
      pinned: true,
      backgroundColor: AppColors.bgDark,
      actions: [
        _NotificationsBell(unread: ref.watch(notificationsProvider).unread),
        IconButton(
          tooltip: 'Настройки',
          icon: const Icon(CupertinoIcons.settings, size: 20),
          onPressed: () => context.push('/profile/settings'),
        ),
      ],
      flexibleSpace: FlexibleSpaceBar(
        background: Container(
          decoration: BoxDecoration(color: AppColors.bg),
          child: SafeArea(
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                const SizedBox(height: 18),
                GestureDetector(
                  onTap: () => context.push('/profile/edit'),
                  child: Stack(
                    children: [
                      _Avatar(name: name, size: 84, avatarPath: user?.avatarPath),
                      Positioned(
                        right: 0,
                        bottom: 0,
                        child: Container(
                          padding: const EdgeInsets.all(5),
                          decoration: BoxDecoration(
                            color: AppColors.electricBlue,
                            shape: BoxShape.circle,
                          ),
                          child: Icon(
                            CupertinoIcons.pencil,
                            size: 11,
                            color: AppColors.ink,
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 10),
                Text(
                  name,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                    fontWeight: FontWeight.w800,
                  ),
                ),
                const SizedBox(height: 6),
                Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 14,
                    vertical: 5,
                  ),
                  decoration: BoxDecoration(
                    color: AppColors.soft,
                    borderRadius: BorderRadius.circular(999),
                    border: Border.all(color: AppColors.line),
                  ),
                  child: Text(
                    city,
                    style: TextStyle(
                      color: AppColors.ink,
                      fontSize: 12,
                      fontWeight: FontWeight.w700,
                      letterSpacing: 0.5,
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
      title: Text(
        '\u041f\u0440\u043e\u0444\u0438\u043b\u044c',
        style: Theme.of(context).textTheme.titleLarge,
      ),
    );
  }
}

class _Avatar extends StatelessWidget {
  final String name;
  final double size;

  /// Единый аватар экосистемы (URL с сервера) — если задан, рисуем фото.
  final String? avatarPath;

  const _Avatar({required this.name, required this.size, this.avatarPath});

  String get _initials {
    final parts = name
        .trim()
        .split(RegExp(r'\s+'))
        .where((p) => p.isNotEmpty)
        .toList();
    if (parts.length >= 2) return '${parts[0][0]}${parts[1][0]}'.toUpperCase();
    return parts.isNotEmpty ? parts.first[0].toUpperCase() : '?';
  }

  bool get _hasPhoto {
    final p = avatarPath;
    return p != null && (p.startsWith('http') || p.startsWith('/media'));
  }

  Widget _initialsCircle() => Container(
    width: size,
    height: size,
    decoration: BoxDecoration(
      shape: BoxShape.circle,
      color: AppColors.electricBlue.withValues(alpha: 0.2),
      border: Border.all(
        color: AppColors.electricBlue.withValues(alpha: 0.5),
        width: 2,
      ),
    ),
    child: Center(
      child: Text(
        _initials,
        style: TextStyle(
          fontSize: size * 0.32,
          fontWeight: FontWeight.w800,
          color: AppColors.electricBlue,
        ),
      ),
    ),
  );

  @override
  Widget build(BuildContext context) {
    if (!_hasPhoto) return _initialsCircle();
    return Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        border: Border.all(
          color: AppColors.electricBlue.withValues(alpha: 0.5),
          width: 2,
        ),
      ),
      child: ClipOval(
        child: Image.network(
          ApiConfig.resolveMedia(avatarPath),
          width: size,
          height: size,
          fit: BoxFit.cover,
          errorBuilder: (_, __, ___) => _initialsCircle(),
        ),
      ),
    );
  }
}

class _AccountCard extends ConsumerWidget {
  final AuthUser? user;
  const _AccountCard({required this.user});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
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
              Text(
                'Аккаунт',
                style: Theme.of(
                  context,
                ).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w800),
              ),
              const Spacer(),
              IconButton(
                tooltip: 'Редактировать',
                onPressed: () => context.push('/profile/edit'),
                icon: const Icon(CupertinoIcons.pencil, size: 18),
              ),
            ],
          ),
          const SizedBox(height: 4),
          _InfoLine(
            icon: CupertinoIcons.phone,
            label: 'Телефон',
            value: user?.phone ?? 'Не указан',
          ),
          _InfoLine(
            icon: CupertinoIcons.mail,
            label: 'Email',
            value:
                (user?.email.isNotEmpty == true &&
                    !user!.email.endsWith('@kvartal.local'))
                ? user!.email
                : '\u041d\u0435 \u0443\u043a\u0430\u0437\u0430\u043d',
          ),
          _InfoLine(
            icon: CupertinoIcons.location,
            label: '\u0413\u043e\u0440\u043e\u0434',
            value: user?.city?.isNotEmpty == true
                ? user!.city!
                : '\u041d\u0435 \u0443\u043a\u0430\u0437\u0430\u043d',
          ),
        ],
      ),
    );
  }
}

class _InfoLine extends StatelessWidget {
  final IconData icon;
  final String label;
  final String value;

  const _InfoLine({
    required this.icon,
    required this.label,
    required this.value,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: 10),
      child: Row(
        children: [
          Icon(icon, size: 16, color: AppColors.textTertiary),
          const SizedBox(width: 10),
          Text(label, style: Theme.of(context).textTheme.bodySmall),
          const SizedBox(width: 12),
          Expanded(
            child: Text(
              value,
              textAlign: TextAlign.right,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: Theme.of(
                context,
              ).textTheme.bodyMedium?.copyWith(color: AppColors.textPrimary),
            ),
          ),
        ],
      ),
    );
  }
}

class EditProfileScreen extends ConsumerStatefulWidget {
  const EditProfileScreen({super.key});

  @override
  ConsumerState<EditProfileScreen> createState() => _EditProfileScreenState();
}

class _EditProfileScreenState extends ConsumerState<EditProfileScreen> {
  late final TextEditingController _nameCtrl;
  late final TextEditingController _phoneCtrl;
  late final TextEditingController _emailCtrl;
  late final TextEditingController _cityCtrl;
  String? _error;

  @override
  void initState() {
    super.initState();
    final user = ref.read(authProvider).user;
    _nameCtrl = TextEditingController(
      text: user?.name == 'Runner' ? '' : user?.name ?? '',
    );
    _phoneCtrl = TextEditingController(
      text: user?.phone ?? ref.read(authProvider).phone,
    );
    _emailCtrl = TextEditingController(
      text: user?.email.endsWith('@kvartal.local') == true
          ? ''
          : user?.email ?? '',
    );
    _cityCtrl = TextEditingController(text: user?.city ?? 'Якутск');
  }

  @override
  void dispose() {
    _nameCtrl.dispose();
    _phoneCtrl.dispose();
    _emailCtrl.dispose();
    _cityCtrl.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    if (_nameCtrl.text.trim().isEmpty) {
      setState(
        () => _error =
            '\u0412\u0432\u0435\u0434\u0438 \u0438\u043c\u044f \u0438\u043b\u0438 \u043d\u0438\u043a',
      );
      return;
    }

    final ok = await ref
        .read(authProvider.notifier)
        .updateProfile(
          name: _nameCtrl.text.trim(),
          phone: _phoneCtrl.text.trim(),
          email: _emailCtrl.text.trim().isEmpty ? null : _emailCtrl.text.trim(),
          city: _cityCtrl.text.trim(),
        );
    if (!mounted) return;
    if (ok) {
      context.pop();
    } else {
      setState(
        () => _error =
            ref.read(authProvider).error ?? 'Не удалось сохранить профиль',
      );
    }
  }

  Future<void> _pickAvatar() async {
    final hasPhoto = (ref.read(authProvider).user?.avatarPath ?? '').isNotEmpty;
    final action = await showCupertinoModalPopup<String>(
      context: context,
      builder: (ctx) => CupertinoActionSheet(
        title: const Text('Фото профиля'),
        message: const Text('Один аватар для всех приложений экосистемы МАТА.'),
        actions: [
          CupertinoActionSheetAction(
            onPressed: () => Navigator.pop(ctx, 'upload'),
            child: Text(hasPhoto ? 'Сменить фото' : 'Загрузить фото'),
          ),
          if (hasPhoto)
            CupertinoActionSheetAction(
              isDestructiveAction: true,
              onPressed: () => Navigator.pop(ctx, 'remove'),
              child: const Text('Убрать фото'),
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
        maxWidth: 800,
        imageQuality: 85,
      );
      if (picked != null) {
        await ref.read(authProvider.notifier).uploadAvatar(picked.path);
      }
    } else if (action == 'remove') {
      await ref.read(authProvider.notifier).removeAvatar();
    }
  }

  @override
  Widget build(BuildContext context) {
    final auth = ref.watch(authProvider);

    return Scaffold(
      backgroundColor: AppColors.bgDark,
      appBar: AppBar(
        backgroundColor: AppColors.bgDark,
        title: const Text('Редактировать профиль'),
      ),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Center(
                child: GestureDetector(
                  onTap: auth.isLoading ? null : _pickAvatar,
                  behavior: HitTestBehavior.opaque,
                  child: Stack(
                    clipBehavior: Clip.none,
                    children: [
                      _Avatar(
                        name: _nameCtrl.text.trim().isEmpty
                            ? 'КВАРТАЛ'
                            : _nameCtrl.text,
                        size: 92,
                        avatarPath: auth.user?.avatarPath,
                      ),
                      Positioned(
                        right: -2,
                        bottom: -2,
                        child: Container(
                          padding: const EdgeInsets.all(6),
                          decoration: BoxDecoration(
                            color: AppColors.electricBlue,
                            shape: BoxShape.circle,
                            border: Border.all(
                              color: AppColors.bgDark,
                              width: 2,
                            ),
                          ),
                          child: Icon(
                            CupertinoIcons.camera_fill,
                            size: 13,
                            color: AppColors.ink,
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 20),
              _EditField(
                controller: _nameCtrl,
                label: 'Имя, фамилия или ник',
                icon: CupertinoIcons.person,
              ),
              const SizedBox(height: 12),
              _EditField(
                controller: _phoneCtrl,
                label: '\u0422\u0435\u043b\u0435\u0444\u043e\u043d',
                icon: CupertinoIcons.phone,
                keyboardType: TextInputType.phone,
              ),
              const SizedBox(height: 12),
              _EditField(
                controller: _emailCtrl,
                label: 'Email',
                icon: CupertinoIcons.mail,
                keyboardType: TextInputType.emailAddress,
              ),
              const SizedBox(height: 12),
              _EditField(
                controller: _cityCtrl,
                label: '\u0413\u043e\u0440\u043e\u0434',
                icon: CupertinoIcons.location,
              ),
              if (_error != null) ...[
                const SizedBox(height: 14),
                Text(_error!, style: TextStyle(color: AppColors.error)),
              ],
              const SizedBox(height: 24),
              SizedBox(
                height: 54,
                child: FilledButton(
                  onPressed: auth.isLoading ? null : _save,
                  child: auth.isLoading
                      ? const SizedBox(
                          width: 22,
                          height: 22,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Text('Сохранить'),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _EditField extends StatelessWidget {
  final TextEditingController controller;
  final String label;
  final IconData icon;
  final TextInputType? keyboardType;

  const _EditField({
    required this.controller,
    required this.label,
    required this.icon,
    this.keyboardType,
  });

  @override
  Widget build(BuildContext context) {
    return TextField(
      controller: controller,
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
}

class SettingsScreen extends ConsumerWidget {
  const SettingsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Scaffold(
      backgroundColor: AppColors.bgDark,
      appBar: AppBar(
        backgroundColor: AppColors.bgDark,
        title: const Text('Настройки'),
      ),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            _SettingsTile(
              icon: CupertinoIcons.person_crop_circle,
              label: '\u041f\u0440\u043e\u0444\u0438\u043b\u044c',
              onTap: () => context.push('/profile/edit'),
            ),
            _SettingsTile(
              icon: CupertinoIcons.chart_bar_alt_fill,
              label: '\u041c\u043e\u044f \u0441\u0442\u0430\u0442\u0438\u0441\u0442\u0438\u043a\u0430',
              onTap: () => context.push('/profile/stats'),
            ),
            _SettingsTile(
              icon: CupertinoIcons.location_solid,
              label:
                  '\u0413\u0435\u043e\u043b\u043e\u043a\u0430\u0446\u0438\u044f \u0438 \u0444\u043e\u043d\u043e\u0432\u044b\u0439 \u0440\u0435\u0436\u0438\u043c',
              onTap: () => context.push('/run/location-access'),
            ),
            _SettingsTile(
              icon: CupertinoIcons.time,
              label: 'Часы и приложения',
              onTap: () => context.push('/profile/watch'),
            ),
            _SettingsTile(
              icon: CupertinoIcons.moon_fill,
              label: 'Тема',
              onTap: () => context.push('/profile/theme'),
            ),
            _SettingsTile(
              icon: CupertinoIcons.bell_fill,
              label:
                  '\u0423\u0432\u0435\u0434\u043e\u043c\u043b\u0435\u043d\u0438\u044f',
              onTap: () => context.push('/profile/notifications'),
            ),
            _SettingsTile(
              icon: CupertinoIcons.lock_fill,
              label:
                  '\u041a\u043e\u043d\u0444\u0438\u0434\u0435\u043d\u0446\u0438\u0430\u043b\u044c\u043d\u043e\u0441\u0442\u044c \u0438 \u0434\u0430\u043d\u043d\u044b\u0435',
              onTap: () => context.push('/profile/privacy'),
            ),
            _SettingsTile(
              icon: CupertinoIcons.doc_text_fill,
              label: '\u0414\u043e\u043a\u0443\u043c\u0435\u043d\u0442\u044b',
              onTap: () => context.push('/profile/legal'),
            ),
            _SettingsTile(
              icon: CupertinoIcons.question_circle_fill,
              label: '\u041f\u043e\u0434\u0434\u0435\u0440\u0436\u043a\u0430',
              onTap: () {},
            ),
            _SettingsTile(
              icon: CupertinoIcons.info_circle_fill,
              label:
                  '\u041e \u043f\u0440\u0438\u043b\u043e\u0436\u0435\u043d\u0438\u0438',
              onTap: () => context.push('/profile/about'),
            ),
            const SizedBox(height: 16),
            _SettingsTile(
              icon: CupertinoIcons.square_arrow_right,
              label:
                  '\u0412\u044b\u0439\u0442\u0438 \u0438\u0437 \u0430\u043a\u043a\u0430\u0443\u043d\u0442\u0430',
              destructive: true,
              onTap: () async {
                await ref.read(authProvider.notifier).logout();
                if (context.mounted) context.go('/auth/phone');
              },
            ),
          ],
        ),
      ),
    );
  }
}

class _SettingsTile extends StatelessWidget {
  final IconData icon;
  final String label;
  final VoidCallback onTap;
  final bool destructive;

  const _SettingsTile({
    required this.icon,
    required this.label,
    required this.onTap,
    this.destructive = false,
  });

  @override
  Widget build(BuildContext context) {
    final color = destructive ? AppColors.error : AppColors.textPrimary;
    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      decoration: BoxDecoration(
        color: AppColors.bgCard,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.separator),
      ),
      child: ListTile(
        leading: Icon(icon, color: color, size: 20),
        title: Text(
          label,
          style: Theme.of(context).textTheme.bodyMedium?.copyWith(color: color),
        ),
        trailing: Icon(
          CupertinoIcons.chevron_right,
          color: AppColors.textDisabled,
          size: 16,
        ),
        onTap: onTap,
      ),
    );
  }
}

class _PointsCard extends ConsumerWidget {
  const _PointsCard();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final loyalty = ref.watch(loyaltyProvider);

    return GestureDetector(
      onTap: () => context.push('/profile/points'),
      child: Container(
        padding: const EdgeInsets.all(18),
        decoration: BoxDecoration(
          color: AppColors.graphite,
          borderRadius: BorderRadius.circular(22),
        ),
        child: Row(
          children: [
            Container(
              width: 46,
              height: 46,
              decoration: BoxDecoration(
                color: AppColors.onDark.withValues(alpha: 0.12),
                shape: BoxShape.circle,
              ),
              child: const Icon(
                CupertinoIcons.star_fill,
                color: AppColors.lime,
                size: 24,
              ),
            ),
            const SizedBox(width: 14),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    'Баллы экосистемы',
                    style: Theme.of(context).textTheme.bodySmall?.copyWith(
                      color: AppColors.onDark.withValues(alpha: 0.66),
                    ),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    loyalty.isLoading && !loyalty.loaded
                        ? '…'
                        : '${loyalty.balance}',
                    style: Theme.of(context).textTheme.headlineMedium?.copyWith(
                      color: AppColors.lime,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ],
              ),
            ),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
              decoration: BoxDecoration(
                color: AppColors.onDark.withValues(alpha: 0.12),
                borderRadius: BorderRadius.circular(999),
              ),
              child: Text(
                loyalty.levelTitle,
                style: TextStyle(
                  color: AppColors.onDark,
                  fontSize: 13,
                  fontWeight: FontWeight.w800,
                ),
              ),
            ),
            const SizedBox(width: 6),
            Icon(
              CupertinoIcons.chevron_right,
              color: AppColors.onDark.withValues(alpha: 0.55),
              size: 18,
            ),
          ],
        ),
      ),
    );
  }
}

/// Источник баллов → иконка и подпись для истории.
({IconData icon, String label}) _loyaltySourceMeta(String source) {
  switch (source) {
    case 'runnerRun':
      return (icon: Icons.directions_run, label: 'Пробежка');
    case 'runnerTerritory':
      return (icon: CupertinoIcons.flag_fill, label: 'Захват территории');
    case 'runnerCompetition':
      return (icon: Icons.emoji_events, label: 'Соревнование');
    case 'registration':
      return (icon: CupertinoIcons.gift_fill, label: 'Бонус');
    case 'purchase':
      return (icon: CupertinoIcons.bag_fill, label: 'Покупка');
    case 'redeem':
      return (icon: CupertinoIcons.minus_circle, label: 'Списание');
    default:
      return (icon: CupertinoIcons.star_fill, label: 'Баллы');
  }
}


/// История баллов экосистемы (за что начислено/списано). Открывается тапом по карточке.
class PointsHistoryScreen extends ConsumerStatefulWidget {
  const PointsHistoryScreen({super.key});

  @override
  ConsumerState<PointsHistoryScreen> createState() =>
      _PointsHistoryScreenState();
}

/// Кошелёк (Ф7 «Экономика баллов», утверждено 31.08.2026): карта лояльности,
/// строка ценности «1 балл = 1 ₽», фильтры и история по дням.
class _PointsHistoryScreenState extends ConsumerState<PointsHistoryScreen> {
  int _filter = 0; // 0 — все · 1 — начисления · 2 — списания

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      ref.read(loyaltyProvider.notifier).refresh();
    });
  }

  @override
  Widget build(BuildContext context) {
    final loyalty = ref.watch(loyaltyProvider);
    final stats = ref.watch(meStatsProvider).valueOrNull;
    final txns = switch (_filter) {
      1 => loyalty.transactions.where((t) => t.amount >= 0).toList(),
      2 => loyalty.transactions.where((t) => t.amount < 0).toList(),
      _ => loyalty.transactions,
    };

    return Scaffold(
      backgroundColor: AppColors.bg,
      appBar: AppBar(
        backgroundColor: AppColors.bg,
        title: const Text('Кошелёк'),
      ),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 24),
          children: [
            // Единая карта лояльности МАТА (дизайн-проект v5).
            Center(
              child: Builder(
                builder: (context) {
                  final user = ref.watch(authProvider).user;
                  return LoyaltyCard3D(
                    balance: loyalty.balance,
                    levelLabel: loyalty.levelTitle,
                    holderName: user?.name ?? 'Бегун КВАРТАЛ',
                    qrData: loyalty.code.isNotEmpty
                        ? loyalty.code
                        : (user?.id ?? ''),
                    tier: switch (loyalty.level) {
                      'platinum' => LoyaltyCardTier.platinum,
                      'gold' => LoyaltyCardTier.gold,
                      'silver' => LoyaltyCardTier.silver,
                      _ => LoyaltyCardTier.basic,
                    },
                  );
                },
              ),
            ),
            const SizedBox(height: 8),
            Center(
              child: Text(
                'нажми карту — QR для кассы МАТА Store',
                style: Theme.of(context).textTheme.labelSmall?.copyWith(
                  color: AppColors.faint,
                ),
              ),
            ),
            const SizedBox(height: 12),
            // Цепочка ценности: бег → баллы → скидка в Store.
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
              decoration: BoxDecoration(
                color: AppColors.block,
                borderRadius: BorderRadius.circular(12),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    '1 балл = 1 ₽ скидки в МАТА Store',
                    style: TextStyle(
                      fontSize: 13,
                      fontWeight: FontWeight.w700,
                      color: Color(0xFFEDEFE8),
                    ),
                  ),
                  if (stats != null) ...[
                    const SizedBox(height: 3),
                    Text(
                      '+${stats.earned} заработано · −${stats.spent} потрачено',
                      style: const TextStyle(
                        fontSize: 12,
                        fontWeight: FontWeight.w800,
                        color: Color(0xFFDFF45F),
                      ),
                    ),
                  ],
                ],
              ),
            ),
            const SizedBox(height: 12),
            // Фильтры.
            Row(
              children: [
                for (final (idx, label) in const [
                  (0, 'Все'),
                  (1, 'Начисления'),
                  (2, 'Списания'),
                ]) ...[
                  GestureDetector(
                    onTap: () => setState(() => _filter = idx),
                    child: AnimatedContainer(
                      duration: const Duration(milliseconds: 160),
                      padding: const EdgeInsets.symmetric(
                        horizontal: 13,
                        vertical: 7,
                      ),
                      decoration: BoxDecoration(
                        color: _filter == idx
                            ? AppColors.ink
                            : AppColors.paper,
                        borderRadius: BorderRadius.circular(9),
                        border: Border.all(
                          color: _filter == idx
                              ? AppColors.ink
                              : AppColors.line,
                        ),
                      ),
                      child: Text(
                        label,
                        style: TextStyle(
                          fontSize: 12.5,
                          fontWeight: FontWeight.w700,
                          color: _filter == idx
                              ? AppColors.bg
                              : AppColors.muted,
                        ),
                      ),
                    ),
                  ),
                  const SizedBox(width: 8),
                ],
              ],
            ),
            const SizedBox(height: 12),
            if (txns.isEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 40),
                child: Center(
                  child: Text(
                    loyalty.isLoading
                        ? 'Загрузка…'
                        : 'Пока нет операций с баллами',
                    style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                      color: AppColors.faint,
                    ),
                  ),
                ),
              )
            else
              ..._groupedTxns(context, txns),
          ],
        ),
      ),
    );
  }

  /// Группировка операций по дням: Сегодня · Вчера · ДД.ММ.
  List<Widget> _groupedTxns(BuildContext context, List<LoyaltyTxn> txns) {
    final out = <Widget>[];
    String? lastDay;
    for (final t in txns) {
      final day = _dayLabel(t.createdAt);
      if (day != lastDay) {
        lastDay = day;
        out.add(
          Padding(
            padding: const EdgeInsets.fromLTRB(4, 10, 4, 8),
            child: Text(
              day.toUpperCase(),
              style: TextStyle(
                fontSize: 10.5,
                fontWeight: FontWeight.w800,
                letterSpacing: 1.2,
                color: AppColors.faint,
              ),
            ),
          ),
        );
      }
      out.add(_txnRow(context, t));
      out.add(const SizedBox(height: 8));
    }
    return out;
  }

  Widget _txnRow(BuildContext context, LoyaltyTxn t) {
    final meta = _loyaltySourceMeta(t.source);
    final positive = t.amount >= 0;
    // Словарь цвета Ф7: начисления — лайм («моё» растёт), списания — тёплый.
    final accent = positive ? AppColors.limeDeep : AppColors.warm;
    return Container(
      padding: const EdgeInsets.all(13),
      decoration: BoxDecoration(
        color: AppColors.paper,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.line),
      ),
      child: Row(
        children: [
          Container(
            width: 38,
            height: 38,
            decoration: BoxDecoration(
              color: accent.withValues(alpha: 0.14),
              borderRadius: BorderRadius.circular(12),
            ),
            child: Icon(meta.icon, size: 19, color: accent),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  t.description.isNotEmpty ? t.description : meta.label,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                    color: AppColors.ink,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                const SizedBox(height: 1),
                Text(
                  _formatTxnTime(t.createdAt),
                  style: Theme.of(context).textTheme.labelSmall?.copyWith(
                    color: AppColors.faint,
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(width: 8),
          Text(
            '${positive ? '+' : ''}${t.amount}',
            style: TextStyle(
              fontFamily: AppTheme.fontDisplay,
              fontSize: 16,
              fontWeight: FontWeight.w800,
              color: accent,
            ),
          ),
        ],
      ),
    );
  }

  static String _dayLabel(String? createdAt) {
    final d = DateTime.tryParse(createdAt ?? '')?.toLocal();
    if (d == null) return 'Ранее';
    final now = DateTime.now();
    final today = DateTime(now.year, now.month, now.day);
    final day = DateTime(d.year, d.month, d.day);
    final diff = today.difference(day).inDays;
    if (diff == 0) return 'Сегодня';
    if (diff == 1) return 'Вчера';
    return '${day.day.toString().padLeft(2, '0')}.${day.month.toString().padLeft(2, '0')}';
  }

  static String _formatTxnTime(String? createdAt) {
    final d = DateTime.tryParse(createdAt ?? '')?.toLocal();
    if (d == null) return '';
    return '${d.hour.toString().padLeft(2, '0')}:${d.minute.toString().padLeft(2, '0')}';
  }
}

class _StatsRow extends ConsumerWidget {
  const _StatsRow();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final runs = ref.watch(completedRunsProvider);
    final totalKm = runs.fold<double>(0, (s, r) => s + r.distanceKm);
    final zones = runs.fold<int>(0, (s, r) => s + r.capturedZones);
    final wins = runs.where((r) => r.capturedTerritory).length;
    final kmText = totalKm >= 100
        ? totalKm.round().toString()
        : totalKm.toStringAsFixed(1);

    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: AppColors.bgCard,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AppColors.separator),
      ),
      child: Row(
        children: [
          _ProfileStat(value: kmText, label: 'км всего'),
          _Div(),
          _ProfileStat(value: '$zones', label: '\u0437\u043e\u043d'),
          _Div(),
          _ProfileStat(
            value: '${runs.length}',
            label: '\u043f\u0440\u043e\u0431\u0435\u0436\u0435\u043a',
          ),
          _Div(),
          _ProfileStat(value: '$wins', label: '\u043f\u043e\u0431\u0435\u0434'),
        ],
      ),
    );
  }
}

class _ProfileStat extends StatelessWidget {
  final String value, label;
  const _ProfileStat({required this.value, required this.label});

  @override
  Widget build(BuildContext context) {
    return Expanded(
      child: Column(
        children: [
          Text(
            value,
            style: Theme.of(context).textTheme.titleLarge?.copyWith(
              color: AppColors.electricBlue,
              fontWeight: FontWeight.w800,
            ),
          ),
          Text(
            label,
            style: Theme.of(context).textTheme.bodySmall,
            textAlign: TextAlign.center,
          ),
        ],
      ),
    );
  }
}

class _Div extends StatelessWidget {
  const _Div();

  @override
  Widget build(BuildContext context) =>
      Container(width: 1, height: 32, color: AppColors.separator);
}

/// Вечный личный след: исследованная площадь навсегда (не уменьшается со временем,
/// в отличие от живой территории на карте, которая распадается через 7 дней).
class _FootprintCard extends ConsumerWidget {
  const _FootprintCard();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final area = ref.watch(footprintAreaProvider).valueOrNull ?? 0;
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: AppColors.bgCard,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AppColors.separator),
      ),
      child: Row(
        children: [
          Container(
            width: 42,
            height: 42,
            decoration: BoxDecoration(
              color: AppColors.electricBlue.withValues(alpha: 0.12),
              shape: BoxShape.circle,
            ),
            child: Icon(
              CupertinoIcons.map_fill,
              color: AppColors.electricBlue,
              size: 21,
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Личная территория',
                  style: Theme.of(context).textTheme.titleSmall?.copyWith(
                    color: AppColors.textPrimary,
                    fontWeight: FontWeight.w700,
                  ),
                ),
                Text(
                  'исследовано навсегда',
                  style: Theme.of(
                    context,
                  ).textTheme.bodySmall?.copyWith(color: AppColors.textTertiary),
                ),
              ],
            ),
          ),
          Text(
            formatAreaM2(area),
            style: TextStyle(
              color: AppColors.electricBlue,
              fontSize: 17,
              fontWeight: FontWeight.w900,
            ),
          ),
        ],
      ),
    );
  }
}

/// Кроссовки из Store: остаток ресурса активной пары. Тап → трекер износа.
class _ShoesCard extends ConsumerWidget {
  const _ShoesCard();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final st = ref.watch(shoesProvider);
    final active = st.active;
    final String subtitle;
    final String? value;
    if (st.hasPending) {
      final n = st.pending.length;
      subtitle = n == 1
          ? 'новая пара — подтвердите'
          : '$n новых пар — подтвердите';
      value = null;
    } else if (!st.hasShoes) {
      subtitle = 'купи в МАТА Store';
      value = null;
    } else if (active != null) {
      subtitle = 'активная пара · износ ${active.wearPercent}%';
      value = '${active.remainingKm.toStringAsFixed(0)} км';
    } else {
      subtitle = 'ресурс исчерпан — пора заменить';
      value = null;
    }

    return GestureDetector(
      onTap: () => context.push('/profile/shoes'),
      child: Container(
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: AppColors.bgCard,
          borderRadius: BorderRadius.circular(16),
          border: Border.all(color: AppColors.separator),
        ),
        child: Row(
          children: [
            Container(
              width: 42,
              height: 42,
              decoration: BoxDecoration(
                color: AppColors.electricBlue.withValues(alpha: 0.12),
                shape: BoxShape.circle,
              ),
              child: Icon(
                Icons.directions_run,
                color: AppColors.electricBlue,
                size: 22,
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    'Кроссовки',
                    style: Theme.of(context).textTheme.titleSmall?.copyWith(
                          color: AppColors.textPrimary,
                          fontWeight: FontWeight.w700,
                        ),
                  ),
                  Text(
                    subtitle,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: Theme.of(context).textTheme.bodySmall?.copyWith(
                          color: AppColors.textTertiary,
                        ),
                  ),
                ],
              ),
            ),
            if (value != null) ...[
              Text(
                value,
                style: TextStyle(
                  color: AppColors.electricBlue,
                  fontSize: 16,
                  fontWeight: FontWeight.w900,
                ),
              ),
              const SizedBox(width: 6),
            ],
            Icon(
              CupertinoIcons.chevron_right,
              color: AppColors.textTertiary,
              size: 18,
            ),
          ],
        ),
      ),
    );
  }
}

class _ActivityHeatmap extends ConsumerWidget {
  const _ActivityHeatmap();

  static const _months = [
    'Январь',
    'Февраль',
    'Март',
    'Апрель',
    'Май',
    'Июнь',
    'Июль',
    'Август',
    'Сентябрь',
    'Октябрь',
    'Ноябрь',
    'Декабрь',
  ];

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final runs = ref.watch(completedRunsProvider);
    final now = DateTime.now();
    final daysInMonth = DateTime(now.year, now.month + 1, 0).day;
    final activeDays = <int>{
      for (final r in runs)
        if (r.finishedAt.year == now.year && r.finishedAt.month == now.month)
          r.finishedAt.day,
    };

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
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(
                '${_months[now.month - 1]} ${now.year}',
                style: Theme.of(context).textTheme.labelMedium,
              ),
              Text(
                '${activeDays.length} \u0430\u043a\u0442\u0438\u0432\u043d\u044b\u0445 \u0434\u043d\u0435\u0439',
                style: Theme.of(
                  context,
                ).textTheme.labelSmall?.copyWith(color: AppColors.textTertiary),
              ),
            ],
          ),
          const SizedBox(height: 10),
          Wrap(
            spacing: 4,
            runSpacing: 4,
            children: List.generate(daysInMonth, (i) {
              final day = i + 1;
              final active = activeDays.contains(day);
              return Container(
                width: 28,
                height: 28,
                decoration: BoxDecoration(
                  color: active ? AppColors.electricBlue : AppColors.bgElevated,
                  borderRadius: BorderRadius.circular(6),
                ),
                alignment: Alignment.center,
                child: Text(
                  '$day',
                  style: TextStyle(
                    fontSize: 10,
                    color: active ? AppColors.ink : AppColors.textDisabled,
                  ),
                ),
              );
            }),
          ),
        ],
      ),
    );
  }
}

// ── Ф4 «Статус бегуна» (утверждено 31.08.2026) ───────────────────────────────

/// Шапка уровня: цвет уровня красит карточку, прогресс — по периметру знака.
class _LevelHeader extends ConsumerWidget {
  const _LevelHeader();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final statsAsync = ref.watch(meStatsProvider);
    final stats = statsAsync.valueOrNull;
    final km = stats?.totalKm ?? 0;
    final level = RunnerLevel.fromKm(km);
    final next = level.next;
    final progress = level.progress(km);
    final left = next == null ? 0.0 : (next.minKm - km).clamp(0.0, 1e9).toDouble();
    // На чёрном «Городе» и сером «Асфальте» контраст держит светлый текст.
    const onLevel = Color(0xFFF2F4EE);
    final dimmed = onLevel.withValues(alpha: .78);

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(16, 15, 16, 15),
      decoration: BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [
            level.color,
            Color.lerp(level.color, const Color(0xFF14181C), .38)!,
          ],
        ),
        borderRadius: BorderRadius.circular(AppTheme.rMd),
      ),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'УРОВЕНЬ · ${level.roman}',
                  style: TextStyle(
                    fontSize: 10.5,
                    fontWeight: FontWeight.w800,
                    letterSpacing: 1.6,
                    color: dimmed,
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  level.title,
                  style: const TextStyle(
                    fontFamily: AppTheme.fontDisplay,
                    fontSize: 24,
                    fontWeight: FontWeight.w800,
                    height: 1.05,
                    color: onLevel,
                  ),
                ),
                const SizedBox(height: 6),
                Text(
                  statsAsync.isLoading
                      ? 'считаем километры…'
                      : next == null
                          ? '${_fmtKm(km)} км всего · статус вечный'
                          : '${_fmtKm(km)} км всего · до уровня «${next.title}» — ${_fmtKm(left)} км',
                  style: TextStyle(
                    fontSize: 12.5,
                    fontWeight: FontWeight.w600,
                    color: dimmed,
                  ),
                ),
                if (stats?.milestone != null) ...[
                  const SizedBox(height: 3),
                  Text(
                    'веха ${stats!.milestone!.atKm} км через '
                    '${_fmtKm(stats.milestone!.leftKm)} км '
                    '(+${stats.milestone!.reward} баллов)',
                    style: const TextStyle(
                      fontSize: 11.5,
                      fontWeight: FontWeight.w700,
                      color: Color(0xFFDFF45F),
                    ),
                  ),
                ],
              ],
            ),
          ),
          const SizedBox(width: 12),
          // Прогресс уровня — заполнение периметра знака (не кольцо!).
          SizedBox(
            width: 58,
            height: 58,
            child: Stack(
              fit: StackFit.expand,
              children: [
                // Подложка: полный контур слабым тоном.
                Opacity(
                  opacity: .30,
                  child: CustomPaint(
                    painter: KvartalMarkPainter(
                      outline: onLevel,
                      fill: Colors.transparent,
                      close: 1,
                    ),
                  ),
                ),
                CustomPaint(
                  painter: KvartalMarkPainter(
                    outline: onLevel,
                    fill: Colors.transparent,
                    close: 1,
                    draw: progress <= 0 ? .03 : progress,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  static String _fmtKm(double v) => v >= 100
      ? v.round().toString()
      : (v == v.roundToDouble() ? v.toStringAsFixed(0) : v.toStringAsFixed(1));
}

/// Недельный стрик: недели подряд с хотя бы одной пробежкой.
class _StreakRow extends ConsumerWidget {
  const _StreakRow();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    // Серверный стрик (учитывает часы и авто-заморозку); локальный — фолбэк.
    final server = ref.watch(meStatsProvider).valueOrNull?.streak;
    final localStreak = ref.watch(weekStreakProvider);
    final form = ref.watch(weekFormProvider);
    final streak = server?.weeks ?? localStreak;
    final ranThisWeek = server?.thisWeekDone ?? form.any((d) => d);
    final frozenCount = server?.frozenWeeks.length ?? 0;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      decoration: BoxDecoration(
        color: AppColors.paper,
        borderRadius: BorderRadius.circular(AppTheme.rSm),
        border: Border.all(color: AppColors.line),
      ),
      child: Row(
        children: [
          Icon(
            CupertinoIcons.flame_fill,
            size: 20,
            color: streak > 0 ? AppColors.limeDeep : AppColors.disabled,
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  streak > 0
                      ? 'Серия: $streak ${_weeks(streak)} подряд'
                      : 'Серия ещё не началась',
                  style: TextStyle(
                    fontSize: 14,
                    fontWeight: FontWeight.w800,
                    color: AppColors.ink,
                  ),
                ),
                const SizedBox(height: 1),
                Text(
                  streak > 0
                      ? (ranThisWeek
                          ? 'Эта неделя уже в серии — так держать'
                          : 'Пробеги на этой неделе, чтобы серия жила')
                      : 'Одна пробежка в неделю — и серия пошла',
                  style: TextStyle(fontSize: 12, color: AppColors.muted),
                ),
              ],
            ),
          ),
          if (frozenCount > 0) ...[
            const SizedBox(width: 8),
            Container(
              padding:
                  const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
              decoration: BoxDecoration(
                color: const Color(0xFF8FA8D8).withValues(alpha: .16),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Text(
                '❄ $frozenCount',
                style: const TextStyle(
                  fontSize: 11.5,
                  fontWeight: FontWeight.w800,
                  color: Color(0xFF8FA8D8),
                ),
              ),
            ),
          ],
        ],
      ),
    );
  }

  static String _weeks(int n) {
    final mod100 = n % 100;
    if (mod100 >= 11 && mod100 <= 14) return 'недель';
    return switch (n % 10) {
      1 => 'неделя',
      2 || 3 || 4 => 'недели',
      _ => 'недель',
    };
  }
}

/// Вход в трофейный зал (медали переехали туда с профиля).
class _TrophyEntryRow extends ConsumerWidget {
  const _TrophyEntryRow();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    // «Штамп МАТА»: счёт открытых медалей ведёт сервер (D-64).
    final medals = ref.watch(medalsProvider).valueOrNull;
    final unlocked = medals?.where((m) => m.earned).length;
    final total = medals?.length ?? kMedals.length;
    return Material(
      color: AppColors.paper,
      borderRadius: BorderRadius.circular(AppTheme.rSm),
      child: InkWell(
        onTap: () => context.push('/profile/trophies'),
        borderRadius: BorderRadius.circular(AppTheme.rSm),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 13),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(AppTheme.rSm),
            border: Border.all(color: AppColors.line),
          ),
          child: Row(
            children: [
              Container(
                width: 34,
                height: 34,
                alignment: Alignment.center,
                decoration: BoxDecoration(
                  color: AppColors.lime,
                  borderRadius: BorderRadius.circular(11),
                ),
                child: const Icon(
                  CupertinoIcons.rosette,
                  size: 18,
                  color: Color(0xFF171C19),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'Трофейный зал',
                      style: TextStyle(
                        fontSize: 14.5,
                        fontWeight: FontWeight.w800,
                        color: AppColors.ink,
                      ),
                    ),
                    Text(
                      unlocked == null
                          ? 'Штамп МАТА · $total наград'
                          : '$unlocked из $total медалей',
                      style: TextStyle(fontSize: 12, color: AppColors.muted),
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
