import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:mata_ui/mata_ui.dart';

import '../../../../core/theme/app_colors.dart';
import '../../../../core/theme/app_states.dart';
import '../../data/friends_provider.dart';
import '../../../moderation/data/moderation_provider.dart';
import '../../../moderation/presentation/report_sheet.dart';

/// Друзья (D-82, этап 2a): взаимные друзья, заявки, добавление.
/// Карта друзей и приватность — этап 2b/2c. Раздел за флагом kFriends.
class FriendsScreen extends ConsumerStatefulWidget {
  const FriendsScreen({super.key});

  @override
  ConsumerState<FriendsScreen> createState() => _FriendsScreenState();
}

/// Результаты поиска по контактам (D-85): null — ещё не искали, [] — не нашли.
final _contactsResultsProvider =
    StateProvider.autoDispose<List<FriendSummary>?>((_) => null);
final _contactsLoadingProvider = StateProvider.autoDispose<bool>((_) => false);

enum _Tab { friends, requests, add }

class _FriendsScreenState extends ConsumerState<FriendsScreen> {
  _Tab _tab = _Tab.friends;
  String _query = '';

  @override
  Widget build(BuildContext context) {
    final data = ref.watch(friendsProvider).valueOrNull ?? const FriendsData();
    final pending = data.incoming.length;

    return Scaffold(
      backgroundColor: AppColors.bg,
      appBar: AppBar(
        backgroundColor: AppColors.bg,
        elevation: 0,
        title: const Text('Друзья',
            style: TextStyle(fontWeight: FontWeight.w800, fontSize: 19)),
        actions: [
          IconButton(
            tooltip: 'Приватность',
            icon: const Icon(CupertinoIcons.shield_lefthalf_fill),
            onPressed: () => context.push('/profile/friends/privacy'),
          ),
        ],
      ),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 4, 16, 10),
            child: _Segment(
              tab: _tab,
              pending: pending,
              onPick: (t) => setState(() => _tab = t),
            ),
          ),
          Expanded(
            child: switch (_tab) {
              _Tab.friends => _FriendsList(data: data),
              _Tab.requests => _Requests(data: data),
              _Tab.add =>
                _AddPanel(query: _query, onQuery: (q) => setState(() => _query = q)),
            },
          ),
        ],
      ),
    );
  }
}

class _Segment extends StatelessWidget {
  final _Tab tab;
  final int pending;
  final ValueChanged<_Tab> onPick;
  const _Segment({required this.tab, required this.pending, required this.onPick});

  @override
  Widget build(BuildContext context) {
    Widget seg(_Tab t, String label, {int badge = 0}) {
      final active = t == tab;
      return Expanded(
        child: GestureDetector(
          onTap: () => onPick(t),
          child: AnimatedContainer(
            duration: const Duration(milliseconds: 150),
            alignment: Alignment.center,
            padding: const EdgeInsets.symmetric(vertical: 9),
            decoration: BoxDecoration(
              color: active ? AppColors.lime : Colors.transparent,
              borderRadius: BorderRadius.circular(9),
            ),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(label,
                    style: TextStyle(
                      fontSize: 13,
                      fontWeight: FontWeight.w700,
                      color: active ? const Color(0xFF141A08) : AppColors.ink,
                    )),
                if (badge > 0) ...[
                  const SizedBox(width: 6),
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
                    decoration: BoxDecoration(
                      color: active ? const Color(0xFF141A08) : AppColors.lime,
                      borderRadius: BorderRadius.circular(99),
                    ),
                    child: Text('$badge',
                        style: TextStyle(
                          fontSize: 11,
                          fontWeight: FontWeight.w800,
                          color: active ? AppColors.lime : const Color(0xFF141A08),
                        )),
                  ),
                ],
              ],
            ),
          ),
        ),
      );
    }

    return Container(
      padding: const EdgeInsets.all(3),
      decoration: BoxDecoration(
        color: AppColors.paper,
        borderRadius: BorderRadius.circular(11),
        border: Border.all(color: AppColors.line),
      ),
      child: Row(
        children: [
          seg(_Tab.friends, 'Друзья'),
          seg(_Tab.requests, 'Заявки', badge: pending),
          seg(_Tab.add, 'Добавить'),
        ],
      ),
    );
  }
}

class _Avatar extends StatelessWidget {
  final FriendSummary f;
  const _Avatar(this.f);
  @override
  Widget build(BuildContext context) {
    return Container(
      width: 44,
      height: 44,
      alignment: Alignment.center,
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        color: AppColors.lime,
        border: Border.all(color: AppColors.bg, width: 2),
      ),
      child: Text(f.initial,
          style: const TextStyle(
              color: Color(0xFF141A08), fontWeight: FontWeight.w800, fontSize: 17)),
    );
  }
}

class _Row extends StatelessWidget {
  final FriendSummary f;
  final Widget trailing;
  const _Row({required this.f, required this.trailing});
  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.fromLTRB(12, 10, 10, 10),
      decoration: BoxDecoration(
        color: AppColors.paper,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppColors.line),
      ),
      child: Row(
        children: [
          _Avatar(f),
          const SizedBox(width: 12),
          Expanded(
            child: Text(f.name,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(
                    color: AppColors.ink, fontSize: 15, fontWeight: FontWeight.w700)),
          ),
          trailing,
        ],
      ),
    );
  }
}

Widget _pill(String text, {Color? bg, Color? fg, VoidCallback? onTap, IconData? icon}) {
  final child = Container(
    padding: const EdgeInsets.symmetric(horizontal: 13, vertical: 8),
    decoration: BoxDecoration(
      color: bg ?? Colors.transparent,
      borderRadius: BorderRadius.circular(10),
      border: bg == null ? Border.all(color: AppColors.line) : null,
    ),
    child: Row(mainAxisSize: MainAxisSize.min, children: [
      if (icon != null) ...[
        Icon(icon, size: 14, color: fg ?? AppColors.ink),
        const SizedBox(width: 5),
      ],
      Text(text,
          style: TextStyle(
              color: fg ?? AppColors.ink, fontSize: 12.5, fontWeight: FontWeight.w800)),
    ]),
  );
  return onTap == null ? child : GestureDetector(onTap: onTap, child: child);
}

/// «…» у строки человека: пожаловаться или заблокировать.
///
/// Обе кнопки живут рядом с человеком, а не в настройках: защита, до которой
/// надо дойти через три экрана, не работает в тот момент, когда она нужна.
Widget _moreButton(BuildContext context, WidgetRef ref, FriendSummary f) {
  return IconButton(
    tooltip: 'Ещё',
    visualDensity: VisualDensity.compact,
    constraints: const BoxConstraints(),
    padding: const EdgeInsets.only(left: 6),
    icon: Icon(CupertinoIcons.ellipsis, size: 18, color: AppColors.muted),
    onPressed: () => _showPersonMenu(context, ref, f),
  );
}

void _showPersonMenu(BuildContext context, WidgetRef ref, FriendSummary f) {
  showModalBottomSheet<void>(
    context: context,
    backgroundColor: Colors.transparent,
    builder: (sheetCtx) => Container(
      decoration: BoxDecoration(
        color: AppColors.paper,
        borderRadius: const BorderRadius.vertical(top: Radius.circular(22)),
      ),
      padding: const EdgeInsets.fromLTRB(8, 10, 8, 10),
      child: SafeArea(
        top: false,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              width: 38,
              height: 4,
              decoration: BoxDecoration(
                color: AppColors.line,
                borderRadius: BorderRadius.circular(2),
              ),
            ),
            const SizedBox(height: 14),
            ListTile(
              leading: Icon(CupertinoIcons.exclamationmark_bubble,
                  color: AppColors.ink),
              title: Text('Пожаловаться',
                  style: TextStyle(
                      color: AppColors.ink, fontWeight: FontWeight.w600)),
              onTap: () {
                Navigator.of(sheetCtx).pop();
                showReportSheet(context,
                    targetType: 'user', targetId: f.userId, targetName: f.name);
              },
            ),
            ListTile(
              leading: Icon(CupertinoIcons.nosign, color: AppColors.error),
              title: Text('Заблокировать',
                  style: TextStyle(
                      color: AppColors.error, fontWeight: FontWeight.w600)),
              onTap: () {
                Navigator.of(sheetCtx).pop();
                _confirmBlock(context, ref, f);
              },
            ),
          ],
        ),
      ),
    ),
  );
}

Future<void> _confirmBlock(
    BuildContext context, WidgetRef ref, FriendSummary f) async {
  final ok = await showDialog<bool>(
    context: context,
    builder: (ctx) => AlertDialog(
      backgroundColor: AppColors.paper,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
      title: Text('Заблокировать ${f.name}?'),
      content: Text(
        'Вы перестанете видеть друг друга в поиске, подсказках и на карте, '
        'а заявки от него не придут. Если вы друзья — дружба прервётся.',
        style: TextStyle(color: AppColors.muted),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(ctx).pop(false),
          child: Text('Отмена', style: TextStyle(color: AppColors.muted)),
        ),
        FilledButton(
          onPressed: () => Navigator.of(ctx).pop(true),
          style: FilledButton.styleFrom(backgroundColor: AppColors.error),
          child: const Text('Заблокировать'),
        ),
      ],
    ),
  );
  if (ok != true) return;
  final done = await ref.read(moderationActionsProvider).block(f.userId);
  if (!context.mounted) return;
  ScaffoldMessenger.of(context).showSnackBar(
    SnackBar(
      content: Text(done
          ? '${f.name} заблокирован — список в «Друзья → Приватность»'
          : 'Не удалось — попробуйте позже'),
    ),
  );
}

class _FriendsList extends ConsumerWidget {
  final FriendsData data;
  const _FriendsList({required this.data});
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    if (data.friends.isEmpty) {
      return MataEmpty(
        icon: CupertinoIcons.person_2,
        iconColor: AppStates.icon,
        title: 'Пока нет друзей',
        titleStyle: AppStates.title,
        hint: 'Найди своих на вкладке «Добавить» — по имени, из клуба или по контактам.',
        hintStyle: AppStates.hint,
      );
    }
    final act = ref.read(friendsActionsProvider);
    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 4, 16, 24),
      children: [
        for (final f in data.friends)
          _Row(
            f: f,
            trailing: Row(mainAxisSize: MainAxisSize.min, children: [
              _pill('Убрать',
                  fg: AppColors.muted, onTap: () => act.remove(f.userId)),
              _moreButton(context, ref, f),
            ]),
          ),
      ],
    );
  }
}

class _Requests extends ConsumerWidget {
  final FriendsData data;
  const _Requests({required this.data});
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    if (data.incoming.isEmpty && data.outgoing.isEmpty) {
      return MataEmpty(
        icon: CupertinoIcons.tray,
        iconColor: AppStates.icon,
        title: 'Заявок нет',
        titleStyle: AppStates.title,
        hint: 'Входящие и отправленные заявки в друзья появятся здесь.',
        hintStyle: AppStates.hint,
      );
    }
    final act = ref.read(friendsActionsProvider);
    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 4, 16, 24),
      children: [
        if (data.incoming.isNotEmpty) ...[
          _label('Входящие'),
          for (final f in data.incoming)
            _Row(
              f: f,
              trailing: Row(mainAxisSize: MainAxisSize.min, children: [
                _pill('Принять',
                    bg: AppColors.lime,
                    fg: const Color(0xFF141A08),
                    onTap: () => act.accept(f.userId)),
                const SizedBox(width: 8),
                _pill('Нет',
                    fg: AppColors.muted, onTap: () => act.reject(f.userId)),
                _moreButton(context, ref, f),
              ]),
            ),
        ],
        if (data.outgoing.isNotEmpty) ...[
          _label('Отправленные'),
          for (final f in data.outgoing)
            _Row(
              f: f,
              trailing: _pill('Отменить',
                  fg: AppColors.muted, onTap: () => act.reject(f.userId)),
            ),
        ],
      ],
    );
  }

  Widget _label(String t) => Padding(
        padding: const EdgeInsets.fromLTRB(2, 8, 0, 8),
        child: Text(t.toUpperCase(),
            style: TextStyle(
                color: AppColors.ink,
                fontSize: 11.5,
                fontWeight: FontWeight.w700,
                letterSpacing: .6)),
      );
}

class _AddPanel extends ConsumerWidget {
  final String query;
  final ValueChanged<String> onQuery;
  const _AddPanel({required this.query, required this.onQuery});

  Widget _addTrailing(WidgetRef ref, FriendSummary f) {
    final act = ref.read(friendsActionsProvider);
    return switch (f.status) {
      'friends' => _pill('В друзьях', fg: AppColors.muted, icon: CupertinoIcons.checkmark_alt),
      'outgoing' => _pill('Отправлено', fg: AppColors.muted),
      'incoming' => _pill('Принять',
          bg: AppColors.lime, fg: const Color(0xFF141A08), onTap: () => act.accept(f.userId)),
      _ => _pill('Добавить',
          bg: AppColors.lime, fg: const Color(0xFF141A08), onTap: () => act.request(f.userId)),
    };
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final results = query.trim().length >= 2
        ? (ref.watch(friendSearchProvider(query)).valueOrNull ?? const [])
        : const <FriendSummary>[];
    final suggestions =
        ref.watch(friendSuggestionsProvider).valueOrNull ?? const <FriendSummary>[];
    final contacts = ref.watch(_contactsResultsProvider);
    final contactsLoading = ref.watch(_contactsLoadingProvider);

    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 4, 16, 24),
      children: [
        // Поиск по имени
        TextField(
          onChanged: onQuery,
          style: TextStyle(color: AppColors.ink, fontSize: 15),
          decoration: InputDecoration(
            hintText: 'Поиск по имени',
            hintStyle: TextStyle(color: AppColors.muted),
            prefixIcon: Icon(CupertinoIcons.search, size: 18, color: AppColors.muted),
            filled: true,
            fillColor: AppColors.paper,
            contentPadding: const EdgeInsets.symmetric(vertical: 4),
            enabledBorder: OutlineInputBorder(
                borderRadius: BorderRadius.circular(12),
                borderSide: BorderSide(color: AppColors.line)),
            focusedBorder: OutlineInputBorder(
                borderRadius: BorderRadius.circular(12),
                borderSide: BorderSide(color: AppColors.lime)),
          ),
        ),
        const SizedBox(height: 10),
        // Пригласить ссылкой
        GestureDetector(
          onTap: () {
            Clipboard.setData(const ClipboardData(
                text: 'Бегай со мной в «Квартале» (МАТА): https://mata-club.ru/app.html'));
            ScaffoldMessenger.of(context).showSnackBar(
                const SnackBar(content: Text('Ссылка-приглашение скопирована')));
          },
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 13),
            decoration: BoxDecoration(
              color: AppColors.paper,
              borderRadius: BorderRadius.circular(12),
              border: Border.all(color: AppColors.line),
            ),
            child: Row(children: [
              Icon(CupertinoIcons.link, size: 17, color: AppColors.lime),
              const SizedBox(width: 10),
              Expanded(
                child: Text('Пригласить по ссылке',
                    style: TextStyle(
                        color: AppColors.ink, fontSize: 14, fontWeight: FontWeight.w700)),
              ),
              Icon(CupertinoIcons.doc_on_doc, size: 16, color: AppColors.muted),
            ]),
          ),
        ),
        const SizedBox(height: 10),
        // Найти по контактам (D-85): читаем контакты, хешируем номера, сверяем.
        GestureDetector(
          onTap: contactsLoading
              ? null
              : () async {
                  ref.read(_contactsLoadingProvider.notifier).state = true;
                  final r = await ref.read(friendsActionsProvider).matchContacts();
                  ref.read(_contactsLoadingProvider.notifier).state = false;
                  if (!r.granted) {
                    if (context.mounted) {
                      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
                          content: Text('Нет доступа к контактам')));
                    }
                    return;
                  }
                  ref.read(_contactsResultsProvider.notifier).state = r.results;
                },
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 13),
            decoration: BoxDecoration(
              color: AppColors.paper,
              borderRadius: BorderRadius.circular(12),
              border: Border.all(color: AppColors.line),
            ),
            child: Row(children: [
              Icon(CupertinoIcons.phone, size: 17, color: AppColors.lime),
              const SizedBox(width: 10),
              Expanded(
                child: Text('Найти по контактам',
                    style: TextStyle(
                        color: AppColors.ink, fontSize: 14, fontWeight: FontWeight.w700)),
              ),
              if (contactsLoading)
                const SizedBox(
                    width: 16, height: 16,
                    child: MataLoading(radius: 8))
              else
                Icon(CupertinoIcons.chevron_right, size: 16, color: AppColors.muted),
            ]),
          ),
        ),
        const SizedBox(height: 18),

        if (contacts != null) ...[
          _hdr('Из контактов'),
          if (contacts.isEmpty)
            _muted('Из контактов пока никто не в «Квартале».')
          else
            for (final f in contacts) _Row(f: f, trailing: _addTrailing(ref, f)),
          const SizedBox(height: 18),
        ],

        if (query.trim().length >= 2) ...[
          _hdr('Результаты'),
          if (results.isEmpty)
            _muted('Никого не нашли по «${query.trim()}»')
          else
            for (final f in results) _Row(f: f, trailing: _addTrailing(ref, f)),
          const SizedBox(height: 18),
        ],

        _hdr('Из твоего клуба'),
        if (suggestions.isEmpty)
          _muted('Подсказок пока нет. Вступи в клуб — предложим одноклубников.')
        else
          for (final f in suggestions) _Row(f: f, trailing: _addTrailing(ref, f)),
      ],
    );
  }

  Widget _hdr(String t) => Padding(
        padding: const EdgeInsets.fromLTRB(2, 0, 0, 10),
        child: Text(t.toUpperCase(),
            style: TextStyle(
                color: AppColors.ink,
                fontSize: 11.5,
                fontWeight: FontWeight.w700,
                letterSpacing: .6)),
      );

  Widget _muted(String t) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 8),
        child: Text(t, style: TextStyle(color: AppColors.muted, fontSize: 14, height: 1.4)),
      );
}
